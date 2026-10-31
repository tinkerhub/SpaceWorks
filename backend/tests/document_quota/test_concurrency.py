"""Real PG storage wait: distinct charged deletions serialize without lost credit."""
from threading import Event, Thread
from time import monotonic

import pytest
from django.db import close_old_connections, connection, connections
from django.urls import reverse

from tests.document_safety.helpers import assert_storage_boundary, cap, jwt_client, lab, usage
from tests.document_quota.helpers import KINDS, releases, upload

pytestmark = pytest.mark.django_db(transaction=True)


def observed_storage_wait(tenant):
    deadline = monotonic() + 8
    last = []
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pid, granted, pg_blocking_pids(pid) FROM pg_locks "
                "WHERE locktype='advisory' AND classid=734312 AND objid=%s "
                "AND objsubid=2 AND mode='ExclusiveLock'", [tenant],
            )
            last = cursor.fetchall()
        granted = {pid for pid, held, _ in last if held}
        if any(not held and granted.intersection(blockers) for _, held, blockers in last):
            return last
        Event().wait(0.01)
    raise AssertionError(f"No actual storage-lock blocking edge: {last}")


@pytest.mark.parametrize("kind", KINDS)
def test_two_distinct_charged_deletes_wait_before_row_locks_and_preserve_unrelated_usage(
    kind, monkeypatch, settings,
):
    assert connection.vendor == "postgresql"
    assert connection.get_autocommit() and not connection.in_atomic_block
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    first, first_charge, first_body = upload(case)
    second, second_charge, second_body = upload(case, variant=True)
    entered, release = Event(), Event()
    outcomes, queries, pids = {}, {"first": [], "second": []}, {}
    threads = []
    case.store.boundary = lambda: assert_storage_boundary(case)

    def pause_at_delete(kwargs):
        if any(row["Key"] == first.object_key for row in kwargs["Delete"]["Objects"]):
            assert not connection.in_atomic_block
            entered.set()
            assert release.wait(12), "Parent did not release provider boundary"
    case.store.before_delete = pause_at_delete

    def run(name, row):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='10s'")
                cursor.execute("SET statement_timeout='15s'")
                cursor.execute("SELECT pg_backend_pid()")
                pids[name] = cursor.fetchone()[0]
            def capture(execute, sql, params, many, context):
                queries[name].append(sql)
                return execute(sql, params, many, context)
            with connection.execute_wrapper(capture):
                response = jwt_client(case.actor).delete(
                    reverse(f"{case.prefix}-detail", kwargs={"pk": row.pk}),
                )
            outcomes[name] = response
        except BaseException as exc:
            outcomes[name] = exc
        finally:
            connections.close_all()

    def start(name, row):
        worker = Thread(target=run, args=(name, row), daemon=True)
        threads.append(worker)
        worker.start()

    try:
        start("first", first)
        assert entered.wait(8), "First delete never reached actual provider I/O"
        assert not case.model.objects.filter(pk=first.pk).exists()
        assert usage(case) == 900 + len(first_body) + len(second_body)
        start("second", second)
        wait = observed_storage_wait(case.home.pk)
        assert any(not held for _, held, _ in wait)
        assert pids["first"] != pids["second"]
        assert not any("FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql for sql in queries["second"])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                "AND classid=734310 AND objid=%s AND objsubid=2 "
                "AND mode='ShareLock' AND granted", [case.home.pk],
            )
            assert cursor.fetchone()[0] >= 2  # Both entered source before storage.
        assert case.model.objects.filter(pk=second.pk).exists()
        assert case.store.objects[second.object_key][0] == second_body
    finally:
        release.set()
        for worker in threads:
            worker.join(timeout=20)
        assert all(not worker.is_alive() for worker in threads), "Owned PG worker leaked"
    assert set(outcomes) == {"first", "second"}
    for response in outcomes.values():
        if isinstance(response, BaseException):
            raise response
        assert response.status_code == 204
    assert usage(case) == 900 and releases(case).count() == 2
    assert set(releases(case).values_list("target_id", flat=True)) == {str(first.pk), str(second.pk)}
    assert {row.meta["charge_event_uuid"] for row in releases(case)} == {
        str(first_charge.event_uuid), str(second_charge.event_uuid),
    }
    assert not case.store.versions.get(first.object_key)
    assert not case.store.versions.get(second.object_key)
