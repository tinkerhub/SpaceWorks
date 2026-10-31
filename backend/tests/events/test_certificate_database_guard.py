"""PostgreSQL guards remain authoritative when callers bypass model.save()."""

from datetime import timedelta
from importlib import import_module

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.events.models import EventAttendanceCertificate
from tests.events.certificate_recovery_helpers import certificate_case, certificate_io, move_to


pytestmark = pytest.mark.django_db


def certificate_row(certificate):
    return EventAttendanceCertificate.objects.filter(pk=certificate.pk)


@pytest.mark.parametrize("status", ["pending", "failed", "rendering"])
def test_database_allows_unactivated_revocation(status, certificate_io):
    certificate = move_to(certificate_case(f"db-revoke-{status}").certificate, status)
    row = certificate_row(certificate)
    before = row.values().get()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE events_eventattendancecertificate SET status = %s WHERE id = %s",
            ["revoked", certificate.pk],
        )
        assert cursor.rowcount == 1

    assert row.values().get() == {**before, "status": "revoked"}
    certificate_io.render.assert_not_called()
    certificate_io.upload.assert_not_called()


FORBIDDEN_TRANSITIONS = [
    ("pending", "active"), ("pending", "failed"),
    ("failed", "pending"), ("failed", "active"),
    ("rendering", "pending"),
    ("active", "pending"), ("active", "rendering"), ("active", "failed"),
    ("revoked", "pending"), ("revoked", "rendering"),
    ("revoked", "active"), ("revoked", "failed"),
]


@pytest.mark.parametrize(
    "source,target", FORBIDDEN_TRANSITIONS,
    ids=[f"{source}-to-{target}" for source, target in FORBIDDEN_TRANSITIONS],
)
def test_database_rejects_backward_and_skip_transitions(source, target, certificate_io):
    certificate = certificate_case(f"db-{source}-{target}").certificate
    if source == "revoked":
        certificate_row(certificate).update(status="revoked")
    else:
        move_to(certificate, source)
    row = certificate_row(certificate)
    before = row.values().get()

    with pytest.raises(DatabaseError, match="invalid certificate status transition"):
        with transaction.atomic():
            row.update(status=target)

    assert row.values().get() == before


@pytest.mark.parametrize("field", ["object_key", "event_title", "recipient_name"])
def test_database_freezes_issuance_snapshots(field, certificate_io):
    certificate = certificate_case(f"db-snapshot-{field.replace('_', '-')}").certificate
    row = certificate_row(certificate)
    before = row.values().get()
    # Raw SQL also bypasses the separate mapped-PII QuerySet guard for recipient_name.
    column = connection.ops.quote_name(certificate._meta.get_field(field).column)

    with pytest.raises(DatabaseError, match="issuance snapshots are immutable"):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE events_eventattendancecertificate SET {column} = %s WHERE id = %s",
                ["replacement-snapshot", certificate.pk],
            )

    assert row.values().get() == before


def test_database_delete_requires_privileged_immutable_delete_flag(certificate_io):
    certificate = certificate_case("db-delete-guard").certificate
    row = certificate_row(certificate)
    before = row.values().get()
    sql = "DELETE FROM events_eventattendancecertificate WHERE id = %s"
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.allow_immutable_delete', true)")
        original_flag = cursor.fetchone()[0]
    assert original_flag != "on"

    with pytest.raises(DatabaseError, match="immutable certificate delete not allowed"):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, [certificate.pk])
    assert row.values().get() == before

    # Exercise the privileged contract, then roll back both the deletion and its GUC.
    # Fixture cleanup never needs a bypass.
    with transaction.atomic():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
                cursor.execute(sql, [certificate.pk])
                assert cursor.rowcount == 1
            assert not row.exists()
        finally:
            transaction.set_rollback(True)

    assert row.values().get() == before
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.allow_immutable_delete', true)")
        # PostgreSQL may retain an empty placeholder for a previously unset GUC.
        assert (cursor.fetchone()[0] or "") == (original_flag or "")


def changed_metadata(before):
    return {
        "size_bytes": (before["size_bytes"] or 0) + 1,
        "sha256": "b" * 64 if before["sha256"] != "b" * 64 else "c" * 64,
        "rendered_at": (before["rendered_at"] or timezone.now()) + timedelta(seconds=1),
    }


@pytest.mark.parametrize("field", ["size_bytes", "sha256", "rendered_at"])
def test_database_preserves_active_artifact_through_revocation(field, certificate_io):
    certificate = move_to(certificate_case(f"db-artifact-{field.replace('_', '-')}").certificate, "active")
    row = certificate_row(certificate)
    before = row.values().get()
    replacement = changed_metadata(before)[field]

    for updates in ({field: replacement}, {"status": "revoked", field: replacement}):
        with pytest.raises(DatabaseError, match="active certificate artifact is immutable"):
            with transaction.atomic():
                row.update(**updates)
        # A forbidden metadata edit must roll back the accompanying revocation too.
        assert row.values().get() == before

    assert row.update(status="revoked") == 1
    revoked = {**before, "status": "revoked"}
    assert row.values().get() == revoked

    with pytest.raises(DatabaseError, match="active certificate artifact is immutable"):
        with transaction.atomic():
            row.update(**{field: replacement})
    assert row.values().get() == revoked


@pytest.mark.parametrize("marker", ["size_bytes", "rendered_at"])
def test_database_freezes_artifact_markers_without_prior_active_status(marker, certificate_io):
    certificate = certificate_case(f"db-marker-{marker.replace('_', '-')}").certificate
    row = certificate_row(certificate)
    marker_value = 42 if marker == "size_bytes" else timezone.now()
    assert row.update(**{marker: marker_value}) == 1
    before = row.values().get()

    # Either retained marker freezes all artifact metadata, including after revoke.
    for status in ("pending", "revoked"):
        assert row.update(status=status) == 1
        expected = {**before, "status": status}
        for field, replacement in changed_metadata(expected).items():
            with pytest.raises(DatabaseError, match="active certificate artifact is immutable"):
                with transaction.atomic():
                    row.update(**{field: replacement})
            assert row.values().get() == expected


@pytest.mark.parametrize("status", ["pending", "failed", "rendering"])
def test_migration_reverse_restores_old_guard_and_forward_restores_recovery(status, certificate_io):
    migration = import_module("apps.events.migrations.0022_certificate_revocation_guard")
    original = import_module("apps.events.migrations.0017_event_feedback_certificates")
    assert migration.Migration.dependencies == [("events", "0021_offline_and_station_checkin")]
    assert migration.REVERSE_SQL.strip() == original.CERTIFICATE_TRIGGER.split("CREATE TRIGGER", 1)[0].strip()
    certificate = move_to(certificate_case(f"db-reverse-{status}").certificate, status)
    row = certificate_row(certificate)
    before = row.values().get()

    # PostgreSQL function DDL is transactional. Always roll back this savepoint,
    # including on assertion failure, so the installed guard cannot leak to peers.
    with transaction.atomic():
        try:
            with connection.cursor() as cursor:
                cursor.execute(migration.REVERSE_SQL)
            with pytest.raises(DatabaseError, match="invalid certificate status transition"):
                with transaction.atomic():
                    row.update(status="revoked")
            assert row.values().get() == before

            with connection.cursor() as cursor:
                cursor.execute(migration.FORWARD_SQL)
            assert row.update(status="revoked") == 1
            assert row.values().get() == {**before, "status": "revoked"}
        finally:
            transaction.set_rollback(True)

    assert row.values().get() == before
    assert row.update(status="revoked") == 1
    assert row.values().get() == {**before, "status": "revoked"}
