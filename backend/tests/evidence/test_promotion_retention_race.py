"""EVID-S04: real outside-DB PNG promotion survives an eligible retention scan."""
import queue
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection, connections
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup.models import DeploymentRecoveryState
from apps.evidence.models import EvidenceObjectRetentionState
from apps.evidence.services_retention import sweep_evidence_retention
from tests.checkout_lock_fixture_helpers import (
    finalized, quota, reviewed_issue, setup_lab, stock,
)
from tests.evidence.safety_retention_helpers import expiry_events, journal, metadata, photo
from tests.inventory_lending_helpers import submit_request
from tests.test_request_workflow import accept_url


pytestmark = pytest.mark.django_db(transaction=True)


def test_fresh_real_promotion_is_skipped_without_retention_blocker_then_issue_succeeds(
    monkeypatch, settings,
):
    assert connection.vendor == "postgresql", "Real PostgreSQL required; no environment skip"
    assert connection.get_autocommit() and not connection.in_atomic_block
    assert DeploymentRecoveryState.load().mode == DeploymentRecoveryState.Mode.NORMAL
    lab = setup_lab(monkeypatch, settings, "put", individual=True, total=1)
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    lab.now = timezone.now()
    request = submit_request(lab, quantity=1)
    response = lab.client.post(accept_url(request), {}, format="json")
    assert response.status_code == 200, response.data
    request.refresh_from_db()
    stock(lab, 0, 1, 0)
    evidence = photo(lab, days=40)
    before = metadata(evidence)
    reached, release = threading.Event(), threading.Event()
    connected, results = queue.Queue(), queue.Queue()
    real_copy = lab.store.copy_object
    worker_pid, captured = [], []
    tag = f"evidence-promotion-{uuid4().hex}"

    def paused_copy(**kwargs):
        assert kwargs["CopySource"]["Key"] == f"staging/{evidence.object_key}"
        assert not connection.in_atomic_block and connection.get_autocommit()
        # The actual validator has already HEADed/GETed and decoded staged PNG.
        assert any(call == "get" and args["Key"] == kwargs["CopySource"]["Key"]
                   for call, args in lab.store.calls)
        reached.set()
        assert release.wait(12), "Outside-DB promotion checkpoint was not released"
        return real_copy(**kwargs)

    monkeypatch.setattr(lab.store, "copy_object", paused_copy)

    def issue():
        announced = False
        try:
            close_old_connections()
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
                cursor.execute("SELECT set_config('application_name', %s, false)", [tag])
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.append(cursor.fetchone()[0])
            connected.put(None)
            announced = True

            def capture(execute, sql, params, many, context):
                captured.append((sql, params))
                return execute(sql, params, many, context)

            with connection.execute_wrapper(capture):
                results.put((reviewed_issue(lab, request, lab.qrs[0], evidence), None))
        except Exception as exc:
            results.put((None, exc))
            if not announced:
                connected.put(exc)
        finally:
            connections.close_all()

    worker = threading.Thread(target=issue, daemon=True)
    worker.start()
    try:
        error = connected.get(timeout=5)
        if error is not None:
            raise error
        assert reached.wait(5), "Actual issue did not reach PNG promotion"
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            assert cursor.fetchone()[0] != worker_pid[0]
        state = journal(evidence)
        assert state.status == "promoting" and state.claim_token is not None
        now = timezone.now()
        assert state.updated_at > now - timedelta(seconds=max(settings.EVIDENCE_URL_TTL_SECONDS, 60))
        summary = sweep_evidence_retention(now=now, batch_size=1)
        assert summary["photos_eligible"] == 1
        assert summary["photos_claimed"] == summary["photos_expired"] == summary["photos_failed"] == 0
        assert not EvidenceObjectRetentionState.objects.filter(evidence=evidence).exists()
        assert not expiry_events(evidence).exists()
        assert journal(evidence).status == "promoting"
        stock(lab, 0, 1, 0)
        quota(lab, 0)
    finally:
        release.set()
        worker.join(timeout=20)
        if worker.is_alive() and worker_pid:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE pid = %s AND application_name = %s", [worker_pid[0], tag],
                    )
            finally:
                worker.join(timeout=5)
        assert not worker.is_alive(), "Owned promotion worker leaked"
    response, error = results.get(timeout=1)
    if error is not None:
        raise error  # never accept a deadlock, timeout or business failure
    assert response.status_code == 200, response.data
    request.refresh_from_db()
    assert request.status == "issued" and request.issue_evidence_id == evidence.pk
    assert request.issued_by_id == lab.actor.pk
    stock(lab, 0, 0, 1)
    finalized(lab, evidence, charged=True)
    quota(lab, 1)
    assert captured and any("FOR NO KEY UPDATE" in sql for sql, _ in captured)
    issued = AuditLog.objects.get(action="request.issued", target_id=str(request.pk))
    attached = AuditLog.objects.get(action="evidence.attached", target_id=str(evidence.pk))
    assert issued.meta["evidence_id"] == evidence.pk and attached.meta["request_id"] == request.pk
    assert not EvidenceObjectRetentionState.objects.filter(evidence=evidence).exists()
    assert metadata(evidence) == before
