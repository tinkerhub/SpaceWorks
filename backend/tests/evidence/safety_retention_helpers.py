"""Stage 3 evidence fixtures: real PNG validation, journals, policy and quota."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.backup.models import DeploymentRecoveryState
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.evidence import finalization, storage
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace
from tests.atomic_publication.store import error, png
from tests.inventory_lending_evidence_helpers import EvidenceStore, uploaded_images
from tests.return_helpers import make_member, make_space


class RetentionStore(EvidenceStore):
    """Transport double retaining delete markers as well as ordinary versions."""

    def __init__(self):
        super().__init__()
        self.markers = {}

    def list_object_versions(self, **kwargs):
        page = super().list_object_versions(**kwargs)
        page["DeleteMarkers"] = [
            {"Key": key, "VersionId": version}
            for key, versions in self.markers.items()
            if key.startswith(kwargs["Prefix"]) for version in versions
        ]
        return page

    def delete_objects(self, **kwargs):
        result = super().delete_objects(**kwargs)
        for item in kwargs["Delete"]["Objects"]:
            self.markers.get(item["Key"], set()).discard(item["VersionId"])
        return result


def safety_lab(monkeypatch, settings, *, seed_identity=True):
    # TransactionTestCase flush removes migration seeds; production evidence code
    # must only read these rows. Provision fixtures via their existing model APIs.
    recovery = DeploymentRecoveryState.load()
    assert recovery.mode == DeploymentRecoveryState.Mode.NORMAL
    if seed_identity:
        DeploymentDatabaseIdentity.load()
    settings.PLATFORM_DOMAIN_SUFFIX = "safety.example.test"
    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    uploaded_images(monkeypatch, settings)  # restore originals hidden by conftest
    settings.STORAGE_PRESIGN_METHOD = "put"
    store = RetentionStore()
    monkeypatch.setattr(storage, "_client", lambda: store)
    space = make_space(f"safety-{uuid4().hex[:10]}")
    space.resource_limit_overrides = {"storage": len(png()) * 100}
    space.save(update_fields=["resource_limit_overrides"])
    actor = make_member(f"safety-{uuid4().hex[:10]}", space)
    client = APIClient(HTTP_HOST="testserver")
    client.force_authenticate(user=actor)
    assert not limits.is_self_host()
    assert limits.resource_limit(space, "storage") == len(png()) * 100
    return SimpleNamespace(
        space=space, actor=actor, client=client, store=store, now=timezone.now(),
    )


def photo(lab, *, days=40, declared=999999, finalized=False, charged=False,
          uploaded=True, created_at=None):
    born = created_at or lab.now - timedelta(days=days)
    # Only the INSERT clock is controlled; immutable metadata is never updated.
    with patch("django.utils.timezone.now", return_value=born):
        evidence = EvidencePhoto.objects.create(
            makerspace=lab.space, uploaded_by=lab.actor, evidence_type="issue",
            object_key=f"evidence/{lab.space.pk}/issue/{uuid4().hex}",
            content_type="image/png", size_bytes=declared,
        )
    if uploaded:
        lab.store.seed(storage.staging_key(evidence.object_key), png(), "image/png")
    if finalized or charged:
        result = finalization.finalize_upload(evidence, 1024 * 1024)
        assert result.size == len(png()) and result.content_type == "image/png"
    if charged:
        finalization.charge_storage_once(evidence, len(png()))
    return evidence


def journal(evidence):
    return EvidenceUploadFinalization.objects.get(evidence=evidence)


def markers(evidence):
    return AuditLog.objects.filter(
        makerspace=evidence.makerspace, action="evidence.storage_charged",
        target_type="evidence.evidencephoto", target_id=str(evidence.pk),
    )


def expiry_events(evidence):
    return AuditLog.objects.filter(
        makerspace=evidence.makerspace, action="evidence.object_expired",
        target_type="evidence.evidencephoto", target_id=str(evidence.pk),
    )


def usage(lab):
    return Makerspace.objects.values_list("storage_bytes_used", flat=True).get(pk=lab.space.pk)


def metadata(evidence):
    return EvidencePhoto.objects.values().get(pk=evidence.pk)


def fail_deletes(store, keys):
    """A provider failure, never a replacement for strict deletion business logic."""
    def before_delete(kwargs):
        if any(item["Key"] in keys for item in kwargs["Delete"]["Objects"]):
            raise error("AccessDenied", 403)
    store.before_delete = before_delete


def remove_identity_for_missing_infrastructure_case():
    """Model a missing migration singleton; do not replace its reader with a stub."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        DeploymentDatabaseIdentity.objects.all().delete()
    assert not DeploymentDatabaseIdentity.objects.exists()


def historical_unproved_charge(evidence, *, meta_changes=None, scope=None, target=None):
    """Explicit negative fixture: real debit, legacy flag, untrusted imported marker.

    This is deliberately NOT the producer: callers must never use it as positive
    proof of charge_storage_once. Direct INSERT permits historical JSON floats
    that today's audit writer correctly refuses to emit.
    """
    state = journal(evidence)
    assert limits.add_storage(evidence.makerspace, state.size_bytes) is True
    state.quota_charged = True
    state.save(update_fields=["quota_charged", "updated_at"])
    meta = {
        "version": 1, "bytes": state.size_bytes,
        "journal_version": state.updated_at.isoformat(),
        "accounting_database_id": str(DeploymentDatabaseIdentity.load().database_uuid),
    }
    meta.update(meta_changes or {})
    target = target or evidence
    return AuditLog.objects.create(
        action="evidence.storage_charged", makerspace=scope or evidence.makerspace,
        target_type=target._meta.label_lower, target_id=str(target.pk), meta=meta,
    )
