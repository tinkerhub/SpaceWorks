"""Real snapshot/source facts; synthetic dump bytes are not restore/image evidence."""

from contextlib import contextmanager
import os

import psycopg2
from django.db import connection, transaction

from apps.backup import archive_payload, full_capture
from apps.backup.digests import build_content_ledger
from apps.makerspaces.models import Makerspace
from tests.backup.full_backup_capture_helpers import archive, capture
from tests.backup.full_backup_fixture_helpers import BUILD, OCI


def set_digest(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SPACEWORKS_OCI_DIGEST", raising=False)
        assert "SPACEWORKS_OCI_DIGEST" not in os.environ
    else:
        monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", value)


@contextmanager
def exported_readonly_snapshot():
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot = cursor.fetchone()[0]
            assert snapshot
        yield snapshot


def forbid_capture_io(monkeypatch):
    """Negative instrumentation: none of these seams may run on refusal."""
    calls = []

    def forbidden(name):
        def call(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"Unexpected {name} before runtime identity admission")
        return call

    for module, name in (
        (full_capture, "capture_source_identity"),
        (archive_payload, "_pg_dump"),
        (archive_payload, "_capture_objects"),
        (archive_payload.storage, "client"),
    ):
        monkeypatch.setattr(module, name, forbidden(name))
    return calls


def captured_full_payload(tmp_path, monkeypatch, *, later_digest=OCI):
    """Production payload/projection/signing with an imported real PG snapshot.

    Only pg_dump transport, its version text and build labels are synthetic.
    Source identity, population, object closure and all validators remain real.
    """
    set_digest(monkeypatch, OCI)
    row = archive()
    value = capture(row, tmp_path)
    snapshots = []
    expected_ids = list(Makerspace.objects.order_by("pk").values_list("pk", flat=True))

    def dump(destination, snapshot_id, *, exclude_operational=False):
        assert exclude_operational is True
        assert value.is_full and value.oci_digest == OCI
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone()[0] == "on"
        with psycopg2.connect(**connection.get_connection_params()) as observer:
            with observer.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SET TRANSACTION SNAPSHOT %s", [snapshot_id])
                cursor.execute("SELECT id FROM makerspaces_makerspace ORDER BY id")
                assert [item[0] for item in cursor.fetchall()] == expected_ids
        snapshots.append(snapshot_id)
        destination.write_bytes(b"synthetic dump: no restore claim")
        set_digest(monkeypatch, later_digest)

    monkeypatch.setattr(archive_payload, "_pg_dump", dump)
    monkeypatch.setattr(archive_payload, "_command_version", lambda _cmd: "pg_dump (PostgreSQL) 16.4")
    monkeypatch.setattr(archive_payload, "_build_info", lambda: dict(BUILD))

    def unexpected_provider(**_kwargs):
        raise AssertionError("Empty object closure must not access a provider")

    monkeypatch.setattr(archive_payload.storage, "client", unexpected_provider)
    detailed = archive_payload._snapshot_payload(
        row, tmp_path, value._kwargs["modes"], value._kwargs["platform_recipients"],
        compound_capture=value,
    )
    assert len(snapshots) == 1
    detailed = value.project_readable_main(detailed)
    detailed["contents"] = build_content_ledger(tmp_path)
    return value, detailed
