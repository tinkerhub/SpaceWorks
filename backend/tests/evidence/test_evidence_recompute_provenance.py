"""EVID-S03: reconcile canonical evidence without trusting client declarations."""
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence import storage
from apps.evidence.finalization import finalize_upload
from apps.evidence.models import EvidenceObjectRetentionState, EvidenceUploadFinalization
from apps.evidence.services_retention import sweep_evidence_retention
from apps.inventory import public_image_storage
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from tests.atomic_publication.store import error, png
from tests.evidence.safety_access_helpers import charged_photo, photo, safety_lab


# The command owns an autocommit boundary. Fixtures must be committed and visible to
# its independent lock connection; do not convert these to TestCase-style atomic tests.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def lab(monkeypatch, settings):
    value = safety_lab(monkeypatch, settings)
    monkeypatch.setattr(public_image_storage, "_client", lambda: value.store)
    return value


def recompute(lab):
    assert connection.get_autocommit() and not connection.in_atomic_block
    output = StringIO()
    call_command("recompute_storage", lab.home.slug, stdout=output)
    lab.home.refresh_from_db()
    return output.getvalue()


def proof_snapshot(evidence):
    return (
        list(EvidenceUploadFinalization.objects.filter(evidence=evidence).values()),
        list(AuditLog.objects.order_by("pk").values()),
    )


@pytest.mark.parametrize("observed", [None, b"observed-final-bytes"], ids=["missing", "observed"])
def test_legacy_declared_size_never_becomes_accounted_bytes(lab, observed):
    evidence = photo(lab, declared=999_999)
    if observed is not None:
        lab.store.seed(evidence.object_key, observed, "image/png")
    Makerspace.objects.filter(pk=lab.home.pk).update(storage_bytes_used=777)
    before = proof_snapshot(evidence)

    output = recompute(lab)

    expected = len(observed) if observed is not None else 0
    assert lab.home.storage_bytes_used == expected
    assert f"total={expected} bytes" in output
    assert proof_snapshot(evidence) == before  # no proof minting or legacy flag repair
    assert [(name, args["Key"]) for name, args in lab.store.calls] == [
        ("head", evidence.object_key),
    ]


def test_staged_unattached_object_stays_outside_existing_row_accounting(lab):
    evidence = photo(lab, declared=999_999)
    staged = storage.staging_key(evidence.object_key)
    lab.store.seed(staged, png(), "image/png")
    before = proof_snapshot(evidence)

    recompute(lab)

    assert lab.home.storage_bytes_used == 0
    assert staged in lab.store.objects
    assert proof_snapshot(evidence) == before
    assert [args["Key"] for name, args in lab.store.calls if name == "head"] == [evidence.object_key]


def test_legacy_handled_flag_is_neither_debit_proof_nor_repaired_by_recompute(lab):
    evidence = photo(lab)
    lab.store.seed(storage.staging_key(evidence.object_key), png(), "image/png")
    assert finalize_upload(evidence, 1024 * 1024).size == len(png())
    # Model a pre-proof legacy flag; no call to charge_storage_once and no debit.
    EvidenceUploadFinalization.objects.filter(evidence=evidence).update(quota_charged=True)
    lab.store.objects.pop(evidence.object_key)
    lab.store.calls.clear()
    before = proof_snapshot(evidence)

    recompute(lab)

    assert lab.home.storage_bytes_used == 0
    assert proof_snapshot(evidence) == before
    assert [name for name, _ in lab.store.calls] == ["head"]


@pytest.mark.parametrize("observed", [None, b"x", b"x" * 200], ids=["missing", "smaller", "larger"])
def test_real_finite_debit_preserves_journal_bytes_until_expiry(lab, settings, observed):
    evidence, state, marker = charged_photo(lab)
    lab.home.refresh_from_db()
    assert lab.home.storage_bytes_used == len(png())
    if observed is None:
        lab.store.objects.pop(evidence.object_key)
    else:
        lab.store.seed(evidence.object_key, observed, "image/png")
    lab.store.calls.clear()
    before = proof_snapshot(evidence)

    recompute(lab)

    assert lab.home.storage_bytes_used == len(png())
    assert marker.meta["bytes"] == state.size_bytes == len(png())
    assert proof_snapshot(evidence) == before
    assert [name for name, _ in lab.store.calls] == ["head"]
    assert lab.store.calls[0][1]["Key"] == evidence.object_key

    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    result = sweep_evidence_retention(now=timezone.now() + timedelta(days=31))
    assert (result["photos_expired"], result["photos_failed"]) == (1, 0)
    event = AuditLog.objects.get(action="evidence.object_expired", target_id=str(evidence.pk))
    assert event.meta["quota_released_bytes"] == len(png())
    expected_removed = len(observed) if observed is not None else len(png())
    assert event.meta["expired_size_bytes"] == expected_removed
    lab.home.refresh_from_db()
    assert lab.home.storage_bytes_used == 0
    lab.store.calls.clear()
    recompute(lab)
    assert lab.home.storage_bytes_used == 0
    assert lab.store.calls == []  # terminal expiry never consults HEAD again


@pytest.mark.parametrize("proven", [False, True], ids=["legacy", "charged"])
def test_provider_head_failure_aborts_whole_counter_set(lab, monkeypatch, proven):
    evidence = charged_photo(lab)[0] if proven else photo(lab)
    InventoryProduct.objects.create(
        makerspace=lab.home, name="Canonical public image", image_key="items/safety/image",
    )
    lab.store.seed("items/safety/image", b"other-category", "image/png")
    Makerspace.objects.filter(pk=lab.home.pk).update(storage_bytes_used=777)
    Makerspace.objects.filter(pk=lab.other.pk).update(storage_bytes_used=333)
    before = proof_snapshot(evidence)
    lab.store.calls.clear()
    real_head = lab.store.head_object

    def fail_evidence(**kwargs):
        if kwargs["Key"] == evidence.object_key:
            lab.store._call("head", kwargs)
            raise error("AccessDenied", 403)
        return real_head(**kwargs)

    head = Mock(side_effect=fail_evidence)
    monkeypatch.setattr(lab.store, "head_object", head)

    output = recompute(lab)

    assert "usage left unchanged due to storage read error" in output
    assert lab.home.storage_bytes_used == 777
    lab.other.refresh_from_db()
    assert lab.other.storage_bytes_used == 333
    assert proof_snapshot(evidence) == before
    head.assert_called_once_with(Bucket=storage.settings.AWS_STORAGE_BUCKET_NAME, Key=evidence.object_key)


def test_actual_expiry_then_recompute_keeps_other_categories_and_tenants(lab, settings):
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    evidence, state, marker = charged_photo(lab)
    image_key, image_bytes = "items/safety/canonical", b"public-image-size"
    InventoryProduct.objects.create(makerspace=lab.home, name="Image", image_key=image_key)
    lab.store.seed(image_key, image_bytes, "image/png")
    Makerspace.objects.filter(pk=lab.other.pk).update(storage_bytes_used=333)
    immutable_before = list(type(evidence).objects.filter(pk=evidence.pk).values())
    recompute(lab)
    assert lab.home.storage_bytes_used == len(png()) + len(image_bytes)

    result = sweep_evidence_retention(now=timezone.now() + timedelta(days=31))

    assert (result["photos_expired"], result["photos_failed"]) == (1, 0)
    expired = EvidenceObjectRetentionState.objects.get(evidence=evidence)
    assert expired.status == "expired"
    event = AuditLog.objects.get(action="evidence.object_expired", target_id=str(evidence.pk))
    assert event.meta["quota_released_bytes"] == marker.meta["bytes"] == state.size_bytes
    lab.home.refresh_from_db()
    assert lab.home.storage_bytes_used == len(image_bytes)
    assert list(type(evidence).objects.filter(pk=evidence.pk).values()) == immutable_before
    assert evidence.object_key not in lab.store.objects
    assert storage.staging_key(evidence.object_key) not in lab.store.objects
    assert any(name == "list" and args["Prefix"] == evidence.object_key for name, args in lab.store.calls)
    assert any(name == "delete" for name, _ in lab.store.calls)
    lab.store.calls.clear()

    recompute(lab)

    assert lab.home.storage_bytes_used == len(image_bytes)
    assert [(name, args["Key"]) for name, args in lab.store.calls] == [("head", image_key)]
    lab.other.refresh_from_db()
    assert lab.other.storage_bytes_used == 333
    assert lab.store.objects[image_key][0] == image_bytes
    assert AuditLog.objects.filter(action="evidence.storage_charged").count() == 1
