"""Authenticated native grants and current signed-client wire requests."""
import hashlib
import hmac
import json
import time
import uuid

from cryptography.fernet import Fernet
from django.utils import timezone

from apps.accounts.models_devices import DeviceGrant, DeviceRefreshFamily, NativeAppRegistration
from apps.apiclients.models import ApiClient
from tests.evidence.safety_access_helpers import jwt_client


def native_client(lab):
    registration = NativeAppRegistration.objects.create(
        makerspace=lab.home, app_id="test.evidence.safety", platform="android",
        environment="production", verifier_config_key="fixture",
        status=NativeAppRegistration.Status.APPROVED,
    )
    grant = DeviceGrant.objects.create(
        registration=registration, user=lab.user, platform="android",
        app_id=registration.app_id, signing_identity="fixture-signing-identity",
        environment="production", attestation_subject_fingerprint="a" * 64,
        attested_at=timezone.now(), last_used_at=timezone.now(),
    )
    family = DeviceRefreshFamily.objects.create(grant=grant, user=lab.user)
    client = jwt_client(lab.user, device_grant_id=str(grant.pk), device_family_id=str(family.pk))
    return client, grant


def server_client(lab, settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")
    return ApiClient.issue(
        label="evidence-safety-server", makerspace=lab.home,
        scopes=["public:read"], client_type="server",
        allowed_origins=[f"https://{lab.home.frontend_domain}"],
    )


def signed_request(client, credential, method, path, body=None):
    """Use the nonce-bearing protocol over the exact bytes passed to Django."""
    app, secret = credential
    timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
    raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
    message = b"\n".join([method.encode(), path.encode(), timestamp.encode(), nonce.encode(), raw])
    headers = {
        "HTTP_X_CLIENT_ID": app.client_id, "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_NONCE": nonce,
        "HTTP_X_SIGNATURE": hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
    }
    return client.generic(method, path, raw, content_type="application/json", **headers)
