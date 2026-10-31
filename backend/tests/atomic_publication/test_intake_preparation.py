"""Multi-file preparation precedes SQL locks; metadata remains all-or-nothing."""
import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.machines import public_printer_service, public_service_intake, service_storage
from apps.machines.models import MachineServiceRequest, ServiceQueue, ServiceRequestFile
from apps.makerspaces import limits
from tests.atomic_publication.domain import bind_store
from tests.machines.public_service_helpers import service_lab

pytestmark = pytest.mark.django_db(transaction=True)


def intake_case(service_lab, mode, monkeypatch):
    space, actor, _client, generic, printer = service_lab
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    kind = generic if mode == "typed-generic" else printer
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=kind, name="Public Requests")
    uploads = []
    payload, mime, filename, policy = (b"%PDF-1.7\nattachment", "application/pdf", "file.pdf", "documents") if kind == generic else (
        b"solid cube\nendsolid cube", "application/octet-stream", "part.stl", "printer")
    store = bind_store(monkeypatch, service_storage)
    for index in range(2):
        file = ServiceRequestFile.objects.create(
            makerspace=space, queue=queue, kind="attachment" if kind == generic else "model",
            object_key=f"machine/{space.pk}/queue-{queue.pk}/service/{index}",
            original_filename=filename, content_type=mime, owner_user_id=actor.pk,
            file_policy_name=policy, file_policy_version=1,
        )
        store.seed(service_storage.staging_key(file.object_key), payload, mime)
        uploads.append(file)
    data = {"machine_type_id": kind.pk, "queue_id": queue.pk,
            "title": "Enclosure", "file_ids": [file.pk for file in uploads]}
    invoke = (lambda: public_printer_service.submit_request(space, data, actor)) if mode == "legacy-printer" else (
        lambda: public_service_intake.submit_typed_request(space, data, actor))
    return space, actor, queue, uploads, store, payload, mime, invoke


@pytest.mark.parametrize("mode", ["typed-generic", "typed-printer", "legacy-printer"])
def test_valid_multifile_intake_has_no_s3_under_application_atomic(service_lab, mode, monkeypatch):
    space, _actor, _queue, files, store, data, _mime, invoke = intake_case(service_lab, mode, monkeypatch)
    row = invoke()
    assert MachineServiceRequest.objects.filter(makerspace=space).count() == 1
    for file in files:
        file.refresh_from_db()
        assert file.service_request_id == row.pk and file.size_bytes == len(data)
        assert store.objects[file.object_key][0] == data
    space.refresh_from_db()
    assert space.storage_bytes_used == 2 * len(data)
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.file_attached").count() == 2
    assert len(store.put_bodies) == 2


@pytest.mark.parametrize("mode,invalid", [
    pytest.param(mode, invalid, id=f"{mode}-{invalid}")
    for mode in ("typed-generic", "typed-printer", "legacy-printer")
    for invalid in ("missing", "ownership-changed")
])
def test_invalid_pending_set_rejected_before_preparation(service_lab, mode, invalid, monkeypatch):
    space, actor, _queue, files, store, data, _mime, invoke = intake_case(service_lab, mode, monkeypatch)
    staging_key = service_storage.staging_key(files[0].object_key)
    original_staging = store.objects[staging_key]
    second = ServiceRequestFile.objects.filter(pk=files[1].pk)
    if invalid == "missing":
        second.delete()
    else:
        second.update(owner_user_id=actor.pk + 10000)
    pending = ServiceRequestFile.objects.filter(pk__in=[file.pk for file in files]).order_by("pk")
    fields = ("pk", "service_request_id", "attached_at", "size_bytes")
    original_metadata = list(pending.values_list(*fields))

    with pytest.raises(ValidationError):
        invoke()

    assert store.calls == []
    assert files[0].object_key not in store.objects
    assert store.objects[staging_key] == original_staging
    assert store.objects[staging_key][0] == data
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
    assert list(pending.values_list(*fields)) == original_metadata
    space.refresh_from_db()
    assert space.storage_bytes_used == 0
    assert not AuditLog.objects.filter(makerspace=space, action="machine_service.file_attached").exists()


@pytest.mark.parametrize("mode", ["typed-generic", "typed-printer", "legacy-printer"])
@pytest.mark.parametrize("failure", ["invalid-second", "ownership-changed"])
def test_multifile_failure_leaves_no_request_attachment_charge_or_attach_audit(service_lab, mode, failure, monkeypatch):
    space, actor, _queue, files, store, _data, mime, invoke = intake_case(service_lab, mode, monkeypatch)
    if failure == "invalid-second":
        # Printer STL admits plain maker text, so a disguised PDF is used rather
        # than treating arbitrary STL text as invalid.
        bad = b"%PDF-disguised" if mode != "typed-generic" else b"not PDF"
        store.seed(service_storage.staging_key(files[1].object_key), bad, mime)
    else:
        def mutate_owner(kwargs):
            if kwargs["Key"] == files[1].object_key and files[1].object_key in store.objects:
                ServiceRequestFile.objects.filter(pk=files[0].pk).update(owner_user_id=actor.pk + 10000)
        store.before_get = mutate_owner
    before = AuditLog.objects.filter(makerspace=space).count()
    with pytest.raises(ValidationError):
        invoke()
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
    assert not ServiceRequestFile.objects.filter(pk__in=[f.pk for f in files], attached_at__isnull=False).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 0
    assert AuditLog.objects.filter(makerspace=space).count() == before
    assert files[0].object_key in store.objects, "unknown ownership must not trigger final compensation"
