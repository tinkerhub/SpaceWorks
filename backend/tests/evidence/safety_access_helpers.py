"""Real authentication, finite PUT accounting and observable S3 transport for S03/05/06."""
from types import SimpleNamespace

from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.evidence import storage, views
from apps.evidence.finalization import charge_storage_once, finalize_upload
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.evidence.storage import (
    object_exists as original_object_exists,
    validate_evidence_object as original_validator,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles
from tests.atomic_publication.store import Store, png


class EvidenceStore(Store):
    """Only provider transport is replaced; HEAD, decoding and promotion remain real."""

    def copy_object(self, **kwargs):
        self._call("copy", kwargs)
        data, mime, _ = self.objects[kwargs["CopySource"]["Key"]]
        return {"VersionId": self.seed(kwargs["Key"], data, mime)}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self._call("presign", dict(operation=operation, **Params, ttl=ExpiresIn))
        return "https://objects.example.test/signed"


def space(slug):
    return Makerspace.objects.create(
        name=slug, slug=slug, frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
        resource_limit_overrides={"storage": 64 * len(png())},
    )


def actor(username="safety-inventory"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.test",
        role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE,
    )


def assign_inventory(user, makerspace):
    ensure_default_roles(makerspace)
    role = MakerspaceRole.objects.get(makerspace=makerspace, slug="inventory_manager")
    return MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user, role="inventory_manager", assigned_role=role,
    )


def jwt_client(user, **claims):
    refresh = SpaceWorksRefreshToken.for_user(user)
    refresh["surface"] = "staff_api"
    for key, value in claims.items():
        refresh[key] = value
    client = APIClient(HTTP_HOST="testserver")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def safety_lab(monkeypatch, settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    settings.PLATFORM_STAFF_ORIGINS = []
    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
    settings.STORAGE_PRESIGN_METHOD = "put"
    settings.EVIDENCE_MAX_BYTES = 1024 * 1024
    # Unconditional migration infrastructure; transactional flushes may remove it.
    identity, _ = DeploymentDatabaseIdentity.objects.get_or_create(pk=1)
    store = EvidenceStore()
    monkeypatch.setattr(storage, "_client", lambda: store)
    monkeypatch.setattr(storage, "_public_client", lambda: store)
    # Capture originals at collection, before conftest installs its legacy fake.
    monkeypatch.setattr(storage, "validate_evidence_object", original_validator)
    monkeypatch.setattr(storage, "object_exists", original_object_exists)
    monkeypatch.setattr(views, "object_exists", original_object_exists)
    home, other = space("safety-a"), space("safety-b")
    user = actor()
    memberships = [assign_inventory(user, item) for item in (home, other)]
    return SimpleNamespace(
        home=home, other=other, user=user, memberships=memberships, store=store,
        client=jwt_client(user), identity=identity,
    )


def origin(makerspace):
    return {"HTTP_ORIGIN": f"https://{makerspace.frontend_domain}"}


def upload_url(makerspace):
    pk = getattr(makerspace, "pk", makerspace)
    return reverse("evidence_admin:evidence-upload-url", kwargs={"makerspace_id": pk})


def detail_url(photo):
    pk = getattr(photo, "pk", photo)
    return reverse("evidence_admin:evidence-detail", kwargs={"pk": pk})


def upload(lab, makerspace=None, *, body=None, headers=None, client=None):
    return (client or lab.client).post(
        upload_url(makerspace or lab.home),
        body if body is not None else {"evidence_type": "issue", "content_type": "image/png"},
        format="json", **(headers or {}),
    )


def photo(lab, *, makerspace=None, declared=999_999):
    makerspace = makerspace or lab.home
    return EvidencePhoto.objects.create(
        makerspace=makerspace, uploaded_by=lab.user, evidence_type="issue",
        object_key=storage.evidence_object_key(makerspace.pk, "issue"),
        content_type="image/png", size_bytes=declared,
    )


def charged_photo(lab, *, makerspace=None):
    evidence = photo(lab, makerspace=makerspace)
    evidence.makerspace.refresh_from_db()
    baseline = evidence.makerspace.storage_bytes_used
    lab.store.seed(storage.staging_key(evidence.object_key), png(), "image/png")
    result = finalize_upload(evidence, 1024 * 1024)
    assert (result.size, result.content_type) == (len(png()), "image/png")
    charge_storage_once(evidence, result.size)
    charge_storage_once(evidence, result.size)
    evidence.makerspace.refresh_from_db()
    assert evidence.makerspace.storage_bytes_used == baseline + len(png())
    state = EvidenceUploadFinalization.objects.get(evidence=evidence)
    assert (state.status, state.size_bytes, state.quota_charged) == (
        "finalized", len(png()), True,
    )
    markers = AuditLog.objects.filter(action="evidence.storage_charged", target_id=str(evidence.pk))
    assert markers.count() == 1
    assert markers.get().meta == {
        "version": 1, "bytes": len(png()), "journal_version": state.updated_at.isoformat(),
        "accounting_database_id": str(lab.identity.database_uuid),
    }
    read_keys = {args["Key"] for name, args in lab.store.calls if name == "get"}
    assert {evidence.object_key, storage.staging_key(evidence.object_key)} <= read_keys
    assert any(name == "copy" for name, _ in lab.store.calls)
    assert lab.store.objects[evidence.object_key][:2] == (png(), "image/png")
    assert storage.staging_key(evidence.object_key) not in lab.store.objects
    return evidence, state, markers.get()


def snapshot():
    return {
        model._meta.label: list(model.objects.order_by(model._meta.pk.name).values())
        for model in (EvidencePhoto, EvidenceUploadFinalization, AuditLog)
    } | {"storage": list(Makerspace.objects.order_by("pk").values_list("pk", "storage_bytes_used"))}


def assert_no_effects(lab, before, calls):
    assert snapshot() == before
    assert lab.store.calls == calls


def assert_presign(lab, evidence):
    calls = [args for name, args in lab.store.calls if name == "presign"]
    assert calls[-1] == {
        "operation": "put_object", "Bucket": views.settings.AWS_STORAGE_BUCKET_NAME,
        "Key": storage.staging_key(evidence.object_key), "ContentType": "image/png",
        "ttl": views.settings.EVIDENCE_URL_TTL_SECONDS,
    }
