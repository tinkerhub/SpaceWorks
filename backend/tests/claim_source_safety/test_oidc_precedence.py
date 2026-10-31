"""Pure identity refusals retain precedence over unrelated source state."""
import pytest

from apps.accounts.models_social import SocialIdentity
from tests.qr_http_ownership_safety.assertions import statements

from .callers import assert_retry, oidc_call
from .state import domain, frozen, tenant_and_transition_audits

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("invalid,code", [
    ("unverified", "identity_conflict"), ("wrong-email", "identity_conflict"),
    ("foreign-subject", "identity_conflict"), ("current-provider", "provider_already_linked"),
    ("autolink-off", "account_link_required"),
])
def test_invalid_full_identity_preflight_precedes_foreign_frozen_n(
    claim_lab, invalid, code, monkeypatch,
):
    overrides = {"unverified": {"email_verified": False},
                 "wrong-email": {"email": "wrong@example.test"},
                 "autolink-off": {"allow_auto_link": False}}.get(invalid, {})
    prepared = oidc_call(claim_lab, monkeypatch, claims=overrides)
    if invalid == "foreign-subject":
        SocialIdentity.objects.create(user=claim_lab.actor,
            provider=prepared.provider.provider_key, provider_sub=prepared.claims["sub"])
    elif invalid == "current-provider":
        SocialIdentity.objects.create(user=claim_lab.user,
            provider=prepared.provider.provider_key, provider_sub="other-subject")
    frozen(claim_lab.spaces[1], claim_lab.actor)
    before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=True)
    with statements() as sql:
        response = prepared.call()
    assert_retry(response, "oidc")
    assert response.json()["code"] == code
    assert "refresh_token" not in response.cookies
    assert not [row for row in sql if '"tenant_migration_sourcemigrationgate"' in row["sql"]]
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=True) == audits
