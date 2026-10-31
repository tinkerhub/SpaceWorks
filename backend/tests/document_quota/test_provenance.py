"""Untrusted historical/imported markers cannot manufacture a quota refund."""
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from apps.audit import services as audit
from apps.makerspaces.models import Makerspace
from apps.warranty.models import WarrantyDocument
from apps.procurement.models import ToBuyReceipt
from tests.document_safety.helpers import accepted_body, cap, lab, usage
from tests.document_quota.helpers import (
    RELEASE, added_action, delete, expected_meta, legacy_row, releases, upload,
)

pytestmark = pytest.mark.django_db(transaction=True)

BAD_META = [
    ("version", True), ("version", 0), ("version", -1), ("version", "1"),
    ("bytes", True), ("bytes", 0), ("bytes", -1), ("bytes", "512"),
    ("accounting_database_id", None), ("accounting_database_id", str(UUID(int=0))),
    ("accounting_database_id", str(uuid4())),
    ("accounting_database_id", "not-a-uuid"),
    ("storage_origin", "0" * 64), ("storage_origin", None),
    ("object_key_sha256", "0" * 64), ("object_key_sha256", None),
    ("row_created_at", None), ("row_created_at", "2026-01-01T00:00:00"),
]


@pytest.mark.parametrize("kind", ["receipt"])
@pytest.mark.parametrize("field,value", BAD_META, ids=[f"{field}-{index}" for index, (field, _) in enumerate(BAD_META)])
def test_invalid_explicit_marker_cannot_credit_legacy_document(
    kind, field, value, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    row = legacy_row(case)
    body = accepted_body("application/pdf")
    case.store.seed(row.object_key, body)
    meta = expected_meta(case, row, len(body)) | {field: value}
    audit.record(case.actor, added_action(case), makerspace=case.home, target=row, meta=meta)
    assert delete(case, row).status_code == 204
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == 900 and not releases(case).exists()


@pytest.mark.parametrize("kind", ["receipt", "asset"])
@pytest.mark.parametrize("mismatch", [
    "source-prefix", "uppercase-uuid", "compact-uuid", "tenant", "type", "target",
    "created-other-incarnation", "noncanonical-time", "legacy-added-size", "empty-meta",
])
def test_identity_scope_incarnation_and_old_added_size_do_not_prove_debit(
    kind, mismatch, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    row = legacy_row(case)
    body = accepted_body("application/pdf")
    case.store.seed(row.object_key, body)
    meta = expected_meta(case, row, len(body))
    space, target = case.home, row
    if mismatch == "source-prefix":
        meta["accounting_database_id"] = "source:" + meta["accounting_database_id"]
    elif mismatch == "uppercase-uuid":
        meta["accounting_database_id"] = meta["accounting_database_id"].upper()
    elif mismatch == "compact-uuid":
        meta["accounting_database_id"] = meta["accounting_database_id"].replace("-", "")
    elif mismatch == "tenant":
        space = case.other
    elif mismatch == "type":
        other_model = WarrantyDocument if kind == "receipt" else ToBuyReceipt
        target = other_model(pk=row.pk)
    elif mismatch == "target":
        target = case.model(pk=row.pk + 1000000)
    elif mismatch == "created-other-incarnation":
        meta["row_created_at"] = (row.created_at - timedelta(days=1)).isoformat()
    elif mismatch == "noncanonical-time":
        meta["row_created_at"] = row.created_at.isoformat().replace("+00:00", "Z")
    elif mismatch == "legacy-added-size":
        meta = {"size_bytes": len(body), "content_type": "application/pdf"}
    else:
        meta = {}
    audit.record(case.actor, added_action(case), makerspace=space, target=target, meta=meta)
    assert delete(case, row).status_code == 204
    assert usage(case) == 900 and not releases(case).exists()


@pytest.mark.parametrize("kind", ["receipt"])
@pytest.mark.parametrize("conflict", ["duplicate", "different-bytes", "partial", "prior-release"])
def test_conflicting_or_previously_released_real_charge_is_conservative(
    kind, conflict, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    row, charge, body = upload(case)
    if conflict == "prior-release":
        audit.record(None, RELEASE, makerspace=case.home, target=row,
                     meta={"charge_event_uuid": str(charge.event_uuid)})
    else:
        meta = charge.meta.copy()
        if conflict == "different-bytes":
            meta["bytes"] += 1
        elif conflict == "partial":
            meta = {"version": 1}
        audit.record(None, charge.action, makerspace=case.home, target=row, meta=meta)
    before = releases(case).count()
    assert delete(case, row).status_code == 204
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == 900 + len(body) and releases(case).count() == before


@pytest.mark.parametrize("kind", ["asset"])
def test_other_canonical_incarnation_does_not_conflict_with_actual_live_charge(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, charge, _ = upload(case)
    prior = charge.meta | {"row_created_at": (row.created_at - timedelta(days=1)).isoformat()}
    audit.record(None, charge.action, makerspace=case.home, target=row, meta=prior)
    assert delete(case, row).status_code == 204
    assert usage(case) == 0 and releases(case).count() == 1


@pytest.mark.parametrize("kind", ["receipt"])
def test_insufficient_locked_counter_refuses_refund_instead_of_clamping(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, _, body = upload(case)
    Makerspace.objects.filter(pk=case.home.pk).update(storage_bytes_used=len(body) - 1)
    assert delete(case, row).status_code == 204
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == len(body) - 1 and not releases(case).exists()
