"""EVID-S06: the HTTP IntegerField is bounded dynamically before presigning."""
import pytest

from apps.audit.models import AuditLog
from apps.evidence import storage
from apps.evidence.finalization import charge_storage_once, finalize_upload
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from tests.atomic_publication.store import png
from tests.evidence.safety_access_helpers import (
    assert_no_effects, assert_presign, origin, safety_lab, snapshot, upload,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def lab(monkeypatch, settings):
    return safety_lab(monkeypatch, settings)


@pytest.mark.parametrize("size", [4097, 2**80], ids=["over-limit", "over-bigint"])
def test_http_declared_size_rejected_before_presign_or_rows(lab, settings, size):
    settings.EVIDENCE_MAX_BYTES = 4096
    before, calls = snapshot(), list(lab.store.calls)

    response = upload(lab, body={
        "evidence_type": "issue", "content_type": "image/png", "size_bytes": size,
    }, headers=origin(lab.home))

    assert response.status_code == 400, response.data
    assert response.data == {"size_bytes": ["Evidence size exceeds the upload limit."]}
    assert_no_effects(lab, before, calls)


@pytest.mark.parametrize("declaration", ["omitted", None, 0, 1, 4096])
def test_optional_and_bounded_http_declarations_remain_compatible(lab, settings, declaration):
    settings.EVIDENCE_MAX_BYTES = 4096
    body = {"evidence_type": "issue", "content_type": "image/png"}
    if declaration != "omitted":
        body["size_bytes"] = declaration

    response = upload(lab, body=body, headers=origin(lab.home))

    assert response.status_code == 201, response.data
    evidence = EvidencePhoto.objects.get(pk=response.data["evidence_id"])
    assert evidence.size_bytes == (None if declaration == "omitted" else declaration)
    assert_presign(lab, evidence)
    assert [name for name, _ in lab.store.calls] == ["presign"]
    assert AuditLog.objects.filter(action="evidence.upload_url_issued").count() == 1
    assert not EvidenceUploadFinalization.objects.exists()
    lab.home.refresh_from_db()
    assert lab.home.storage_bytes_used == 0


def test_http_cap_reads_current_override_not_import_time_field_metadata(lab, settings):
    body = {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 128}
    settings.EVIDENCE_MAX_BYTES = 127
    before, calls = snapshot(), list(lab.store.calls)
    rejected = upload(lab, body=body)
    assert rejected.status_code == 400
    assert_no_effects(lab, before, calls)

    settings.EVIDENCE_MAX_BYTES = 128
    accepted = upload(lab, body=body)
    assert accepted.status_code == 201, accepted.data
    evidence = EvidencePhoto.objects.get(pk=accepted.data["evidence_id"])
    assert_presign(lab, evidence)


@pytest.mark.parametrize("declared", [0, 4096], ids=["underdeclared", "overdeclared"])
def test_accepted_declaration_never_controls_actual_finalized_debit(lab, settings, declared):
    settings.EVIDENCE_MAX_BYTES = 4096
    response = upload(lab, body={
        "evidence_type": "issue", "content_type": "image/png", "size_bytes": declared,
    })
    assert response.status_code == 201, response.data
    evidence = EvidencePhoto.objects.get(pk=response.data["evidence_id"])
    assert_presign(lab, evidence)
    lab.store.seed(storage.staging_key(evidence.object_key), png(), "image/png")

    result = finalize_upload(evidence, settings.EVIDENCE_MAX_BYTES)
    charge_storage_once(evidence, result.size)
    charge_storage_once(evidence, result.size)

    lab.home.refresh_from_db()
    evidence.refresh_from_db()
    state = EvidenceUploadFinalization.objects.get(evidence=evidence)
    assert evidence.size_bytes == declared
    assert (state.size_bytes, state.quota_charged, lab.home.storage_bytes_used) == (
        len(png()), True, len(png()),
    )
    marker = AuditLog.objects.get(action="evidence.storage_charged", target_id=str(evidence.pk))
    assert marker.meta["bytes"] == len(png())
    assert marker.meta["journal_version"] == state.updated_at.isoformat()
    reads = {args["Key"] for name, args in lab.store.calls if name == "get"}
    assert {evidence.object_key, storage.staging_key(evidence.object_key)} <= reads
