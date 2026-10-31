"""Bounded PostgreSQL observation, including a pre-domain provider checkpoint."""
import queue
import threading
import time
from uuid import uuid4

from django.db import close_old_connections, connection, connections

from apps.audit import services as audit
from tests.asset_fix_concurrency_helpers import _lock_edge, race


def pause_audit(monkeypatch, action, *, target_id=None):
    """Pause AFTER the real audit write, inside the winning domain transaction."""
    reached, release = threading.Event(), threading.Event()
    original = audit.record

    def record(actor, observed_action, **kwargs):
        result = original(actor, observed_action, **kwargs)
        if (observed_action == action and not reached.is_set()
                and (target_id is None or kwargs["target"].pk == target_id)):
            assert connection.in_atomic_block
            reached.set()
            assert release.wait(12), "Domain audit checkpoint was not released"
        return result

    monkeypatch.setattr(audit, "record", record)
    return reached, release


def prepared_race(first, second, reached, release, prepared, resume, *, table, clause):
    """Second validates real bytes first; observe its later DOMAIN lock wait.

    The ordinary race() is used elsewhere. Here second's real validator pauses
    after promotion has committed, before its domain transaction. This prevents
    accidentally proving only finalization's already-correct Evidence-first order.
    SQL correlation is exactly the existing root-owned observer's implementation.
    """
    assert connection.vendor == "postgresql", "Real PostgreSQL is required"
    assert connection.get_autocommit() and not connection.in_atomic_block
    connected = queue.Queue()
    outcomes, pids, tags, executing, workers = {}, {}, {}, {}, []
    token = uuid4().hex

    def run(name, operation):
        announced = False
        try:
            close_old_connections()
            tags[name] = f"checkout-lock-{token}-{name}"
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
                cursor.execute("SELECT set_config('application_name', %s, false)", [tags[name]])
                cursor.execute("SELECT pg_backend_pid()")
                pids[name] = cursor.fetchone()[0]
            connected.put((name, None))
            announced = True

            def capture(execute, sql, params, many, context):
                executing[name] = sql
                return execute(sql, params, many, context)

            with connection.execute_wrapper(capture):
                outcomes[name] = operation(), None
        except Exception as exc:
            outcomes[name] = None, exc
            if not announced:
                connected.put((name, exc))
        finally:
            connections.close_all()

    def start(name, operation):
        worker = threading.Thread(target=run, args=(name, operation), daemon=True)
        workers.append((name, worker))
        worker.start()
        announced, error = connected.get(timeout=5)
        assert announced == name
        if error is not None:
            raise error

    try:
        start("second", second)
        assert prepared.wait(5), "Second never completed real provider validation"
        start("first", first)
        assert reached.wait(5), "First never reached its domain lock checkpoint"
        assert pids["first"] != pids["second"]
        resume.set()
        query = _lock_edge(pids["second"], pids["first"], table, clause, executing)
    finally:
        # Both barriers are released even after observation/setup failure.
        resume.set()
        release.set()
        deadline = time.monotonic() + 20
        for _, worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        cleanup_errors = []
        for name, worker in workers:
            if worker.is_alive() and name in pids:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE pid = %s AND application_name = %s",
                            [pids[name], tags[name]],
                        )
                except Exception as exc:
                    cleanup_errors.append(exc)
                finally:
                    worker.join(timeout=5)
        assert all(not worker.is_alive() for _, worker in workers), "Owned race worker leaked"
        if cleanup_errors:
            raise cleanup_errors[0]

    assert set(outcomes) == {"first", "second"}
    for _, error in outcomes.values():
        if error is not None:
            raise error  # Never accept/retry a deadlock, timeout or worker exception.
    return outcomes["first"][0], outcomes["second"][0], pids, query


def prepare_validation(monkeypatch, module, *, label):
    """Always invoke the real validator and preserve its result/exceptions."""
    prepared, resume = threading.Event(), threading.Event()
    original = module.validate_evidence_upload

    def validate(evidence, **kwargs):
        result = original(evidence, **kwargs)
        if kwargs["label"] == label and not prepared.is_set():
            assert not connection.in_atomic_block, "Provider work must precede domain locks"
            prepared.set()
            assert resume.wait(12), "Provider checkpoint was not released"
        return result

    monkeypatch.setattr(module, "validate_evidence_upload", validate)
    return prepared, resume


def pause_attachment(monkeypatch, module, evidence_id):
    """Hold real attachment Evidence locks before the next Maker guard call."""
    reached, release = threading.Event(), threading.Event()
    original = module.lock_evidence_for_attachment

    def lock(pk, **kwargs):
        result = original(pk, **kwargs)
        if pk == evidence_id and not reached.is_set():
            assert result and connection.in_atomic_block
            reached.set()
            assert release.wait(12), "Attachment checkpoint was not released"
        return result

    monkeypatch.setattr(module, "lock_evidence_for_attachment", lock)
    return reached, release
