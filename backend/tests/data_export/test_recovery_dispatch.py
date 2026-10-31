import json

import pytest

from apps.data_export import lifecycle, services, storage
from apps.data_export.models import DataExportJob
from apps.makerspaces import limits
from tests.data_export.recovery_test_helpers import (
    events, make_job, manifest, recovery_case, usage,
)
from tests.data_export.test_api import client_for, list_url

pytestmark = pytest.mark.django_db(transaction=True)


def test_broker_failure_is_sanitized_503_and_releases_active_export_quota(
    recovery_case, monkeypatch, caplog,
):
    case = recovery_case
    secret = "amqp://private-user:SECRET-PASSWORD@broker.invalid/secret-vhost"

    def unavailable(_job_id):
        raise RuntimeError(secret)

    monkeypatch.setattr("apps.data_export.views.run_data_export_task.delay", unavailable)
    response = client_for(case.actor).post(
        list_url(case.space), {"fidelity": "REDACTED"}, format="json",
    )

    assert response.status_code == 503
    assert response.data["code"] == "export_dispatch_unavailable"
    job = DataExportJob.objects.get(pk=response.data["job_id"])
    assert job.status == DataExportJob.Status.FAILED
    assert job.failure_code == DataExportJob.FailureCode.INTERNAL_ERROR
    assert job.completed_at is not None
    assert job.accounted_size_bytes == usage(case) == 0
    assert not services.fail_dispatch(job)
    failed = events(job, "data_export.failed")
    assert failed.count() == 1
    disclosed = json.dumps({
        "response": response.data, "detail": job.failure_detail,
        "manifest": job.manifest, "audit": list(failed.values("meta")),
    }) + caplog.text
    assert secret not in disclosed
    assert "SECRET-PASSWORD" not in disclosed
    assert "RuntimeError" not in disclosed
    assert all(record.exc_info is None for record in caplog.records
               if record.name == "apps.data_export.views")
    assert limits._data_exports(case.space) == 0
    # A second real admission proves the failed row does not occupy the one-job cap.
    replacement = services.create_export_job(case.actor, case.space)
    assert replacement.status == DataExportJob.Status.PENDING


@pytest.mark.parametrize("completed", (False, True), ids=("claimed", "completed"))
def test_ambiguous_broker_reply_preserves_worker_state_bytes_and_charge(
    recovery_case, monkeypatch, completed,
):
    case = recovery_case
    objects = {}
    deleted = []
    expected = {}
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)

    def accepted_then_disconnected(job_id):
        claimed = lifecycle._claim_job(job_id)
        assert claimed is not None
        objects[claimed.object_key] = b"finished-archive"
        if completed:
            lifecycle._finalize_job(claimed.pk, manifest(), len(objects[claimed.object_key]))
        expected.update(DataExportJob.objects.filter(pk=job_id).values().get())
        raise RuntimeError("amqp://user:PRIVATE@broker.invalid")

    monkeypatch.setattr(
        "apps.data_export.views.run_data_export_task.delay", accepted_then_disconnected,
    )
    response = client_for(case.actor).post(list_url(case.space), {}, format="json")

    assert response.status_code == 503
    assert response.data["code"] == "export_dispatch_unavailable"
    job = DataExportJob.objects.get(pk=response.data["job_id"])
    assert DataExportJob.objects.filter(pk=job.pk).values().get() == expected
    assert job.status == (DataExportJob.Status.AVAILABLE if completed
                          else DataExportJob.Status.RUNNING)
    assert objects == {job.object_key: b"finished-archive"}
    assert deleted == []
    assert usage(case) == job.accounted_size_bytes == (16 if completed else 0)
    assert events(job, "data_export.failed").count() == 0
    assert events(job, "data_export.completed").count() == int(completed)


@pytest.mark.parametrize("worker_state", ("pending", "running", "available"))
def test_portable_pending_failure_snapshot_only_retires_an_unclaimed_job(
    recovery_case, monkeypatch, worker_state,
):
    case = recovery_case
    snapshot = make_job(case, fidelity="PORTABLE")
    deleted = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)
    if worker_state != "pending":
        lifecycle._claim_job(snapshot.pk)
    if worker_state == "available":
        lifecycle._finalize_job(snapshot.pk, manifest(), 23)
    before = DataExportJob.objects.filter(pk=snapshot.pk).values().get()

    services._fail_job(snapshot, DataExportJob.FailureCode.INTERNAL_ERROR, "broker failed")
    services._fail_job(snapshot, DataExportJob.FailureCode.INTERNAL_ERROR, "retry failed")

    job = DataExportJob.objects.get(pk=snapshot.pk)
    if worker_state == "pending":
        assert job.status == DataExportJob.Status.FAILED
        assert job.failure_code == DataExportJob.FailureCode.INTERNAL_ERROR
        assert events(job, "data_export.failed").count() == 1
        assert limits._data_exports(case.space) == 0
    else:
        assert DataExportJob.objects.filter(pk=job.pk).values().get() == before
        assert events(job, "data_export.failed").count() == 0
    assert usage(case) == job.accounted_size_bytes == (23 if worker_state == "available" else 0)
    assert deleted == []
