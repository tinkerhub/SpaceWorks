"""Canonical physical credentials; no authentication or permission replacement."""
from types import SimpleNamespace

import pytest
from django.contrib.admin.models import LogEntry
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import MemberClaimCode, OidcBrowserAttempt, User
from apps.accounts.models_devices import (
    DeviceGrant, DeviceRefreshFamily, DeviceRefreshToken, NativeAppRegistration,
)
from apps.accounts.models_social import SocialIdentity
from apps.accounts.services_claim import issue_claim_code
from apps.accounts.services_device_tokens import issue_device_token_pair
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.presence.models import PresenceSession
from tests.device_helpers import make_native_app_registration
from tests.qr_source_safety.http_helpers import closure_lab  # noqa: F401

PASSWORD = "Claim source boundary password 827!"
NEW_PASSWORD = "Replacement claim password 937!"
DOMAIN_MODELS = (User, MakerspaceMembership, MemberClaimCode, PresenceSession,
                 SocialIdentity, DeviceGrant, DeviceRefreshFamily, OutstandingToken,
                 DeviceRefreshToken, NativeAppRegistration, BlacklistedToken, LogEntry)


def membership(space, user):
    return MakerspaceMembership.objects.create(
        makerspace=space, user=user, role="custom",
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )


def physical_claim(actor, row):
    issued = issue_claim_code(actor=actor, makerspace_id=row.makerspace_id,
                              membership_id=row.pk)
    client = APIClient(REMOTE_ADDR="203.0.113.70", HTTP_HOST="testserver")
    response = client.post("/api/v1/auth/claim/redeem", {
        "makerspace_slug": row.makerspace.slug, "code": issued.code,
    }, format="json")
    assert response.status_code == 200, response.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    claim = MemberClaimCode.objects.get(pk=issued.claim.pk)
    response = client.post(f"/api/v1/public/{row.makerspace.slug}/presence-sessions",
                           {"duration_minutes": 60}, format="json")
    assert response.status_code == 201, response.content
    presence = PresenceSession.objects.get(created_via_claim_session=claim)
    assert presence.expires_at <= claim.absolute_expires_at
    return SimpleNamespace(claim=claim, presence=presence, client=client)


@pytest.fixture
def claim_lab(settings, request):
    from tests.accounts.oidc_browser_helpers import ORIGIN

    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.AUTH_COOKIE_SECURE = False
    actor = User.objects.create_superuser(username="claim-source-root",
        email="claim-root@example.test", password=PASSWORD)
    client = Client(HTTP_HOST="testserver")
    assert client.login(username=actor.username, password=PASSWORD)
    user = User(username="claim-source-walkin", email="claim-walkin@example.test",
                is_walk_in=True, is_active=True)
    user.set_unusable_password()
    user.save()
    lower_space = Makerspace.objects.create(name="Earlier claim scope", slug="source-earlier")
    spaces, memberships, credentials = [], [], []
    for suffix in ("first", "second")[:getattr(request, "param", 2)]:
        space = Makerspace.objects.create(name=f"Claim {suffix}", slug=f"source-{suffix}")
        space.enabled_modules = [key for key in space.enabled_modules if key != "member_accounts"]
        space.save(update_fields=["enabled_modules", "updated_at"])
        row = membership(space, user)
        spaces.append(space)
        memberships.append(row)
        credentials.append(physical_claim(actor, row))
    # These rows deliberately have no claim FK: transition must leave them active.
    now = timezone.now()
    unrelated = PresenceSession.objects.create(member=user, makerspace=spaces[0],
        membership=memberships[0], started_at=now,
        expires_at=credentials[0].presence.expires_at)
    old_refresh = SpaceWorksRefreshToken.for_user(user)
    registration = make_native_app_registration(app_id="test.claim.source", makerspace=spaces[0])
    grant = DeviceGrant.objects.create(registration=registration, user=user,
        platform=registration.platform, app_id=registration.app_id,
        signing_identity="claim-source-fixture", environment=registration.environment,
        attestation_subject_fingerprint="a" * 64, attested_at=now, last_used_at=now)
    _, _, family = issue_device_token_pair(user, grant)
    return SimpleNamespace(actor=actor, native=client, user=user, spaces=spaces,
        memberships=memberships, credentials=credentials, unrelated=unrelated,
        grant=grant, family=family, old_refresh=str(old_refresh),
        lower_space=lower_space,
        old_token_ids=set(OutstandingToken.objects.filter(user=user).values_list("pk", flat=True)))
