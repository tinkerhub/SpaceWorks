"""Persisted protocol fixtures; real signed JWT, grant, family and selection checks."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.claim_sessions import attach_claim_context, validated_claim_session
from apps.accounts.claim_tokens import ClaimAccessToken, mint_claim_tokens
from apps.accounts.models_claim import MemberClaimCode
from apps.accounts.models_devices import DeviceGrant, DeviceRefreshFamily, NativeAppRegistration
from apps.accounts.services_device_tokens import issue_device_token_pair
from apps.accounts.tokens import SpaceWorksAccessToken
from apps.presence.models import PresenceSession
from apps.presence.services import start_session
from apps.tenant_migration.models_source_gate import SourceMigrationGate
from tests.qr_target_safety_helpers import staff


def native_session(lab):
    """Mirror persisted attestation fixtures; no provider or auth guard is mocked.

    The real issuer creates the refresh family and token row. Like the frozen
    staff JWT helper, this trusted test issuer explicitly selects staff_api.
    """
    registration = NativeAppRegistration.objects.create(
        makerspace=lab.home, app_id=f"test.qr.http.{uuid4().hex}", platform="android",
        environment="production", verifier_config_key="fixture",
        status=NativeAppRegistration.Status.APPROVED,
    )
    now = timezone.now()
    grant = DeviceGrant.objects.create(
        registration=registration, user=lab.actor, platform=registration.platform,
        app_id=registration.app_id, signing_identity="fixture-signing-identity",
        environment=registration.environment, attestation_subject_fingerprint="a" * 64,
        attested_at=now, last_used_at=now - timedelta(days=1),
    )
    access, _, family = issue_device_token_pair(lab.actor, grant)
    token = SpaceWorksAccessToken(access)
    token["surface"] = "staff_api"
    client = APIClient(HTTP_HOST="testserver", HTTP_X_MAKERSPACE_ID=str(lab.home.pk))
    session = SimpleNamespace(client=client, token=token, grant=grant,
                              family=family, registration=registration)
    authenticate(session)
    return session


def authenticate(session):
    session.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session.token}")


def claim_session(lab, invalid=None):
    """Legacy/fault fixture: raw invalidation leaves otherwise unreachable live presence.

    Normal canonical revocation ends claim presence atomically; these two direct
    updates intentionally model old or inconsistent rows for defensive cleanup.
    """
    member = staff(lab.home, "member")
    member.is_walk_in = True
    member.set_unusable_password()
    member.save(update_fields=["is_walk_in", "password"])
    membership = member.makerspace_memberships.get(makerspace=lab.home)
    now = timezone.now()
    claim = MemberClaimCode.objects.create(
        membership=membership, code_digest=uuid4().hex + uuid4().hex, issued_by=lab.actor,
        expires_at=now + timedelta(minutes=10), consumed_at=now,
        absolute_expires_at=now + timedelta(hours=1), consumed_ip="203.0.113.70",
    )
    pair = mint_claim_tokens(claim)
    # Prove the signed token and its DB provenance are valid BEFORE invalidation.
    validated = validated_claim_session(ClaimAccessToken(pair.access))
    presence = start_session(attach_claim_context(member, validated), lab.home, 60)
    assert presence.created_via_claim_session_id == claim.pk
    if invalid == "revoked":
        MemberClaimCode.objects.filter(pk=claim.pk).update(revoked_at=timezone.now())
    elif invalid == "expired-row":
        # Signed access remains unexpired; the authoritative session deadline changed.
        MemberClaimCode.objects.filter(pk=claim.pk).update(
            absolute_expires_at=now - timedelta(seconds=1),
        )
    elif invalid is not None:
        raise AssertionError(invalid)
    client = APIClient(HTTP_HOST="testserver")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {pair.access}")
    return SimpleNamespace(client=client, claim=claim, presence=presence, member=member)


def freeze(lab):
    now = timezone.now()
    return SourceMigrationGate.objects.create(
        makerspace=lab.home, actor=lab.root, state=SourceMigrationGate.State.QUIESCED,
        owner_id=uuid4(), fencing_token=1, heartbeat_at=now,
        lease_expires_at=now + timedelta(hours=1), presign_drain_until=now, quiesced_at=now,
    )


AUTH_MODELS = (DeviceGrant, DeviceRefreshFamily, NativeAppRegistration, MemberClaimCode, PresenceSession)
