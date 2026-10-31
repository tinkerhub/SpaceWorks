"""Same-actor native conversion must win without an audit-FK/issuer deadlock."""
import json

import pytest
from django.db import connection

from apps.accounts.models import MemberClaimCode, User
from apps.accounts.services_claim import ClaimCodeIneligible, issue_claim_code
from apps.accounts.services_tokens import blacklist_device_family
from apps.audit.models import AuditLog
from tests.box_parent_safety.pg_helpers import blocked_by, workers

from .callers import prepare
from .test_transitions import assert_closed_lifecycle

pytestmark = pytest.mark.django_db(transaction=True)


def locking_select(statement, table, pk):
    sql = statement.sql
    prefix, matched, _ = sql.partition(f'"{table}"."id" = %s')
    return (sql.startswith("SELECT ") and f'FROM "{table}"' in sql
            and " FOR " in sql and bool(matched)
            and statement.params[prefix.count("%s")] == pk)


def sqlstates(error):
    chain, seen = [], set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        chain.append({"type": type(error).__name__,
                      "sqlstate": getattr(error, "sqlstate", None)
                      or getattr(error, "pgcode", None)})
        error = error.__cause__ or error.__context__
    return chain


def test_same_actor_native_winner_freshly_refuses_physical_issue(
    claim_lab, monkeypatch, record_property,
):
    lab = claim_lab
    call = prepare(lab, "native", monkeypatch)
    # Reuse the authenticated native identity for real issuance; no actor split.
    assert int(lab.native.session["_auth_user_id"]) == lab.actor.pk
    assert lab.actor.pk != lab.user.pk
    assert len(lab.credentials) == 2
    blacklist_device_family(lab.family, revoke_grant=True)
    actor_before = User.objects.filter(pk=lab.actor.pk).values().get()
    memberships = type(lab.memberships[0]).objects.filter(user=lab.user).order_by("pk")
    memberships_before = list(memberships.values())
    claims = MemberClaimCode.objects.all().order_by("pk")
    claim_ids = list(claims.values_list("pk", flat=True))
    consumed_before = list(claims.values_list("pk", "consumed_at", "consumed_ip"))
    issuance = AuditLog.objects.filter(action="member.claim_code_issued").order_by("pk")
    issued_audit_ids = list(issuance.values_list("pk", flat=True))
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.conname, c.condeferrable, c.condeferred FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey) "
            "WHERE c.contype='f' AND c.conrelid=%s::regclass "
            "AND c.confrelid=%s::regclass AND a.attname=%s",
            [AuditLog._meta.db_table, User._meta.db_table,
             AuditLog._meta.get_field("actor").column],
        )
        actor_fks = [dict(zip(("name", "deferrable", "initially_deferred"), row))
                     for row in cursor.fetchall()]

    def target_user(statement):
        return (locking_select(statement, "accounts_user", lab.user.pk)
                and statement.sql.rstrip().endswith("FOR UPDATE"))

    def target_membership(statement):
        return (locking_select(statement, "makerspaces_makerspacemembership",
                               lab.memberships[0].pk)
                and statement.sql.rstrip().endswith("FOR UPDATE"))

    def issue_loser():
        try:
            return issue_claim_code(actor=lab.actor, makerspace_id=lab.spaces[0].pk,
                                   membership_id=lab.memberships[0].pk)
        except ClaimCodeIneligible as refused:
            return refused  # Only this policy refusal is an expected typed result.

    owned, edges, finish_errors = {}, [], []
    observation_error = None
    try:
        with workers() as start:
            try:
                assert len(actor_fks) == 1
                native = owned["native"] = start(call, pause=target_user)
                native.paused()  # Actual completed TargetUser full FOR UPDATE.
                issuing = owned["issuer"] = start(issue_loser)
                pending = blocked_by(issuing, native.pid, target_user)
                edges.append({"waiter": issuing.pid, "blocker": native.pid})
                assert issuing.pid != native.pid
                assert any(s.completed and locking_select(s, "accounts_user", lab.actor.pk)
                           for s in issuing.statements)
                assert any(s.completed and target_membership(s) for s in issuing.statements)
                assert pending.pid == issuing.pid and not pending.completed
            except BaseException as exc:
                observation_error = exc
            finally:
                # Release both before joining either. A victim must not hide its peer.
                for worker in owned.values():
                    worker.release.set()
                for worker in owned.values():
                    try:
                        worker.finish()
                    except BaseException as exc:
                        finish_errors.append(exc)
        # workers() has also performed its owned-backend cleanup before propagation.
        for error in finish_errors + [observation_error]:
            if error is not None:
                raise error
    finally:
        # Parameter-free proof is retained on red and green, after both settle.
        record_property("same_actor_issue_ordering", json.dumps({
            "audit_actor_fk": actor_fks,
            "observed_wait_edges": edges,
            "observation_error": sqlstates(observation_error),
            "finish_errors": [sqlstates(error) for error in finish_errors],
            "workers": {name: {
                "pid": worker.pid,
                "settled": not worker.thread.is_alive(),
                "result_type": type(worker.result).__name__,
                "response_status": getattr(worker.result, "status_code", None),
                "exception_chain": sqlstates(worker.error),
                "actor_lock_modes": ["FOR " + s.sql.rsplit(" FOR ", 1)[1].strip()
                    for s in worker.statements if s.completed
                    and locking_select(s, "accounts_user", lab.actor.pk)],
                "sql": [{"template": s.sql, "completed": s.completed}
                        for s in worker.statements],
            } for name, worker in owned.items()},
        }))

    assert native.result.status_code == 302
    assert pending.completed and target_user(pending)
    assert isinstance(issuing.result, ClaimCodeIneligible)
    assert_closed_lifecycle(lab, "native")  # Includes the actual replacement password.
    assert list(claims.values_list("pk", flat=True)) == claim_ids
    assert list(issuance.values_list("pk", flat=True)) == issued_audit_ids
    assert list(claims.values_list("pk", "consumed_at", "consumed_ip")) == consumed_before
    assert all(item.claim.revoked_at is not None for item in lab.credentials)
    assert list(memberships.values()) == memberships_before
    assert User.objects.filter(pk=lab.actor.pk).values().get() == actor_before
    for action in ("member.walk_in_transitioned", "user.password_changed"):
        event = AuditLog.objects.get(action=action, target_type="accounts.user",
                                     target_id=str(lab.user.pk))
        assert event.actor_id == lab.actor.pk
        assert event.makerspace_id is None
