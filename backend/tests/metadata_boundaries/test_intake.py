"""Empty attachment sets retain validation, auditing and caller atomicity."""
from unittest.mock import Mock

import pytest
from django.db import transaction
from rest_framework.exceptions import ValidationError, NotFound

from apps.audit.models import AuditLog
from apps.evidence.storage import StorageUnavailable
from apps.machines import public_service_intake, service_storage
from apps.machines.models import MachineServiceRequest, ServiceQueue, ServiceRequestFile
from apps.makerspaces import limits
from tests.atomic_publication.domain import bind_store
from tests.machines.public_service_helpers import service_lab
from tests.metadata_boundaries.helpers import assert_caller_rollback, intake_case, no_storage, snapshot

pytestmark = pytest.mark.django_db
MODES = ("typed-generic", "typed-printer", "legacy-printer")


@pytest.mark.parametrize("mode", MODES)
def test_empty_files_submit_inside_outer_atomic_and_notify_only_after_commit(
    service_lab, mode, no_storage, monkeypatch, django_capture_on_commit_callbacks,
):
    case = intake_case(service_lab, mode)
    notify = Mock()
    monkeypatch.setattr("apps.machines.service_workflow_helpers.notify_service_status", notify)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with transaction.atomic():
            row = case.invoke()
            assert row.queue_id == case.queue.pk and row.member_id == case.actor.pk
            assert row.requester_name == case.actor.display_name
            assert row.contact_email == case.actor.email and row.contact_phone == case.actor.phone
            assert row.status == "pending" and row.title == "Enclosure"
            assert row.capability_payload == ({} if mode == "typed-generic" else {
                "requested_material": case.kind.capability_config["accepted_materials"][0],
                "requested_color": case.kind.capability_config["accepted_colours"][0],
                "quantity": 1, "project_brief": "", "no_filament_preference": True,
            })
            assert not ServiceRequestFile.objects.filter(service_request=row).exists()
            assert AuditLog.objects.filter(makerspace=case.space, action="machine_service.submitted", target_id=str(row.pk)).count() == 1
            notify.assert_not_called()
    assert len(callbacks) == 1
    assert notify.call_count == 1 and notify.call_args.args[1] == "submitted"


@pytest.mark.parametrize("mode", MODES)
def test_empty_files_caller_rollback_removes_request_queue_audit_and_notification(
    service_lab, mode, no_storage, django_capture_on_commit_callbacks,
):
    case = intake_case(service_lab, mode, queue=mode == "legacy-printer")
    before_queues = ServiceQueue.objects.filter(makerspace=case.space).count()
    def check(row):
        assert MachineServiceRequest.objects.filter(pk=row.pk).exists()
        assert ServiceQueue.objects.filter(makerspace=case.space).count() == before_queues + (mode != "legacy-printer")
        assert AuditLog.objects.filter(makerspace=case.space, action="machine_service.submitted").exists()
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert_caller_rollback(case.space, case.invoke, check)
    assert callbacks == []


@pytest.mark.parametrize("mode", MODES)
def test_nonempty_ids_refuse_caller_atomic_before_any_preparation(service_lab, mode, no_storage):
    case = intake_case(service_lab, mode)
    file = ServiceRequestFile.objects.create(
        makerspace=case.space, queue=case.queue, kind="attachment" if mode == "typed-generic" else "model",
        object_key=f"machine/{case.space.pk}/queue-{case.queue.pk}/service/original",
        owner_user_id=case.actor.pk, original_filename="part.pdf" if mode == "typed-generic" else "part.stl",
        content_type="application/pdf" if mode == "typed-generic" else "application/octet-stream",
        file_policy_name="documents" if mode == "typed-generic" else "printer", file_policy_version=1,
    )
    case.data["file_ids"] = [file.pk]
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(StorageUnavailable):
        case.invoke()
    assert snapshot(case.space) == original


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("invalid", ["inactive-queue", "pii-fence", "quota"])
def test_metadata_branch_keeps_locked_queue_pii_and_quota_checks(service_lab, mode, invalid, no_storage, monkeypatch):
    case = intake_case(service_lab, mode)
    if invalid == "inactive-queue":
        case.queue.is_active = False
        case.queue.save(update_fields=["is_active"])
        from apps.machines.public_service_queue import PublicServiceQueueConflict
        from apps.machines.service_errors import ServiceMachineUnavailable
        expected = (ValidationError, PublicServiceQueueConflict, ServiceMachineUnavailable)
    elif invalid == "pii-fence":
        from apps.encryption.models import PiiMakerspaceWriteFence
        from apps.encryption.write_fence import close_makerspace, PiiWriteFenced
        close_makerspace(case.space.pk, PiiMakerspaceWriteFence.OperationKind.DECRYPT_ROLLBACK, case.actor.pk)
        expected = PiiWriteFenced
    else:
        monkeypatch.setattr(limits, "is_self_host", lambda: False)
        case.space.resource_limit_overrides = {"machine_service_open": 0}
        case.space.save(update_fields=["resource_limit_overrides"])
        expected = ValidationError
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(expected):
        case.invoke()
    assert snapshot(case.space) == original


@pytest.mark.parametrize("mode", MODES)
def test_module_off_still_rejects_empty_files(service_lab, mode, no_storage):
    case = intake_case(service_lab, mode)
    case.space.enabled_modules = [key for key in case.space.enabled_modules if key != ("machine_service" if mode == "typed-generic" else "printing")]
    case.space.save(update_fields=["enabled_modules"])
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises((NotFound, ValidationError)):
        case.invoke()
    assert snapshot(case.space) == original


def test_generic_still_rejects_printer_fields_without_creating_queue(service_lab, no_storage):
    case = intake_case(service_lab, "typed-generic", queue=False)
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(ValidationError, match="Printer fields"):
        public_service_intake.submit_typed_request(case.space, case.data, case.actor, supplied_printer_fields=("material",))
    assert snapshot(case.space) == original


@pytest.mark.parametrize("mode", ["typed-printer", "legacy-printer"])
def test_printer_consumable_ownership_and_payload_validation_survive_empty_files(service_lab, mode, no_storage):
    case = intake_case(service_lab, mode)
    case.data["consumable_pool_id"] = 2147000000
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(ValidationError, match="consumable"):
        case.invoke()
    assert snapshot(case.space) == original


@pytest.mark.parametrize("mode", ["typed-printer", "legacy-printer"])
@pytest.mark.parametrize("invalid", [{"quantity": 0}, {"material": "Not an accepted material"}])
def test_empty_files_preserve_printer_payload_validation(service_lab, mode, invalid, no_storage):
    from apps.machines.service_errors import ServiceConsumptionInvalid

    case = intake_case(service_lab, mode)
    case.data.update(invalid)
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(ServiceConsumptionInvalid):
        case.invoke()
    assert snapshot(case.space) == original


@pytest.mark.parametrize("mode", ["typed-printer", "legacy-printer"])
def test_empty_files_keep_selected_consumable_payload_without_debiting_stock(service_lab, mode, no_storage):
    from apps.machines.models import MachineConsumablePool

    case = intake_case(service_lab, mode)
    pool = MachineConsumablePool.objects.create(
        makerspace=case.space, machine_type=case.kind, is_public=True,
        material=case.kind.capability_config["accepted_materials"][0],
        color=case.kind.capability_config["accepted_colours"][0],
        initial_grams=500, remaining_grams=500,
    )
    case.data.update(consumable_pool_id=pool.pk, quantity=2, project_brief="Enclosure")
    with transaction.atomic():
        row = case.invoke()
        assert row.capability_payload["requested_consumable_pool"] == pool.pk
        assert row.capability_payload["quantity"] == 2 and row.capability_payload["project_brief"] == "Enclosure"
        pool.refresh_from_db()
        assert pool.remaining_grams == 500


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("invalid", ["foreign-owner", "other-queue", "already-used"])
def test_nonempty_attachment_ownership_and_queue_preflight_remains_complete(service_lab, mode, invalid, monkeypatch):
    case = intake_case(service_lab, mode)
    store = bind_store(monkeypatch, service_storage)
    queue = case.queue
    if invalid == "other-queue":
        queue = ServiceQueue.objects.create(makerspace=case.space, machine_type=case.kind, name="Other queue")
    file = ServiceRequestFile.objects.create(
        makerspace=case.space, queue=queue, kind="attachment" if mode == "typed-generic" else "model",
        owner_user_id=case.actor.pk + 10000 if invalid == "foreign-owner" else case.actor.pk,
        object_key=f"machine/{case.space.pk}/queue-{queue.pk}/service/invalid",
        original_filename="part.pdf" if mode == "typed-generic" else "part.stl",
        content_type="application/pdf" if mode == "typed-generic" else "application/octet-stream",
        file_policy_name="documents" if mode == "typed-generic" else "printer", file_policy_version=1,
    )
    if invalid == "already-used":
        from django.utils import timezone
        ServiceRequestFile.objects.filter(pk=file.pk).update(attached_at=timezone.now())
    payload, mime = ((b"%PDF-1.7\npart", "application/pdf") if mode == "typed-generic" else
                     (b"solid cube\nendsolid cube", "application/octet-stream"))
    store.seed(service_storage.staging_key(file.object_key), payload, mime)
    case.data["file_ids"] = [file.pk]
    original = snapshot(case.space)
    with pytest.raises(ValidationError):
        case.invoke()
    assert snapshot(case.space) == original
    # The legacy route validates queue membership under the locked recheck after
    # preparation; it must still reject the row and leave accounting untouched.
    if invalid != "other-queue" or mode != "legacy-printer":
        assert store.calls == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", MODES)
def test_preflight_payload_mutation_cannot_replace_snapshotted_attachment_ids(service_lab, mode, monkeypatch):
    # Real guard and versioned provider, with mutation at an honest read-only
    # preflight seam. The file finalizer must still select exactly the first ID.
    case = intake_case(service_lab, mode)
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    case.space.resource_limit_overrides = {"storage": 100000}
    case.space.save(update_fields=["resource_limit_overrides"])
    store = bind_store(monkeypatch, service_storage)
    data, mime, filename = ((b"%PDF-1.7\npart", "application/pdf", "part.pdf") if mode == "typed-generic" else
                            (b"solid cube\nendsolid cube", "application/octet-stream", "part.stl"))
    files = []
    for index in range(2):
        file = ServiceRequestFile.objects.create(
            makerspace=case.space, queue=case.queue, kind="attachment" if mode == "typed-generic" else "model",
            owner_user_id=case.actor.pk, object_key=f"machine/{case.space.pk}/queue-{case.queue.pk}/service/{index}",
            original_filename=filename, content_type=mime,
            file_policy_name="documents" if mode == "typed-generic" else "printer", file_policy_version=1,
        )
        store.seed(service_storage.staging_key(file.object_key), data, mime)
        files.append(file)
    case.data["file_ids"] = [files[0].pk]
    if mode == "legacy-printer":
        from apps.machines import public_printer_service as module
        name = "resolve_queue"
    else:
        module, name = public_service_intake, "validate_requested_queue"
    original = getattr(module, name)
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        case.data["file_ids"][:] = [files[1].pk]
        return result
    monkeypatch.setattr(module, name, mutate)
    row = case.invoke()
    files[0].refresh_from_db(); files[1].refresh_from_db(); case.space.refresh_from_db()
    assert files[0].service_request_id == row.pk
    assert files[1].service_request_id is None and files[1].attached_at is None
    assert files[0].object_key in store.objects and files[1].object_key not in store.objects
    assert case.space.storage_bytes_used == len(data)
    assert list(AuditLog.objects.filter(makerspace=case.space, action="machine_service.file_attached").values_list("target_id", flat=True)) == [str(files[0].pk)]
