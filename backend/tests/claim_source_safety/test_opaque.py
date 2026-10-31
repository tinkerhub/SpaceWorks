"""Opaque restore state is a real persisted gate input, never a mocked exception."""
import pytest

from .callers import assert_retry, prepare
from .opaque import opaque
from .state import domain, tenant_and_transition_audits

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["native", "oidc"])
def test_opaque_other_owned_tenant_refuses_without_any_domain_mutation(
    claim_lab, kind, monkeypatch,
):
    call = prepare(claim_lab, kind, monkeypatch)
    opaque(claim_lab.spaces[1])
    before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc")
    response = call()
    assert_retry(response, kind, oidc_status=503)
    if kind == "oidc":
        assert response.json()["code"] == "tenant_not_restored"
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc") == audits
