"""Shared P excludes a real exclusive P over auth writes and all delegated dispatch."""
import pytest

from apps.accounts.claim_route_types import Refused
from apps.accounts.claim_routes import policy_for
from apps.accounts.models_devices import DeviceGrant
from apps.audit.models import AuditLog
from apps.presence.models import PresenceSession
from tests.qr_source_safety.state_helpers import plain, state

from .assertions import all_rows, dml, domain_without_audits, no_gate_or_dml
from .auth_setup import AUTH_MODELS, claim_session, native_session
from .cases import ROUTES, prepared
from .p_protocol import full_dispatch, refused_dispatch

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("route", ROUTES)
def test_actual_native_last_used_update_and_qr_audit_stay_under_same_p(
    closure_lab, settings, route, record_property,
):
    session = native_session(closure_lab)
    case = prepared(closure_lab, route, session.client)
    before = all_rows(*AUTH_MODELS)
    grant_before = DeviceGrant.objects.values().get(pk=session.grant.pk)
    audits_before = all_rows(AuditLog)["audit.auditlog"]
    response, sql = full_dispatch(settings, case, "accounts_devicegrant", record_property)
    assert response.status_code == case.status, response.content
    after = all_rows(*AUTH_MODELS)
    grant_after = DeviceGrant.objects.values().get(pk=session.grant.pk)
    assert grant_after["last_used_at"] > grant_before["last_used_at"]
    assert grant_after == {**grant_before, "last_used_at": grant_after["last_used_at"]}
    assert after == {**before, "accounts.devicegrant": [plain(grant_after)]}
    audits_after = all_rows(AuditLog)["audit.auditlog"]
    assert audits_after[:len(audits_before)] == audits_before
    assert len(audits_after) == len(audits_before) + 1
    event = audits_after[-1]
    expected = {"qr-boxes": "qr.box_created", "qr-tools": "qr.tool_created",
                "qr-scan": "qr.scanned", "qr-resolve": "qr.scanned",
                "qr-revoke": "qr.revoked", "qr-rebind-target": "qr.rebound",
                "asset-generate": "asset_units.generated", "asset-qr": "qr.created"}[route]
    assert (event["action"], event["actor_id"], event["makerspace_id"]) == (
        expected, closure_lab.actor.pk, closure_lab.home.pk,
    )
    updates = [row for row in sql if row["sql"].startswith('UPDATE "accounts_devicegrant"')]
    assert len(updates) == 1


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("invalid", ["revoked", "expired-row"])
def test_legacy_fault_invalid_claim_cleanup_updates_presence_and_audit_under_p_and_owner_n(
    closure_lab, settings, route, invalid, record_property,
):
    assert isinstance(policy_for(route, "POST"), Refused)
    session = claim_session(closure_lab, invalid)
    case = prepared(closure_lab, route, session.client)
    domain_before = domain_without_audits()
    auth_before = all_rows(*AUTH_MODELS)
    audits_before = all_rows(AuditLog)["audit.auditlog"]
    response, sql = full_dispatch(settings, case, "presence_presencesession",
                                  record_property, cleanup=True,
                                  cleanup_makerspace_id=closure_lab.home.pk)
    assert response.status_code == 401
    assert response.json()["detail"] == "Claim session is no longer active."
    assert domain_without_audits() == domain_before
    presence = PresenceSession.objects.values().get(pk=session.presence.pk)
    old = auth_before["presence.presencesession"][0]
    assert presence["ended_at"] is not None
    assert presence == {**old, "ended_at": presence["ended_at"], "ended_by_id": None,
                        "end_reason": PresenceSession.EndReason.CLAIM_REVOKED}
    assert all_rows(*AUTH_MODELS) == {**auth_before, "presence.presencesession": [plain(presence)]}
    audits_after = all_rows(AuditLog)["audit.auditlog"]
    assert audits_after[:len(audits_before)] == audits_before
    assert len(audits_after) == len(audits_before) + 1
    event = audits_after[-1]
    assert (event["action"], event["actor_id"], event["makerspace_id"],
            event["target_type"], event["target_id"], event["meta"]) == (
        "presence.ended_claim_revoked", None, closure_lab.home.pk,
        "presence.presencesession", str(session.presence.pk),
        {"claim_session_id": str(session.claim.session_id)},
    )
    assert any('"tenant_migration_sourcemigrationgate"' in row["sql"] for row in sql)
    assert all('"presence_presencesession"' in row["sql"] or '"audit_auditlog"' in row["sql"]
               for row in sql if dml(row["sql"]))


@pytest.mark.parametrize("route", ROUTES)
def test_valid_claim_policy_still_refuses_403_without_presence_cleanup_under_p(
    closure_lab, settings, route, record_property,
):
    policy = policy_for(route, "POST")
    assert isinstance(policy, Refused)
    session = claim_session(closure_lab)
    case = prepared(closure_lab, route, session.client)
    before, auth_before = state(), all_rows(*AUTH_MODELS)
    response, sql = refused_dispatch(settings, case, record_property)
    assert response.status_code == 403
    assert response.json()["detail"] == policy.reason
    no_gate_or_dml(sql)
    assert state() == before and all_rows(*AUTH_MODELS) == auth_before
