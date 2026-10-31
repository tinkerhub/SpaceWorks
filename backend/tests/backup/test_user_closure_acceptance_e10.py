"""Lane E section 11 row 15: Decision 20 digest acceptance."""

from copy import deepcopy

import pytest
from django.db import DatabaseError, transaction

from apps.audit.models import AuditLog
from apps.backup import artifact_ledger, outer_manifest, promotion
from apps.backup.models import BackupArtifactLedger, PlatformBackupSettings
from tests.backup.e10_test_helpers import (
    independent_user_closure_digest,
    resign_source_proof,
)
from tests.backup.test_promotion_e5 import _final_verified, _prepared


pytestmark = pytest.mark.django_db(transaction=True)


ORIGINAL_CLOSURE = (
    ("stubbed", "1", "sovereign-global-user-reference"),
)


def test_manifest_and_audit_each_equal_an_independently_derived_closure_digest(
    tmp_path,
):
    _space, _recipient, archive, ledger, _size, _digest = _final_verified(tmp_path)
    expected = independent_user_closure_digest(ORIGINAL_CLOSURE)

    promotion.promote_verified_artifact(ledger.pk)

    archive.refresh_from_db()
    completed = AuditLog.objects.get(
        action="backup.archive_completed", target_id=str(archive.pk)
    )
    assert archive.manifest["user_closure_digest"] == expected
    assert completed.meta["user_closure_digest"] == expected


def _replace_signed_closure(ledger, entries):
    manifest = deepcopy(ledger.outer_manifest)
    digest = independent_user_closure_digest(entries)
    manifest["user_closure_digest"] = digest
    proof = deepcopy(manifest["source_partition_proof"])
    proof["user_closure_digest"] = digest
    manifest["source_partition_proof"] = resign_source_proof(proof)
    unsigned = dict(manifest)
    unsigned.pop("archive_signature")
    components = [
        unsigned["main_component"], *unsigned["slice_components"]
    ]
    manifest["archive_signature"] = outer_manifest._signature(
        unsigned, components
    )
    BackupArtifactLedger.objects.filter(pk=ledger.pk).update(
        outer_manifest=manifest,
        outer_manifest_sha256=outer_manifest.manifest_digest(manifest),
    )


@pytest.mark.parametrize(
    "changed",
    ((), (("included", "1", "sovereign-global-user-reference"),)),
    ids=("omitted", "disposition-drift"),
)
def test_omission_or_disposition_drift_prevents_availability(changed, tmp_path):
    expected = independent_user_closure_digest(ORIGINAL_CLOSURE)
    changed_digest = independent_user_closure_digest(changed)
    assert changed_digest != expected
    # Freeze independently derived drift before the immutable ledger is created.
    space, _recipient, archive, ledger, size, digest = _prepared(
        tmp_path, promotion_closure_digest=changed_digest,
    )
    artifact_ledger.mark_final_verified(ledger.pk, size, digest)
    assert ledger.outer_manifest["user_closure_digest"] == expected
    assert ledger.outer_manifest["source_partition_proof"]["user_closure_digest"] == expected
    assert ledger.frozen_promotion_snapshot["user_closure_digest"] == changed_digest

    with pytest.raises(
        artifact_ledger.ArtifactLedgerMismatch,
        match="independently recomputed user-closure digest",
    ):
        promotion.promote_verified_artifact(ledger.pk)

    archive.refresh_from_db()
    ledger.refresh_from_db()
    assert archive.status == "running"
    assert ledger.state == "final_verified"
    assert space.b1_activation_state.state == "off_pending"
    assert not AuditLog.objects.filter(
        action="backup.archive_completed", target_id=str(archive.pk),
    ).exists()
    assert not AuditLog.objects.filter(action="backup.archive_exclusion_activated").exists()
    assert PlatformBackupSettings.load().last_success_at is None


def test_signed_closure_cannot_rewrite_immutable_retained_ledger(tmp_path):
    space, _recipient, archive, ledger, _size, _digest = _final_verified(tmp_path)
    before = deepcopy(ledger.outer_manifest)
    before_digest = ledger.outer_manifest_sha256
    frozen = deepcopy(ledger.frozen_promotion_snapshot)

    with pytest.raises(DatabaseError, match="immutable backup artifact facts"), transaction.atomic():
        _replace_signed_closure(ledger, ())

    ledger.refresh_from_db()
    archive.refresh_from_db()
    assert ledger.outer_manifest == before
    assert ledger.outer_manifest_sha256 == before_digest
    assert ledger.frozen_promotion_snapshot == frozen
    assert ledger.state == "final_verified"
    assert archive.status == "running"
    assert space.b1_activation_state.state == "off_pending"
    assert not AuditLog.objects.filter(action="backup.archive_completed").exists()
    assert not AuditLog.objects.filter(action="backup.archive_exclusion_activated").exists()
    assert PlatformBackupSettings.load().last_success_at is None
