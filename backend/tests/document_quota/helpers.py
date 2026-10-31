"""Real API charges and explicit adversarial fixtures; provider transport only."""
from hashlib import sha256

from django.db import connection
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.makerspaces.purge_intent import storage_origins
from tests.document_safety.helpers import accepted_body, finalize, presign

RELEASE = "storage.document_quota_released"
KINDS = ["receipt", "asset", "machine"]


def added_action(case):
    return "procurement.receipt_added" if case.prefix.startswith("procurement:") else "warranty.document_added"


def upload(case, *, variant=False, boundary=None):
    key, _ = presign(case)
    body = accepted_body("application/pdf", variant=variant)
    case.store.seed(case.module.staging_key(key), body)
    if boundary is not None:
        case.store.boundary = boundary
    response = finalize(case, key)
    assert response.status_code == 201, response.data
    row = case.model.objects.get(pk=response.data["id"])
    event = AuditLog.objects.get(
        makerspace=case.home, action=added_action(case),
        target_type=row._meta.label_lower, target_id=str(row.pk),
    )
    return row, event, body


def delete(case, row):
    return case.client.delete(reverse(f"{case.prefix}-detail", kwargs={"pk": row.pk}))


def releases(case):
    return AuditLog.objects.filter(makerspace=case.home, action=RELEASE)


def expected_meta(case, row, size):
    identity = DeploymentDatabaseIdentity.objects.get(pk=1)
    return {
        "version": 1, "bytes": size,
        "accounting_database_id": str(identity.database_uuid),
        "storage_origin": storage_origins()["private"],
        "object_key_sha256": sha256(row.object_key.encode()).hexdigest(),
        "row_created_at": row.created_at.isoformat(),
    }


def clear_identity():
    # Fixture-only equivalent of transaction-test flush, never an app write.
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE TABLE backup_deploymentdatabaseidentity")


def legacy_row(case, *, key=None):
    if key is None:
        key, _ = presign(case)
    fields = {"to_buy_item": case.target} if case.prefix.startswith("procurement:") else {
        "warranty": case.target, "original_filename": "legacy.pdf",
        "content_type": "application/pdf", "size_bytes": 99999,
    }
    return case.model.objects.create(object_key=key, uploaded_by=case.actor, **fields)
