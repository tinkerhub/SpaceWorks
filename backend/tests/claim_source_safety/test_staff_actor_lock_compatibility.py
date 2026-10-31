"""Actor NO KEY UPDATE orders real deactivation and fresh claim authorization."""
import json

import pytest
from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import MemberClaimCode, User
from apps.accounts.services_claim import issue_claim_code
from apps.accounts.services_tokens import blacklist_device_family
from apps.audit.models import AuditLog
from tests.box_parent_safety.pg_helpers import blocked_by, workers

from .test_same_actor_issue_ordering import locking_select, sqlstates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("winner", ["issuance", "writer"])
def test_actor_deactivation_serializes_with_claim_issuance(
    claim_lab, record_property, winner,
):
    lab = claim_lab
    # Keep this authenticated actor stale: only the independent writer updates it.
    assert lab.actor.is_active is True
    assert lab.actor.pk != lab.user.pk
    blacklist_device_family(lab.family, revoke_grant=True)
    actor_rows = User.objects.filter(pk=lab.actor.pk)
    target_rows = User.objects.filter(pk=lab.user.pk)
    memberships = type(lab.memberships[0]).objects.filter(user=lab.user).order_by("pk")
    claims = MemberClaimCode.objects.all().order_by("pk")
    audits = AuditLog.objects.all().order_by("pk")
    issuance = audits.filter(action="member.claim_code_issued")
    actor_before = actor_rows.values().get()
    target_before = target_rows.values().get()
    memberships_before = list(memberships.values())
    claims_before = list(claims.values())
    audits_before = list(audits.values())
    claim_ids = {row["id"] for row in claims_before}
    audit_ids = {row["id"] for row in audits_before}
    issuance_ids = set(issuance.values_list("pk", flat=True))

    def actor_lock(statement):
        return (locking_select(statement, "accounts_user", lab.actor.pk)
                and statement.sql.rstrip().endswith("FOR NO KEY UPDATE"))

    def actor_update(statement):
        return (statement.sql == 'UPDATE "accounts_user" SET "is_active" = %s '
                'WHERE "accounts_user"."id" = %s'
                and statement.params == (False, lab.actor.pk))

    def deactivate():
        with transaction.atomic():
            # QuerySet.update deliberately leaves timestamps and the actor object alone.
            count = User.objects.filter(pk=lab.actor.pk).update(is_active=False)
        return count

    def issue():
        try:
            return issue_claim_code(actor=lab.actor, makerspace_id=lab.spaces[0].pk,
                                    membership_id=lab.memberships[0].pk)
        except PermissionDenied as refused:
            if winner == "writer":
                return refused
            raise

    owned, edges, finish_errors = {}, [], []
    observation_error = None
    try:
        with workers() as start:
            try:
                if winner == "issuance":
                    issuing = owned["issuer"] = start(issue, pause=actor_lock)
                    issuing.paused()  # Actual ActorUser SELECT completed inside atomic().
                    writer = owned["writer"] = start(deactivate)
                    pending = blocked_by(writer, issuing.pid, actor_update)
                    waiter, blocker = writer, issuing
                    completed_predicate = actor_lock
                else:
                    writer = owned["writer"] = start(deactivate, pause=actor_update)
                    writer.paused()  # Actual UPDATE completed; transaction still uncommitted.
                    issuing = owned["issuer"] = start(issue)
                    pending = blocked_by(issuing, writer.pid, actor_lock)
                    waiter, blocker = issuing, writer
                    completed_predicate = actor_update
                edges.append({"waiter": waiter.pid, "blocker": blocker.pid,
                              "template": pending.sql, "completed": pending.completed})
                assert waiter.pid != blocker.pid
                assert pending.pid == waiter.pid and not pending.completed
                assert any(s.completed and completed_predicate(s)
                           for s in blocker.statements)
            except BaseException as exc:
                observation_error = exc
            finally:
                # Release BOTH first, then settle BOTH even if one finish raises.
                for worker in owned.values():
                    worker.release.set()
                for worker in owned.values():
                    try:
                        worker.finish()
                    except BaseException as exc:
                        finish_errors.append(exc)
        errors = finish_errors + ([observation_error] if observation_error else [])
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("Actor ordering workers/observation failed", errors)

        assert pending.completed
        assert writer.result == 1
        assert lab.actor.is_active is True
        assert actor_rows.values().get() == {**actor_before, "is_active": False}
        assert target_rows.values().get() == target_before
        assert list(memberships.values()) == memberships_before
        if winner == "issuance":
            # Inspect the durable row, never render IssuedClaimCode (it holds a secret).
            added = claims.exclude(pk__in=claim_ids)
            assert added.count() == 1
            new_claim = added.get()
            assert new_claim.issued_by_id == lab.actor.pk
            assert new_claim.membership_id == lab.memberships[0].pk
            assert new_claim.revoked_at is None and new_claim.consumed_at is None
            issued_claim_id = issuing.result.claim.pk
            assert issued_claim_id == new_claim.pk
            assert claims.count() == len(claim_ids) + 1
            assert set(claims.filter(pk__in=claim_ids).values_list("pk", flat=True)) == claim_ids
            added_issuance = issuance.exclude(pk__in=issuance_ids)
            assert added_issuance.count() == 1
            event = added_issuance.get()
            assert event.actor_id == lab.actor.pk
            assert event.makerspace_id == lab.spaces[0].pk
            assert event.target_type == lab.memberships[0]._meta.label_lower
            assert event.target_id == str(lab.memberships[0].pk)
            assert issuance.count() == len(issuance_ids) + 1
            assert list(audits.filter(pk__in=audit_ids).values()) == audits_before
            # Real reissue also revokes the prior credential and its provenanced presence.
            prior = claims.get(pk=lab.credentials[0].claim.pk)
            assert prior.revoked_at is not None and prior.revoked_by_id == lab.actor.pk
        else:
            was_refused = isinstance(issuing.result, PermissionDenied)
            assert was_refused
            assert list(claims.values()) == claims_before
            assert list(audits.values()) == audits_before

        # Both orders must refuse a second real issuance using the original stale actor.
        claims_after = list(claims.values())
        audits_after = list(audits.values())
        with pytest.raises(PermissionDenied):
            issue_claim_code(actor=lab.actor, makerspace_id=lab.spaces[0].pk,
                             membership_id=lab.memberships[0].pk)
        assert list(claims.values()) == claims_after
        assert list(audits.values()) == audits_after
        assert target_rows.values().get() == target_before
        assert list(memberships.values()) == memberships_before
        assert actor_rows.values().get() == {**actor_before, "is_active": False}
        assert lab.actor.is_active is True
    finally:
        # Parameter-free diagnostics survive failures, after owned workers have settled.
        record_property("staff_actor_lock_compatibility", json.dumps({
            "winner": winner,
            "observed_wait_edges": edges,
            "observation_error": sqlstates(observation_error),
            "finish_errors": [sqlstates(error) for error in finish_errors],
            "workers": {name: {
                "pid": worker.pid,
                "settled": not worker.thread.is_alive(),
                "result_type": type(worker.result).__name__,
                "exception_chain": sqlstates(worker.error),
                "refusal_chain": (sqlstates(worker.result)
                                  if isinstance(worker.result, PermissionDenied) else []),
                "sql": [{"template": s.sql, "completed": s.completed}
                        for s in worker.statements],
            } for name, worker in owned.items()},
        }))
