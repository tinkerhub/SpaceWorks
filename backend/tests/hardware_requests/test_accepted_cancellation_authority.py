"""Exact-tenant review authority, stale concrete actors, and boundary admission."""
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.apiclients.models import ApiClient
from apps.audit.models import AuditLog
from apps.hardware_requests import workflow
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from tests.evidence.safety_transport_helpers import signed_request
from tests.handout_roles import make_handout_member
from tests.test_request_workflow import (
    accept_url, accepted_requests_url, authenticated_client, history_url,
    make_hardware_request, make_space, make_user, pending_requests_url,
)
from tests.tenant_migration.source_gate_helpers import close_gate
from tests.hardware_requests.cancellation_support import (
    accepted_lab, buckets, cancel, cancel_url, refused, reviewer, snapshot,
)

pytestmark = pytest.mark.django_db


def test_reject_only_reviewer_can_cancel_and_read_only_decision_history():
    lab = accepted_lab()
    actor = reviewer(lab.space)
    client = authenticated_client(actor)
    pending = make_hardware_request(lab.space, lab.product)
    rejected = make_hardware_request(lab.space, lab.product, status="rejected")
    returned = make_hardware_request(lab.space, lab.product, status="returned")
    make_hardware_request(lab.space, lab.product, status="closed_with_issue")
    foreign = make_hardware_request(make_space("foreign-queue"), lab.product, status="rejected")
    for url, expected in [(pending_requests_url(lab.space), {pending.pk}),
                          (accepted_requests_url(lab.space), {lab.request.pk})]:
        response = client.get(url)
        assert response.status_code == 200, response.content
        assert {row["id"] for row in response.data["results"]} == expected
    before = snapshot()
    assert client.post(accept_url(pending), {}, format="json").status_code in {403, 404}
    assert client.post(f"/api/v1/admin/requests/{lab.request.pk}/issue",
                       {"evidence_id": 999999}, format="json").status_code == 403
    assert client.get(f"/api/v1/admin/makerspace/{lab.space.pk}/active-loans").status_code == 403
    assert snapshot() == before
    response = client.post(cancel_url(lab.request), {"reason": "Review decision"}, format="json")
    assert response.status_code == 200, response.content
    assert response.data["closed_by"] == {"username": actor.username, "role": actor.role}
    history = client.get(history_url(lab.space))
    assert history.status_code == 200
    assert {row["id"] for row in history.data["results"]} == {rejected.pk, lab.request.pk}
    assert returned.pk not in {row["id"] for row in history.data["results"]}
    assert foreign.pk not in {row["id"] for row in history.data["results"]}
    # ISSUE holders retain all terminal history, including the new cancellation.
    issuer = make_handout_member("cancel-issuer", lab.space)
    history = authenticated_client(issuer).get(history_url(lab.space))
    assert history.status_code == 200
    assert {row["status"] for row in history.data["results"]} == {
        "rejected", "cancelled", "returned", "closed_with_issue",
    }


def test_public_and_other_action_grants_cannot_cancel():
    lab = accepted_lab()
    clients = [APIClient(), authenticated_client(lab.request.requester),
        authenticated_client(reviewer(make_space("foreign-authority"), username="foreign-reviewer")),
        authenticated_client(make_handout_member("front-desk", lab.space)),
        authenticated_client(reviewer(lab.space, username="accept-only", actions=(rbac.Action.ACCEPT_REQUEST,)))]
    for client in clients:
        refused(lab, status=(401, 403, 404), client=client)


@pytest.mark.parametrize("demotion", ["role", "is_superuser", "is_active", "access_status",
                                     "must_change_password", "is_tenant_dump_stub",
                                     "membership", "role_grants"])
def test_stale_concrete_actor_is_rechecked_without_refreshing_the_caller(demotion):
    lab = accepted_lab()
    if demotion in {"role", "is_superuser"}:
        actor = make_user("stale-global", role="superadmin" if demotion == "role" else "requester",
                          is_superuser=demotion == "is_superuser", access_status="active")
    else:
        actor = reviewer(lab.space, username="stale-local")
    assert rbac.can(actor, rbac.Action.REJECT_REQUEST, lab.space.pk)
    # Keep this original concrete instance. In particular no SPACE_MANAGER legacy
    # fallback or remaining membership may accidentally preserve the removed grant.
    if demotion == "membership":
        MakerspaceMembership.objects.filter(user=actor).update(status="revoked")
    elif demotion == "role_grants":
        MakerspaceRole.objects.filter(memberships__user=actor).update(granted_actions=[])
    else:
        value = {"role": "requester", "is_superuser": False, "is_active": False,
                 "access_status": "restricted", "must_change_password": True,
                 "is_tenant_dump_stub": True}[demotion]
        User.objects.filter(pk=actor.pk).update(**{demotion: value})
        assert getattr(actor, demotion) != value
    before = snapshot()
    with pytest.raises(PermissionDenied):
        workflow.cancel_request(actor, lab.request, "Stale authorization must not persist")
    assert snapshot() == before
    # Force-authenticate that same stale instance: the HTTP entry point must not
    # undo the service's fresh-authority check either.
    refused(lab, status=(403, 404), client=authenticated_client(actor))


def test_forged_actor_pk_does_not_replace_original_authentication():
    lab = accepted_lab()
    before = snapshot()
    with pytest.raises(PermissionDenied):
        workflow.cancel_request(SimpleNamespace(pk=lab.actor.pk, is_authenticated=False),
                                lab.request, "Forged actor")
    assert snapshot() == before


def test_fresh_actor_preserves_claim_audit_attribution():
    lab = accepted_lab()
    lab.actor._claim_audit_context = SimpleNamespace(
        session_id="cancellation-claim-session", issued_by_id=lab.actor.pk,
        redemption_ip="203.0.113.42",
    )
    actor_reads = []

    def observe(execute, sql, params, many, context):
        if sql.startswith("SELECT ") and 'FROM "accounts_user"' in sql:
            actor_reads.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(observe):
        workflow.cancel_request(lab.actor, lab.request, "Private reason")
    assert actor_reads
    assert all(" FOR " not in sql for sql in actor_reads)
    event = AuditLog.objects.get(action="request.cancelled")
    assert event.meta["claim_session_id"] == "cancellation-claim-session"
    assert event.meta["claim_issued_by_id"] == lab.actor.pk
    assert event.meta["claim_redemption_ip"].startswith("hmac-sha256:")
    assert "203.0.113.42" not in str(event.meta)


def test_foreign_origin_cannot_cancel_even_for_a_global_superadmin(settings):
    lab = accepted_lab()
    settings.PLATFORM_STAFF_ORIGINS = []
    other = Makerspace.objects.create(name="Foreign origin", slug="cancel-origin",
        frontend_domain="cancel-origin.example.test", frontend_domain_status="verified")
    actor = make_user("origin-root", role=User.Role.SUPERADMIN, is_superuser=True,
                      access_status="active")
    refused(lab, status=403, client=authenticated_client(actor),
            HTTP_ORIGIN=f"https://{other.frontend_domain}")


def test_authoritative_cancel_route_resolves_and_obeys_source_quiescence():
    lab = accepted_lab()
    close_gate(lab.space, lab.actor)
    response = refused(lab, status=423)
    assert response.json()["code"] == "tenant_migration_quiesced"


@pytest.mark.parametrize("scopes", [["legacy:v1"], ["public:write"]])
def test_valid_hmac_does_not_grant_unknown_staff_cancel_route(settings, scopes):
    lab = accepted_lab()
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.APICLIENT_REQUIRE_NONCE = True
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/v1/admin/"]
    credential = ApiClient.issue(label="cancel-denied-client", makerspace=lab.space,
        scopes=scopes, client_type="server", allowed_origins=["http://localhost:5000"])
    before = snapshot()
    # The human has legitimate REJECT authority, so only the signed client's
    # unknown-route admission can deny this otherwise valid mutation.
    response = signed_request(lab.client, credential, "POST", cancel_url(lab.request),
                              {"reason": "Valid signature is not staff-route authority"})
    assert response.status_code == 401, response.content
    assert snapshot() == before


def test_core_review_cancellation_does_not_depend_on_optional_handover():
    lab = accepted_lab()
    lab.space.enabled_modules = [key for key in lab.space.enabled_modules if key != "guest_handover"]
    lab.space.save(update_fields=["enabled_modules"])
    assert cancel(lab).status_code == 200
    assert buckets(lab.product) == (8, 0, 0, 8)


def test_missing_core_review_module_refuses_legacy_configuration():
    lab = accepted_lab()
    # Permitted DB JSON modeling a damaged/legacy install, not an operator API
    # workaround: core cannot be uninstalled through normal module management.
    lab.space.enabled_modules = [key for key in lab.space.enabled_modules if key != "request_workflow"]
    lab.space.save(update_fields=["enabled_modules"])
    refused(lab, status=400)
