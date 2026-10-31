"""The authoritative SET cannot outlive its actual PostgreSQL exclusive owner."""
from io import StringIO

import psycopg2
import pytest
from django.core.management.base import CommandError

from apps.audit.models import AuditLog
from apps.backup.models import DeploymentRecoveryState
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_runtime import (
    _exclusive_boundary_connection, assert_boundary_held, boundary_tenant_write,
)
from tests.makerspaces.storage_recompute_faults import instrument, updates
from tests.makerspaces.storage_recompute_support import (
    WAIT, await_lock, counter, image_request, jobs, locks, recompute, sql, storage_case,
)

pytestmark = pytest.mark.django_db(transaction=True)


def accepted_with_stale_counter(case):
    key, size = case.staged()
    image_request(case.space, case.actor, key=key)
    assert counter(case.space) == size
    Makerspace.objects.filter(pk=case.space.pk).update(storage_bytes_used=999)
    return key, size


def test_setter_backend_equals_holder_and_exclusion_survives_update_until_commit(
    storage_case, jobs, monkeypatch,
):
    case = storage_case
    _key, size = accepted_with_stale_counter(case)
    audit_ids = list(AuditLog.objects.order_by("pk").values_list("pk", flat=True))
    entered, release, pause = jobs.pause()
    observed = []

    def after_update(probe, cursor):
        cursor.execute("SELECT pg_backend_pid(), storage_bytes_used FROM makerspaces_makerspace WHERE id=%s",
                       [case.space.pk])
        pid, value = cursor.fetchone()
        assert value == size
        assert await_lock(case.space.pk, "ExclusiveLock", granted=True) == pid
        observed.append(("update", pid))
        pause()

    def before_commit(probe):
        pid = probe.raw.get_backend_pid()
        assert await_lock(case.space.pk, "ExclusiveLock", granted=True) == pid
        observed.append(("commit", pid))

    opened = instrument(monkeypatch, after_update=after_update, before_commit=before_commit)
    output = StringIO()
    command = jobs.spawn(lambda: recompute(case.space, output))
    assert entered.wait(WAIT)
    holder = await_lock(case.space.pk, "ExclusiveLock", granted=True)
    assert observed == [("update", holder)]
    assert counter(case.space) == 999, "Setter became visible before retained-backend commit"
    assert "total=" not in output.getvalue()
    release.set()
    assert f"total={size} bytes" in command.result()
    assert observed == [("update", holder), ("commit", holder)]
    assert len(opened) == 1 and opened[0].commits == 1
    assert opened[0].raw.closed and len(updates(opened[0])) == 1
    assert counter(case.space) == size and locks(case.space.pk) == []
    assert list(AuditLog.objects.order_by("pk").values_list("pk", flat=True)) == audit_ids


@pytest.mark.parametrize("gap", ["scan", "after-final-verification"])
def test_killed_retained_backend_cannot_set_reconnect_or_announce_success(
    storage_case, monkeypatch, gap,
):
    case = storage_case
    accepted_with_stale_counter(case)
    killed = []

    def kill(probe):
        pid = probe.raw.get_backend_pid()
        assert await_lock(case.space.pk, "ExclusiveLock", granted=True) == pid
        assert sql("SELECT pg_terminate_backend(%s)", [pid]) == [(True,)]
        killed.append(pid)

    def before_update(probe, _cursor, _statement, _params):
        # All ownership queries above were real; the immediately preceding one is
        # the command's last verification. Kill before delegating the real UPDATE.
        assert "SELECT pg_backend_pid(), EXISTS" in probe.statements[-2][0]
        kill(probe)

    opened = instrument(monkeypatch, before_update=before_update if gap != "scan" else None)
    if gap == "scan":
        head = case.store.head_object

        def killed_head(**params):
            result = head(**params)
            if not killed:
                kill(opened[0])
            return result

        monkeypatch.setattr(case.store, "head_object", killed_head)
    output = StringIO()
    with pytest.raises((psycopg2.Error, SourceMigrationGateUnavailable)):
        recompute(case.space, output)
    assert len(killed) == len(opened) == 1
    assert sum("SELECT pg_advisory_xact_lock(" in s for s, _ in opened[0].statements) == 1
    assert opened[0].commits == 0 and opened[0].raw.closed
    assert len(updates(opened[0])) == (0 if gap == "scan" else 1)
    assert counter(case.space) == 999 and "total=" not in output.getvalue()
    assert locks(case.space.pk) == []


def test_lost_commit_ack_reports_uncertain_fresh_rescan_after_real_commit(storage_case, monkeypatch):
    case = storage_case
    _key, size = accepted_with_stale_counter(case)

    def lost_ack(_probe):
        raise psycopg2.OperationalError("injected acknowledgement loss after server COMMIT")

    opened = instrument(monkeypatch, after_commit=lost_ack)
    output = StringIO()
    with pytest.raises(CommandError, match="outcome uncertain; fresh rescan required") as error:
        recompute(case.space, output)
    assert counter(case.space) == size, "Injection must follow a real committed setter"
    assert "unchanged" not in str(error.value) + output.getvalue()
    assert "total=" not in output.getvalue()
    assert len(opened) == 1 and opened[0].commits == 1 and opened[0].raw.closed
    assert locks(case.space.pk) == []


@pytest.mark.parametrize("fault", ["sql", "rowcount-zero", "rowcount-zero-missing", "scan"])
def test_real_sql_or_scan_failure_rolls_back_releases_and_never_reports_success(
    storage_case, monkeypatch, fault,
):
    case = storage_case
    accepted_with_stale_counter(case)

    def before_update(_probe, cursor, _statement, _params):
        if fault == "sql":
            cursor.execute("SELECT 1 / 0")
        elif fault == "rowcount-zero":
            # Change recovery after final admission/verification. The actual SQL
            # predicate, rather than a fake cursor.rowcount, must refuse the SET.
            DeploymentRecoveryState.objects.filter(pk=1).update(mode="quiesced")
        elif fault == "rowcount-zero-missing":
            DeploymentRecoveryState.objects.filter(pk=1).delete()

    opened = instrument(monkeypatch, before_update=before_update)
    if fault == "scan":
        def failed_head(**_params):
            raise OSError("deliberate provider outage")
        monkeypatch.setattr(case.store, "head_object", failed_head)
    output = StringIO()
    if fault == "scan":
        recompute(case.space, output)
        assert "storage read error" in output.getvalue()
    else:
        with pytest.raises(psycopg2.Error if fault == "sql" else CommandError):
            recompute(case.space, output)
    assert counter(case.space) == 999 and "total=" not in output.getvalue()
    assert len(opened) == 1 and opened[0].commits == 0
    assert opened[0].rollbacks == 1 and opened[0].raw.closed
    assert locks(case.space.pk) == []


@pytest.mark.parametrize("end", ["commit", "rollback"])
def test_ended_transaction_owner_cannot_be_used_again(storage_case, end):
    space = storage_case.space
    with boundary_tenant_write(space.pk, exclusive=True):
        retained = _exclusive_boundary_connection(space.pk)
        assert await_lock(space.pk, "ExclusiveLock", granted=True) == retained.get_backend_pid()
        getattr(retained, end)()
        assert locks(space.pk) == []
        with pytest.raises(SourceMigrationGateUnavailable):
            assert_boundary_held(space.pk)
        with pytest.raises(SourceMigrationGateUnavailable):
            _exclusive_boundary_connection(space.pk)
    with pytest.raises(SourceMigrationGateUnavailable):
        _exclusive_boundary_connection(space.pk)
