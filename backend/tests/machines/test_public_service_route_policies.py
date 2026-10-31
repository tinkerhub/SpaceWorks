"""Public client/claim policies admit only the correct scope and resolved tenant."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.test import RequestFactory
from django.urls import resolve, reverse

from apps.accounts.claim_route_types import Allowed, AnonymousRead, SLUG
from apps.accounts.claim_routes import policy_for
from apps.apiclients.scope_registry import classify, lookup, resolve_target
from apps.machines.models import Machine, MachineServiceRequest, MachineType
from tests.accounts.claim_helpers_p7 import redeemed_claim, start_claim_presence
from tests.machines.public_service_helpers import endpoint, object_io, post_request, service_lab
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db(transaction=True)


def request_for(path, method="GET", body=None):
    request = getattr(RequestFactory(), method.lower())(path, data=body or {}, content_type="application/json")
    request.resolver_match = resolve(path)
    return request


@pytest.mark.parametrize("action,method,scope", [("types", "GET", "public:read"), ("upload", "POST", "public:write"), ("status", "GET", "public:read")])
def test_new_routes_are_public_scoped_tenant_isolated_and_excluded_from_legacy(service_lab, action, method, scope):
    space = service_lab[0]
    post_request(service_lab)
    row = MachineServiceRequest.objects.get()
    path = reverse("public-machine-service-status", args=[row.public_token]) if action == "status" else endpoint(space, action)
    request = request_for(path, method)
    entry = lookup(request.resolver_match.view_name, method)
    assert not entry.legacy_v1 and resolve_target(request, entry) == (space, True)
    other = make_space("route-policy-other")
    for scopes, tenant, verdict in [([scope], space.pk, True), (["public:*"], space.pk, True),
                                   ([scope], other.pk, False), (["legacy:v1"], space.pk, False),
                                   (["admin:*"], space.pk, False),
                                   (["public:write" if method == "GET" else "public:read"], space.pk, False)]:
        assert classify(request, SimpleNamespace(scopes=scopes, makerspace_id=tenant)).verdict is verdict
    if action == "status":
        missing = request_for(reverse("public-machine-service-status", args=[uuid4()]))
        assert resolve_target(missing, entry) == (None, False)
    policy = policy_for(request.resolver_match.view_name, method)
    if action == "upload":
        assert isinstance(policy, Allowed) and policy.tenant == SLUG and policy.audited
    else:
        assert isinstance(policy, AnonymousRead)


def test_submission_target_is_slug_and_foreign_machine_body_cannot_change_it(service_lab):
    space, _, _, generic, _ = service_lab
    foreign = make_space("forged-machine-target")
    request = request_for(endpoint(space), "POST", {"machine_id": 999999})
    entry = lookup(request.resolver_match.view_name, "POST")
    assert resolve_target(request, entry) == (space, True)
    assert classify(request, SimpleNamespace(scopes=["public:write"], makerspace_id=foreign.pk)).verdict is False
    policy = policy_for(request.resolver_match.view_name, "POST")
    assert isinstance(policy, Allowed) and policy.tenant == SLUG and policy.audited


@pytest.mark.parametrize("action", ["submit", "upload"])
def test_redeemed_claim_cannot_use_a_foreign_slug_or_select_a_foreign_type(service_lab, object_io, action):
    harness = redeemed_claim(f"typed-{action}")
    start_claim_presence(harness)
    own_type = MachineType.objects.create(makerspace=harness.space, slug="router", name="Router")
    Machine.objects.create(makerspace=harness.space, machine_type=own_type, name="Own", is_public=True)
    foreign, _, _, foreign_type, _ = service_lab
    fields = {"title": "Claim project"} if action == "submit" else {"filename": "project.pdf", "content_type": "application/pdf", "kind": "attachment"}
    for target, kind, expected in [(foreign, foreign_type, 403), (harness.space, foreign_type, 404)]:
        response = harness.claim_client.post(endpoint(target, action), {"machine_type_id": kind.pk, **fields}, format="json")
        assert response.status_code == expected, response.data
    own = harness.claim_client.post(endpoint(harness.space, action), {"machine_type_id": own_type.pk, **fields}, format="json")
    assert own.status_code == 201, own.data
