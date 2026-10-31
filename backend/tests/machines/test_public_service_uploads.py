"""Owned uploads pin the queue and finalize through the real storage validator."""
from io import BytesIO

from PIL import Image
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence.storage import StorageUnavailable
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue, ServiceRequestFile
from tests.machines.public_service_helpers import endpoint, object_io, post_request, service_lab
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db(transaction=True)


def png_bytes():
    buffer = BytesIO()
    Image.new("RGB", (1, 1), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


def stage(lab, machine_type=None, **changes):
    space, _, client, generic, _ = lab
    return client.post(endpoint(space, "upload"), {
        "machine_type_id": (machine_type or generic).pk, "filename": "drawing.pdf",
        "content_type": "application/pdf", "kind": "attachment", **changes,
    }, format="json")


@pytest.mark.parametrize("printer,kind,filename,mime,body", [
    (False, "attachment", "drawing.pdf", "application/pdf", b"%PDF-1.7\ncontent"),
    (True, "stl", "part.stl", "model/stl", b"solid bracket\nendsolid bracket"),
    (True, "screenshot", "estimate.png", "image/png", png_bytes()),
])
def test_uploaded_owned_file_finalizes_and_keeps_declared_policy_snapshot(service_lab, object_io, printer, kind, filename, mime, body):
    space, actor, _, generic, printer_type = service_lab
    objects, storage, _ = object_io
    selected = printer_type if printer else generic
    response = stage(service_lab, selected, kind=kind, filename=filename, content_type=mime)
    assert response.status_code == 201, response.data
    assert set(response.data) == {"queue_id", "file_id", "upload"}
    file = ServiceRequestFile.objects.get(pk=response.data["file_id"])
    assert file.owner_user_id == actor.pk and file.makerspace_id == space.pk
    assert file.machine_id is None and file.service_request_id is None and file.attached_at is None
    assert file.queue_id == response.data["queue_id"]
    assert file.file_policy_name == ("printer" if printer else "documents") and file.file_policy_version == 1
    objects[file.object_key] = (body, mime)
    result = post_request(service_lab, selected, queue_id=file.queue_id, file_ids=[file.pk])
    assert result.status_code == 201, result.data
    row = MachineServiceRequest.objects.get(public_token=result.data["public_token"])
    file.refresh_from_db()
    assert list(row.files.values_list("pk", flat=True)) == [file.pk]
    assert file.service_request_id == row.pk and file.attached_at is not None
    assert file.kind == {"stl": "model", "screenshot": "screenshot", "attachment": "attachment"}[kind]
    assert (file.original_filename, file.content_type, file.size_bytes) == (filename, mime, len(body))
    assert storage.get_object.call_count == 1  # existing final is snapshotted exactly once
    storage.put_object.assert_not_called()
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.file_attached", target_id=str(file.pk)).count() == 1
    with pytest.raises(RuntimeError, match="immutable"):
        file.original_filename = "replacement.pdf"
        file.save()


@pytest.mark.parametrize("printer,fields", [
    (False, {"filename": "evil.exe"}), (False, {"content_type": ""}),
    (False, {"content_type": "image/png"}), (False, {"kind": "stl"}),
    (True, {"kind": "stl", "filename": "evil.exe"}),
    (True, {"kind": "screenshot", "filename": "part.stl"}),
    (True, {"kind": "screenshot", "filename": "estimate.png", "content_type": ""}),
])
def test_invalid_upload_declaration_never_writes_or_calls_storage(service_lab, object_io, printer, fields):
    space, _, _, generic, printer_type = service_lab
    _, storage, public = object_io
    before = AuditLog.objects.count()
    response = stage(service_lab, printer_type if printer else generic, **fields)
    assert response.status_code == 400, response.data
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert not ServiceRequestFile.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before
    assert storage.mock_calls == public.mock_calls == []


def test_blank_model_mime_uses_printer_octet_stream_contract(service_lab, object_io):
    _, _, _, _, printer = service_lab
    response = stage(service_lab, printer, kind="stl", filename="part.stl", content_type="")
    assert response.status_code == 201, response.data
    assert ServiceRequestFile.objects.get(pk=response.data["file_id"]).content_type == "application/octet-stream"


def test_presign_failure_rolls_back_first_queue_file_and_audit(service_lab, object_io, monkeypatch):
    from apps.machines import service_storage
    before = AuditLog.objects.count()
    monkeypatch.setattr(service_storage, "presigned_upload", Mock(side_effect=StorageUnavailable()))
    response = stage(service_lab)
    assert response.status_code == 503, response.data
    assert not ServiceQueue.objects.exists() and not ServiceRequestFile.objects.exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize("explicit_pin", [False, True])
def test_upload_queue_is_recovered_even_after_active_queues_are_reordered(service_lab, object_io, explicit_pin):
    space, _, _, generic, _ = service_lab
    objects, _, _ = object_io
    staged = stage(service_lab)
    first = ServiceQueue.objects.get(pk=staged.data["queue_id"])
    first.name = "Z original upload queue"
    first.save(update_fields=["name"])
    second = ServiceQueue.objects.create(makerspace=space, machine_type=generic, name="A new default")
    again = stage(service_lab, queue_id=first.pk, filename="second.pdf")
    assert again.status_code == 201 and again.data["queue_id"] == first.pk
    ids = [staged.data["file_id"], again.data["file_id"]]
    for file in ServiceRequestFile.objects.filter(pk__in=ids):
        objects[file.object_key] = (b"%PDF-1.7\ndrawing", "application/pdf")
    kwargs = {"queue_id": first.pk} if explicit_pin else {}
    response = post_request(service_lab, file_ids=ids, **kwargs)
    assert response.status_code == 201, response.data
    row = MachineServiceRequest.objects.get(public_token=response.data["public_token"])
    assert row.queue_id == first.pk and row.queue_id != second.pk
    assert set(row.files.values_list("pk", flat=True)) == set(ids)


@pytest.mark.parametrize("invalid", ["other_owner", "foreign", "mixed", "consumed", "missing", "wrong_pin", "wrong_type", "inactive"])
def test_invalid_attachment_set_rejected_before_object_io(service_lab, object_io, invalid):
    space, actor, _, generic, _ = service_lab
    _, storage, public = object_io
    staged = stage(service_lab)
    file = ServiceRequestFile.objects.get(pk=staged.data["file_id"])
    ids, kwargs = [file.pk], {}
    if invalid == "other_owner":
        ServiceRequestFile.objects.filter(pk=file.pk).update(owner_user_id=actor.pk + 10000)
    elif invalid == "foreign":
        other = make_space("foreign-upload")
        foreign_type = MachineType.objects.create(makerspace=other, slug="foreign", name="Foreign")
        queue = ServiceQueue.objects.create(makerspace=other, machine_type=foreign_type, name="Foreign")
        ServiceRequestFile.objects.filter(pk=file.pk).update(makerspace=other, queue=queue)
    elif invalid in {"mixed", "wrong_pin"}:
        queue = ServiceQueue.objects.create(makerspace=space, machine_type=generic, name="Other queue")
        if invalid == "wrong_pin":
            kwargs["queue_id"] = queue.pk
        else:
            second = stage(service_lab, queue_id=queue.pk)
            ids.append(second.data["file_id"])
    elif invalid == "wrong_type":
        printer_file = stage(service_lab, service_lab[-1], kind="stl", filename="part.stl", content_type="model/stl")
        assert printer_file.status_code == 201
        ids = [printer_file.data["file_id"]]
    elif invalid == "consumed":
        assert post_request(service_lab).status_code == 201
        ServiceRequestFile.objects.filter(pk=file.pk).update(service_request=MachineServiceRequest.objects.get(), attached_at=timezone.now())
    elif invalid == "missing":
        ids.append(999999)
    else:
        ServiceQueue.objects.filter(pk=file.queue_id).update(is_active=False)
    before = (MachineServiceRequest.objects.count(), AuditLog.objects.count())
    storage.reset_mock()
    public.reset_mock()
    if invalid == "inactive":
        refused = stage(service_lab, queue_id=file.queue_id)
        assert refused.status_code == 409
    response = post_request(service_lab, file_ids=ids, **kwargs)
    assert response.status_code == (409 if invalid == "inactive" else 400), response.data
    assert (MachineServiceRequest.objects.count(), AuditLog.objects.count()) == before
    assert storage.mock_calls == public.mock_calls == []


def test_object_validation_failure_rolls_back_job_and_leaves_owned_upload_unattached(service_lab, object_io):
    objects, _, _ = object_io
    staged = stage(service_lab)
    file = ServiceRequestFile.objects.get(pk=staged.data["file_id"])
    objects[file.object_key] = (b"not a PDF", "application/pdf")
    before = AuditLog.objects.count()
    response = post_request(service_lab, file_ids=[file.pk])
    assert response.status_code == 400, response.data
    assert not MachineServiceRequest.objects.exists()
    file.refresh_from_db()
    assert file.attached_at is None and file.service_request_id is None
    assert AuditLog.objects.count() == before


def test_staged_policy_snapshot_survives_a_type_policy_change(service_lab, object_io, settings):
    _, _, _, generic, _ = service_lab
    staged = stage(service_lab)
    assert staged.status_code == 201
    file = ServiceRequestFile.objects.get(pk=staged.data["file_id"])
    assert file.file_policy_name == "documents"
    # Staff switch future uploads to another policy. This already-owned declaration
    # must still be finalized under the documents policy captured with its row.
    generic.capability_config = {"service_file_policy": {"name": "printer", "version": 1}}
    generic.save(update_fields=["capability_config"])
    settings.PRINT_ALLOWED_SCREENSHOT_EXT = ["png"]
    settings.PRINT_ALLOWED_SCREENSHOT_MIME = ["image/png"]
    object_io[0][file.object_key] = (b"%PDF-1.7\nplan", "application/pdf")
    response = post_request(service_lab, file_ids=[file.pk])
    assert response.status_code == 201, response.data
    file.refresh_from_db()
    assert file.file_policy_name == "documents" and file.file_policy_version == 1
    assert file.original_filename == "drawing.pdf" and file.content_type == "application/pdf"
    assert file.service_request_id == MachineServiceRequest.objects.get().pk


@pytest.mark.parametrize("gate", ["machines", "machine_service", "printing", "public_inventory_enabled"])
def test_upload_gates_run_before_queue_setup_or_storage(service_lab, object_io, gate):
    space, _, _, _, printer = service_lab
    if gate == "public_inventory_enabled":
        space.public_inventory_enabled = False
    else:
        space.enabled_modules.remove(gate)
        if gate == "machine_service":
            space.enabled_modules.remove("printing")
    space.save()
    response = stage(service_lab, printer, kind="stl", filename="part.stl", content_type="model/stl")
    assert response.status_code == 404, response.data
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert not ServiceRequestFile.objects.filter(makerspace=space).exists()
    assert object_io[1].mock_calls == object_io[2].mock_calls == []
