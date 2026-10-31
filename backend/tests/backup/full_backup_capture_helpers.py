"""Database-backed capture/publication preparation; synthetic payload, real freeze."""

from types import SimpleNamespace
import uuid

from django.db import connection, transaction
from django.utils import timezone

from apps.backup import artifact_ledger
from apps.backup.full_capture import DeploymentCapture
from apps.backup.models import BackupArchive, BackupRun
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.backup.object_ownership import build_object_ownership_plan
from apps.makerspaces.models import Makerspace
from tests.backup.full_backup_fixture_helpers import PLATFORM, make_full_fixture, sha


def space(**kwargs):
    return Makerspace.objects.create(name="Stage3 full", slug="full-" + uuid.uuid4().hex, **kwargs)


def archive(*, run=None):
    identifier, holder = uuid.uuid4(), uuid.uuid4()
    return BackupArchive.objects.create(
        id=identifier, scope="deployment", status="running", build_holder=holder, backup_run=run,
        object_key=f"backup-archives/deployment/{identifier}.tar.age",
        staging_object_key=f"backup-archives/staging/{identifier}/{holder}.tar.age",
    )


def run_for(cohort):
    return BackupRun.objects.create(cohort_at=timezone.now(), flag_snapshot=cohort,
                                    holder=uuid.uuid4(), status="running")


def capture(archive, root):
    DeploymentDatabaseIdentity.load()
    return DeploymentCapture(archive=archive, root=root,
                             modes={"private": "versioned", "public_image": "versioned"},
                             platform_recipients=[{"public_recipient": PLATFORM}])


def freeze_full(archive, root):
    root.mkdir()
    value = capture(archive, root)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT pg_export_snapshot()")
            assert cursor.fetchone()[0]
        value.select_from_snapshot()
        assert value.is_full
        (root / "database.dump").write_bytes(b"synthetic dump: no restore claim")
        value.prepare_from_snapshot()
        plan = build_object_ownership_plan(())
        plan.bind_component("main", root / "objects", [])
        value.capture_from_snapshot(object_plan=plan)
    return value


def prepared(tmp_path, *, scheduled=False, final_verified=True):
    ordinary = space()
    run = run_for({str(ordinary.pk): True}) if scheduled else None
    row = archive(run=run)
    frozen_capture = freeze_full(row, tmp_path / "capture")
    fixture = make_full_fixture(tmp_path, archive_id=row.pk, frozen=frozen_capture.promotion_snapshot(),
                                include_objects=False)
    # This real source has no object references. The envelope preserves that
    # exact empty closure and the independently frozen ownership/dump digest.
    build = SimpleNamespace(manifest=fixture.manifest, encrypted=fixture.encrypted,
                            promotion_snapshot=frozen_capture.promotion_snapshot(),
                            archive_sha256=sha(fixture.encrypted.read_bytes()))
    size = fixture.encrypted.stat().st_size
    ledger = artifact_ledger.persist_pending(row, build, size)
    if final_verified:
        artifact_ledger.mark_final_verified(ledger.pk, size, build.archive_sha256)
    return ordinary, row, ledger, build, run
