"""Both real callers and a small standalone control preserve canonical closure."""
import json

import pytest
from django.contrib.admin.models import LogEntry
from django.db import IntegrityError, connection
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import OidcBrowserAttempt
from apps.accounts.models_devices import DeviceGrant
from apps.accounts.models_social import SocialIdentity
from apps.audit.models import AuditLog
from tests.box_parent_safety.pg_helpers import workers

from .callers import assert_retry, prepare
from .conftest import NEW_PASSWORD
from .observations import NProof, TransitionProbe, exclusive_n, row_lock
from .state import domain, frozen, tenant_and_transition_audits

pytestmark = pytest.mark.django_db(transaction=True)


def assert_closed_lifecycle(lab, kind):
    lab.user.refresh_from_db()
    assert lab.user.is_walk_in is False
    assert lab.user.check_password(NEW_PASSWORD) if kind == "native" else not lab.user.has_usable_password()
    for item in lab.credentials:
        item.claim.refresh_from_db()
        item.presence.refresh_from_db()
        assert item.claim.revoked_at is not None
        assert item.presence.ended_at is not None
        assert item.presence.end_reason == "claim_revoked"
        assert item.presence.ended_by_id is None
        events = AuditLog.objects.filter(action="presence.ended_claim_revoked",
            target_id=str(item.presence.pk), target_type="presence.presencesession")
        assert events.count() == 1
        event = events.get()
        assert event.makerspace_id == item.presence.makerspace_id
        assert event.actor_id is None
        assert event.meta == {"claim_session_id": str(item.claim.session_id)}
    lab.unrelated.refresh_from_db()
    assert lab.unrelated.ended_at is None
    lab.grant.refresh_from_db()
    lab.family.refresh_from_db()
    assert lab.grant.status == DeviceGrant.Status.REVOKED
    assert lab.family.revoked_at is not None
    assert set(BlacklistedToken.objects.filter(token_id__in=lab.old_token_ids)
               .values_list("token_id", flat=True)) == lab.old_token_ids
    event = AuditLog.objects.get(action="member.walk_in_transitioned", target_id=str(lab.user.pk))
    assert event.actor_id == (None if kind == "oidc" else lab.actor.pk)
    assert event.makerspace_id is None
    if kind == "oidc":
        assert lab.user.email_verified_at is not None
        linked = SocialIdentity.objects.get(user=lab.user)
        assert (linked.provider, linked.provider_sub) == ("oidc:campus", "claim-source-subject")
        # Exactly the post-transition session is still usable.
        outstanding = OutstandingToken.objects.filter(user=lab.user)
        assert outstanding.count() == len(lab.old_token_ids) + 1
        assert BlacklistedToken.objects.filter(token__in=outstanding).count() == len(lab.old_token_ids)
    elif kind == "native":
        assert LogEntry.objects.filter(user=lab.actor, object_id=str(lab.user.pk), action_flag=2).count() == 1


@pytest.mark.parametrize("kind", ["native", "oidc", "service"])
def test_open_all_owned_ns_precede_rows_and_retain_original_locks_through_commit(
    claim_lab, kind, monkeypatch, record_property,
):
    call = prepare(claim_lab, kind, monkeypatch)
    proof = NProof([space.pk for space in claim_lab.spaces], record_property)
    probe = TransitionProbe()
    try:
        with workers() as start, probe:
            request = start(probe.run(call))
            probe.before_rows.wait(request)
            proof.observe("before_first_target_row_lock")
            assert not [row for row in probe.sql if row["completed"] and "FOR UPDATE" in row["sql"]
                        and any(f'FROM "{table}"' in row["sql"] for table in (
                            "accounts_user", "makerspaces_makerspacemembership", "accounts_memberclaimcode"))]
            key = claim_lab.spaces[0].pk
            exclusive = start(lambda: exclusive_n(key))
            proof.queued(exclusive, key)
            probe.before_rows.release.set()
            probe.audit.wait(request)
            proof.observe("actual_tenant_audit_INSERT")
            proof.queued(exclusive, key)
            probe.audit.release.set()
            probe.commit.wait(request)
            proof.observe("actual_outer_commit")
            proof.queued(exclusive, key)
            probe.commit.release.set()
            response = request.finish()
            assert exclusive.finish() == "exclusive N acquired"
    finally:
        probe.release_all()
    proof.released()
    record_property("full_transition_SQL", json.dumps(probe.sql, default=str))
    if kind != "service":
        assert response.status_code == (302 if kind == "native" else 200), response.content
    assert_closed_lifecycle(claim_lab, kind)
    if kind == "oidc":
        locks = [row["sql"] for row in probe.sql if "FOR UPDATE" in row["sql"]]
        member_index = next(i for i, sql in enumerate(locks) if 'FROM "makerspaces_makerspacemembership"' in sql)
        user_index = next(i for i, sql in enumerate(locks) if 'FROM "accounts_user"' in sql)
        assert member_index < user_index
    hooks = [row["sql"] for row in probe.sql if 'FROM "accounts_memberclaimcode"' in row["sql"]
             and 'JOIN "makerspaces_makerspacemembership"' in row["sql"] and "FOR UPDATE" in row["sql"]]
    assert hooks and all('FOR UPDATE OF "accounts_memberclaimcode"' in sql for sql in hooks)


@pytest.mark.parametrize("kind", ["native", "oidc"])
@pytest.mark.parametrize("membership_status", ["active", "revoked"])
def test_one_quiesced_membership_of_any_status_refuses_entire_transition(
    claim_lab, kind, membership_status, monkeypatch,
):
    call = prepare(claim_lab, kind, monkeypatch)
    row = claim_lab.memberships[1]
    type(row).objects.filter(pk=row.pk).update(status=membership_status)
    frozen(claim_lab.spaces[1], claim_lab.actor)
    before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc")
    response = call()
    assert_retry(response, kind, oidc_status=423)
    if kind == "oidc":
        assert response.json()["code"] == "tenant_migration_quiesced"
        assert OidcBrowserAttempt.objects.get().consumed_at is not None
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc") == audits


@pytest.mark.parametrize("kind", ["native", "oidc", "service"])
def test_real_audit_insert_failure_rolls_back_complete_transition_under_retained_ns(
    claim_lab, kind, monkeypatch, record_property,
):
    call = prepare(claim_lab, kind, monkeypatch)
    proof = NProof([space.pk for space in claim_lab.spaces], record_property)
    before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc")
    injected = []

    def fail_insert(execute, sql, params, many, context):
        if sql.startswith('INSERT INTO "audit_auditlog"') and "presence.ended_claim_revoked" in (params or ()):
            proof.observe("failed_actual_tenant_audit_INSERT")
            proof.queued(exclusive, claim_lab.spaces[0].pk)
            injected.append((sql, tuple(params)))
            raise IntegrityError("injected canonical AuditLog INSERT failure")
        return execute(sql, params, many, context)

    def failing_call():
        with connection.execute_wrapper(fail_insert):
            return call()

    with workers() as start:
        request = start(failing_call, pause=lambda statement: row_lock(statement.sql))
        request.paused()
        proof.observe("before_failed_audit_with_row_lock_held")
        key = claim_lab.spaces[0].pk
        exclusive = start(lambda: exclusive_n(key))
        proof.queued(exclusive, key)
        if kind == "oidc":
            assert_retry(request.finish(), kind)
        else:
            with pytest.raises(IntegrityError, match="canonical AuditLog INSERT"):
                request.finish()
        assert exclusive.finish() == "exclusive N acquired"
        record_property("failed_audit_full_SQL", json.dumps([vars(s) for s in request.statements], default=str))
    assert len(injected) == 1
    proof.released()
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc") == audits
