"""Snapshot selection tests; synthetic dumps here are not restore evidence."""

from types import SimpleNamespace
import uuid

import psycopg2
import pytest
from django.db import InternalError, connection, transaction
from django.utils import timezone

from apps.backup import archive_payload
from apps.backup.compound_archive import CompoundCapture
from apps.backup.errors import BackupBuildError
from apps.backup.full_population import run_facts
from apps.backup.models import B1ActivationState, BackupArchive, BackupRun
from tests.backup.full_backup_capture_helpers import archive, capture, freeze_full, run_for, space
from tests.backup.full_backup_fixture_helpers import OCI


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def synthetic_runtime_image_identity(monkeypatch):
    """Satisfy FULL admission only in this module; this is no image attestation."""
    monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", OCI)


@pytest.mark.parametrize("count", [0, 1, 3])
def test_actual_snapshot_payload_selects_full_before_dump_in_exported_transaction(
    tmp_path, monkeypatch, count,
):
    rows = [space() for _ in range(count)]
    row = archive()
    value = capture(row, tmp_path)
    observed = []

    def dump(destination, snapshot, *, exclude_operational=False):
        assert connection.in_atomic_block
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            assert cursor.fetchone()[0] == "repeatable read"
        # Import the exact exported ID on a genuinely separate connection.
        with psycopg2.connect(**connection.get_connection_params()) as observer:
            with observer.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SET TRANSACTION SNAPSHOT %s", [snapshot])
                cursor.execute("SELECT id FROM makerspaces_makerspace ORDER BY id")
                assert [item[0] for item in cursor.fetchall()] == [item.pk for item in rows]
        assert value.is_full and value._selected and not value._prepared
        assert exclude_operational is True
        observed.append(snapshot)
        destination.write_bytes(b"unit-test synthetic dump")

    monkeypatch.setattr(archive_payload, "_pg_dump", dump)
    monkeypatch.setattr(archive_payload, "_command_version", lambda _cmd: "pg_dump (PostgreSQL) 16.4")
    detailed = archive_payload._snapshot_payload(
        row, tmp_path, value._kwargs["modes"], value._kwargs["platform_recipients"], compound_capture=value,
    )
    frozen = value.promotion_snapshot()
    assert len(observed) == 1
    assert [item["makerspace_id"] for item in frozen["retained"]] == [item.pk for item in rows]
    assert frozen["servable_run_cohort"] == {str(item.pk): True for item in rows}
    assert detailed["backup_run_id"] is None
    assert frozen["source_database_identity"] == connection.settings_dict["NAME"]


def test_archived_retained_space_still_needs_consent_and_selects_actual_compound(tmp_path):
    space()
    archived = space(archived_at=timezone.now(), superadmin_access_enabled=False)
    value = capture(archive(), tmp_path)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT pg_export_snapshot()")
            assert cursor.fetchone()[0]
        value.select_from_snapshot()
    assert value.is_full is False
    assert isinstance(value._compound, CompoundCapture)
    assert B1ActivationState.objects.get(makerspace=archived).state == "off_pending"


@pytest.mark.parametrize("change", ["missing", "divergent"])
def test_missing_or_divergent_activation_refuses_instead_of_falling_back(tmp_path, change):
    ordinary = space()
    if change == "missing":
        B1ActivationState.objects.filter(makerspace=ordinary).delete()
    else:
        B1ActivationState.objects.filter(makerspace=ordinary).update(state="off_pending")
    value = capture(archive(), tmp_path)
    with pytest.raises(BackupBuildError, match="incomplete|diverge"):
        with transaction.atomic():
            value.select_from_snapshot()


def test_run_cohort_is_servable_only_and_facts_are_frozen(tmp_path):
    ordinary = space()
    archived = space(archived_at=timezone.now())
    run = run_for({str(ordinary.pk): True})
    row = archive(run=run)
    value = freeze_full(row, tmp_path / "capture")
    before = value.promotion_snapshot()
    assert [item["makerspace_id"] for item in before["retained"]] == [ordinary.pk, archived.pk]
    assert before["servable_run_cohort"] == {str(ordinary.pk): True}
    assert before["run"] == {"id": str(run.pk), "holder": str(run.holder),
                              "status": "running", "flag_snapshot": {str(ordinary.pk): True}}
    with transaction.atomic():
        with pytest.raises(InternalError, match="immutable backup run flag_snapshot"), transaction.atomic():
            BackupRun.objects.filter(pk=run.pk).update(flag_snapshot={})
    run.refresh_from_db()
    assert run.flag_snapshot == {str(ordinary.pk): True}
    assert str(run.holder) == before["run"]["holder"]
    # Holder rotation is mutable; the captured facts must still be independent.
    BackupRun.objects.filter(pk=run.pk).update(holder=uuid.uuid4())
    assert value.promotion_snapshot() == before
    before["run"]["flag_snapshot"].clear()
    before["retained"].clear()
    assert len(value.promotion_snapshot()["retained"]) == 2
    assert value.promotion_snapshot()["run"]["flag_snapshot"] == {str(ordinary.pk): True}


@pytest.mark.parametrize("flags", [{}, {"01": True}, {"1": 1}, {"1": False}, {"-1": True}])
def test_run_requires_exact_canonical_typed_flags(tmp_path, flags):
    ordinary = space()
    if flags == {"1": 1}:
        flags = {str(ordinary.pk): 1}
    elif flags == {"1": False}:
        flags = {str(ordinary.pk): False}
    run = run_for(flags)
    value = capture(archive(run=run), tmp_path)
    with pytest.raises(BackupBuildError):
        with transaction.atomic():
            value.select_from_snapshot()


@pytest.mark.parametrize("invalid", ["archived-cohort", "missing-holder"])
def test_run_cannot_include_archived_retained_space_or_missing_holder(tmp_path, invalid):
    ordinary, archived = space(), space(archived_at=timezone.now())
    flags = {str(ordinary.pk): True}
    if invalid == "archived-cohort":
        flags[str(archived.pk)] = True
    # Each case inserts its own invalid input, before any capture is accepted.
    run = BackupRun.objects.create(cohort_at=timezone.now(), flag_snapshot=flags,
                                   holder=None if invalid == "missing-holder" else uuid.uuid4(),
                                   status="running")
    row = archive(run=run)
    with pytest.raises(BackupBuildError, match="holder, status or exact cohort"):
        run_facts(row, {str(ordinary.pk): True})


def test_cached_run_relation_cannot_replace_persisted_binding(tmp_path):
    ordinary = space()
    run = run_for({str(ordinary.pk): True})
    row = archive(run=run)
    with transaction.atomic():
        with pytest.raises(InternalError, match="immutable backup archive backup_run"), transaction.atomic():
            BackupArchive.objects.filter(pk=row.pk).update(backup_run=None)
    assert BackupArchive.objects.get(pk=row.pk).backup_run_id == run.pk
    # Only the caller's stale object disagrees; the persisted binding stays intact.
    row.backup_run_id = None
    with pytest.raises(BackupBuildError, match="binding"):
        run_facts(row, {str(ordinary.pk): True})
    row.refresh_from_db()
    assert run_facts(row, {str(ordinary.pk): True})["id"] == str(run.pk)


def test_capture_refuses_late_selection_and_mutated_source_references(tmp_path):
    value = capture(archive(), tmp_path)
    with pytest.raises(BackupBuildError, match="before the source dump"):
        value.prepare_from_snapshot()
    frozen = freeze_full(archive(), tmp_path / "freeze")
    frozen.object_plan.references = (SimpleNamespace(injected="post-capture"),)
    with pytest.raises(BackupBuildError, match="references changed"):
        frozen.promotion_snapshot()
