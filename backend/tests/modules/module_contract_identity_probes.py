"""Anonymous identity probes keep the API's generic, non-enumerating error bodies."""

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.accounts.models import PlatformLoginMethods, User
from apps.accounts.models_devices import (
    DeviceAttestationChallenge,
    DeviceGrant,
    DeviceRefreshFamily,
    DeviceRefreshToken,
    NativeAppRegistration,
)
from apps.accounts.models_phone import PhoneVerificationChallenge
from apps.accounts.services_phone import GENERIC_START_ACK
from apps.accounts.services_device_tokens import token_fingerprint
from apps.accounts.tokens import SpaceWorksAccessToken, SpaceWorksRefreshToken
from apps.audit.models import AuditLog
from apps.makerspaces.servability import servable_queryset
from tests.accounts.test_device_auth import attested_login


# These public auth contracts intentionally contain no raw module key.
AUTH_DENIALS = {
    "member_accounts": (
        404, {"detail": "Phone sign-in is not available on this deployment."}
    ),
    "mobile": (401, {"detail": "Mobile device sessions are not enabled."}),
}


def member_accounts(space, client, *, monkeypatch):
    assert list(servable_queryset().values_list("pk", flat=True)) == [space.pk]
    methods = PlatformLoginMethods.load()
    methods.phone_enabled = True
    methods.save()
    assert PlatformLoginMethods.load().phone_enabled is True
    phone = "+14155552671"
    calls = []
    # This is a view/module-gate probe only: OTP generation, account lookup and SMS
    # delivery are downstream of this service boundary and are not claimed here.
    monkeypatch.setattr("apps.accounts.views_phone.start_login", calls.append)
    users_before = User.objects.count()
    challenges_before = PhoneVerificationChallenge.objects.count()

    response = APIClient().post(
        "/api/v1/auth/phone/login/start", {"phone": phone}, format="json"
    )

    if "member_accounts" in space.enabled_modules:
        assert response.status_code == 200
        assert response.data == {"detail": GENERIC_START_ACK}
        assert calls == [phone]
    else:
        status, body = AUTH_DENIALS["member_accounts"]
        assert response.status_code == status
        assert response.data == body
        assert calls == []
    assert User.objects.count() == users_before
    assert PhoneVerificationChallenge.objects.count() == challenges_before
    return response


def mobile(space, client, *, settings, monkeypatch):
    assert list(servable_queryset().values_list("pk", flat=True)) == [space.pk]
    # Matrix OFF retains this declared dependency and removes only mobile.
    assert "member_accounts" in space.enabled_modules
    methods = PlatformLoginMethods.load()
    methods.password_enabled = True
    methods.save()
    assert PlatformLoginMethods.load().password_enabled is True
    settings.DEVICE_ATTESTATION_CHALLENGE_TTL_SECONDS = 300
    user = User.objects.create_user(
        username=f"{space.slug}-member",
        email="native-contract@example.test",
        password="strong-device-password",
        role=User.Role.REQUESTER,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
        email_verified_at=timezone.now(),
    )
    assert user.is_active and user.access_status == User.AccessStatus.ACTIVE
    assert not user.is_staff and not user.is_superuser and not user.is_walk_in
    assert user.has_usable_password() and user.email_verified_at is not None
    assert not DeviceGrant.objects.exists()
    assert not DeviceRefreshFamily.objects.exists()
    assert not DeviceRefreshToken.objects.exists()
    assert not OutstandingToken.objects.exists()

    # Existing helper creates the real registration/challenge and mocks only the
    # Apple attestation provider HTTP response, never auth, module or token services.
    response, _ = attested_login(APIClient(), user, settings, monkeypatch)

    registration = NativeAppRegistration.objects.get(
        app_id="org.spaceworks.app", platform="apple", environment="development"
    )
    assert registration.status == NativeAppRegistration.Status.APPROVED
    challenge = DeviceAttestationChallenge.objects.get(registration=registration)
    assert challenge.consumed_at is not None
    if "mobile" in space.enabled_modules:
        assert response.status_code == 200
        assert set(response.data) == {"access", "refresh", "user", "device_grant"}
        assert response.data["access"] and response.data["refresh"]
        assert response.data["user"]["id"] == user.pk
        assert DeviceGrant.objects.count() == 1
        assert DeviceRefreshFamily.objects.count() == 1
        assert DeviceRefreshToken.objects.count() == 1
        assert OutstandingToken.objects.count() == 1
        grant = DeviceGrant.objects.get(user=user)
        assert str(grant.pk) == str(response.data["device_grant"]["id"])
        assert grant.registration_id == registration.pk
        assert grant.status == DeviceGrant.Status.ACTIVE
        family = DeviceRefreshFamily.objects.get(grant=grant, user=user)
        token = DeviceRefreshToken.objects.get(family=family)
        # Project token constructors validate signature, expiry, type and generation.
        access = SpaceWorksAccessToken(response.data["access"])
        refresh = SpaceWorksRefreshToken(response.data["refresh"])
        for claims in (access, refresh):
            assert str(claims["user_id"]) == str(user.pk)
            assert claims["device_grant_id"] == str(grant.pk)
            assert claims["device_family_id"] == str(family.pk)
        assert refresh["jti"] == token.jti
        assert token.token_fingerprint == token_fingerprint(response.data["refresh"])
        assert OutstandingToken.objects.filter(user=user, jti=token.jti).exists()
        assert AuditLog.objects.filter(
            actor=user, action="auth.device_login_succeeded"
        ).count() == 1
        assert AuditLog.objects.filter(action="auth.device_login_succeeded").count() == 1
        audit = AuditLog.objects.get(action="auth.device_login_succeeded")
        assert (audit.target_type, audit.target_id) == ("accounts.user", str(user.pk))
    else:
        status, body = AUTH_DENIALS["mobile"]
        assert response.status_code == status
        assert response.data == body
        assert not DeviceGrant.objects.exists()
        assert not DeviceRefreshFamily.objects.exists()
        assert not DeviceRefreshToken.objects.exists()
        assert not OutstandingToken.objects.exists()
        assert not AuditLog.objects.filter(action="auth.device_login_succeeded").exists()
    return response
