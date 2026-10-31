"""Independent accepted charges settle once; unaccepted/native bytes receive zero."""
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.backup.models import RestoreOperation, RestoreRollbackObject
from apps.events.models import EventAttendanceCertificate, EventFeedbackSurvey, EventFeedbackResponse, EventRegistration
from apps.machines.models import MachineServiceRequest, ServiceQueue, ServiceRequestFile
from apps.maintenance.models import MaintenanceLog, MaintenanceLogDocument
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import bucket_name
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from tests.backup.test_restore_services import restore_fixture
from tests.makerspaces.module_cleanup_support import (
    H, actor, event, module_space, module_store, rollback, seed_versions,
)
from tests.test_storage_reconciler_gaps import make_machine


@pytest.mark.django_db(transaction=True)
def test_same_source_two_rollback_copies_are_independently_charged_and_atomically_removed(module_store):
    space, user = module_space(storage_bytes_used=1000), actor()
    _, first = restore_fixture(stage=RestoreOperation.Stage.COMPLETED)
    # A second restore holds a distinct, separately charged physical copy.
    second = RestoreOperation.objects.create(archive=first.archive, kind=first.kind, stage=first.stage)
    key = f"event/{space.pk}/{H}.png"
    event(space, key)
    copies = [rollback(first, space, "events", "public_image", key, 17),
              rollback(second, space, "events", "public_image", key, 19)]
    for row in copies:
        seed_versions(module_store, "public_image", row.copy_key)
    seed_versions(module_store, "public_image", key)
    module_store.put(bucket_name("public_image"), key, b"original-accepted")
    module_store.failure = "storage"
    with pytest.raises(ValidationError):
        purge_module(space, "events", user)
    receipt = ModulePurgeReceipt.objects.get()
    assert sorted(row[3] for row in receipt.charge_obligations) == [17, 17, 19]
    assert RestoreRollbackObject.objects.filter(pk__in=[row.pk for row in copies]).count() == 2
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 1000
    module_store.failure = None
    retry_cleanup(receipt.pk, user)
    assert not RestoreRollbackObject.objects.filter(pk__in=[row.pk for row in copies]).exists()
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 947
    assert not module_store.objects
    retry_cleanup(receipt.pk, user)
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 947


@pytest.mark.django_db(transaction=True)
def test_native_procurement_receipts_delete_all_bytes_without_unproven_credit(module_store):
    space, user = module_space(storage_bytes_used=1000), actor()
    item = ToBuyItem.objects.create(makerspace=space, kind="hardware", name="Native receipt")
    key = f"procurement/{space.pk}/{item.pk}/receipts/{H}.pdf"
    row = ToBuyReceipt.objects.create(to_buy_item=item, object_key=key)
    seed_versions(module_store, "private", key, b"receipt")
    receipt, counts = purge_module(space, "procurement", user)
    assert counts and receipt.charge_obligations == []
    assert not ToBuyReceipt.objects.filter(pk=row.pk).exists() and not module_store.objects
    space.refresh_from_db()
    assert space.storage_bytes_used == 1000


@pytest.mark.django_db(transaction=True)
def test_maintenance_uses_recorded_accepted_size_without_head_or_version_multiplier(module_store):
    space, user = module_space(storage_bytes_used=1000), actor()
    machine = make_machine(space)
    log = MaintenanceLog.objects.create(machine=machine, summary="Maintenance")
    key = f"machines/{space.pk}/{machine.pk}/logs/{H}.step"
    row = MaintenanceLogDocument.objects.create(log=log, object_key=key, size_bytes=71)
    seed_versions(module_store, "private", key, b"different retained version sizes")
    receipt, _ = purge_module(space, "maintenance", user)
    assert receipt.charge_obligations == [[f"maintenance:{row.pk}", "private", key, 71]]
    assert not MaintenanceLog.objects.filter(pk=log.pk).exists()
    assert type(machine).objects.filter(pk=machine.pk).exists()
    assert not any(op == "head" for op, _ in module_store.calls)
    space.refresh_from_db()
    assert space.storage_bytes_used == 929


@pytest.mark.django_db(transaction=True)
def test_attached_service_files_credit_recorded_charge_but_unaccepted_staged_files_do_not(module_store):
    space, user = module_space(storage_bytes_used=1000), actor()
    machine = make_machine(space)
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=machine.machine_type, name="Service")
    request = MachineServiceRequest.objects.create(
        makerspace=space, queue=queue, assigned_machine=machine, requester=user, title="Service",
    )
    final = f"machine/{space.pk}/{machine.pk}/service/{H}"
    staged = f"machine/{space.pk}/{machine.pk}/service/{'b' * 32}"
    accepted = ServiceRequestFile.objects.create(makerspace=space, machine=machine, service_request=request,
                                                object_key=final, kind="attachment", owner_user_id=user.pk,
                                                attached_at=timezone.now(), size_bytes=61)
    unaccepted = ServiceRequestFile.objects.create(makerspace=space, machine=machine, object_key=staged,
                                                  kind="attachment", owner_user_id=user.pk, size_bytes=900)
    seeded = set()
    for key in (final, staged):
        seeded |= seed_versions(module_store, "private", key)
    receipt, _ = purge_module(space, "machine_service", user)
    assert receipt.charge_obligations == [[f"service:{accepted.pk}", "private", final, 61]]
    assert not ServiceRequestFile.objects.filter(pk__in=[accepted.pk, unaccepted.pk]).exists()
    assert not MachineServiceRequest.objects.filter(pk=request.pk).exists()
    assert not module_store.objects
    deleted = [(call["Bucket"], row["Key"], row["VersionId"])
               for call in module_store.deletes for row in call["Delete"]["Objects"]]
    assert set(deleted) == seeded and len(deleted) == len(seeded)
    space.refresh_from_db()
    assert space.storage_bytes_used == 939
    deletion_calls = list(module_store.deletes)
    retry_cleanup(receipt.pk, user)
    space.refresh_from_db()
    assert space.storage_bytes_used == 939 and not module_store.objects
    assert module_store.deletes == deletion_calls


@pytest.mark.django_db(transaction=True)
def test_revoked_rendered_certificates_remain_charged_until_module_graph_commit(module_store):
    space, user = module_space(storage_bytes_used=1000), actor()
    parent = event(space)
    registration = EventRegistration.objects.create(event=parent, name="Certificate owner", email="owner@example.test")
    survey = EventFeedbackSurvey.objects.create(event=parent, title="Feedback", questions=[{"id": "rating", "label": "Rating", "type": "number", "options": [], "required": True}], certificate_enabled=True)
    response = EventFeedbackResponse.objects.create(survey=survey, registration=registration,
                                                    certificate_requested=True, answers_snapshot="{}")
    serial = uuid4()
    key = f"event-certificates/{space.pk}/{serial}.pdf"
    certificate = EventAttendanceCertificate.objects.create(
        response=response, registration=registration, revision=1, serial=serial,
        recipient_name="Owner", event_title=parent.title, event_starts_at=parent.starts_at,
        event_ends_at=parent.ends_at, issuer_name=space.name, object_key=key,
        status="revoked", revoked_at=timezone.now(), revocation_reason="staff_revoked",
        rendered_at=timezone.now(), size_bytes=83, sha256="a" * 64,
    )
    seed_versions(module_store, "private", key)
    receipt, _ = purge_module(space, "events", user)
    assert receipt.charge_obligations == [[f"certificate:{certificate.pk}", "private", key, 83]]
    assert not EventAttendanceCertificate.objects.filter(pk=certificate.pk).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == 917 and not module_store.objects


@pytest.mark.django_db(transaction=True)
def test_final_failure_restores_rollback_rows_and_independent_charge_with_module_graph(module_store, monkeypatch):
    from apps.events.models import Event
    from apps.makerspaces import module_purge_receipts

    space, user = module_space(storage_bytes_used=100), actor()
    accepted = event(space)
    _, restore = restore_fixture(stage=RestoreOperation.Stage.COMPLETED)
    rb = rollback(restore, space, "events", "private", "legacy/exact-source", 13)
    seed_versions(module_store, "private", rb.copy_key)
    original = module_purge_receipts.settle

    def after_settle(*args, **kwargs):
        original(*args, **kwargs)
        assert not RestoreRollbackObject.objects.filter(pk=rb.pk).exists()
        assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 87
        raise RuntimeError("crash inside final graph transaction")

    with monkeypatch.context() as patch:
        patch.setattr(module_purge_receipts, "settle", after_settle)
        with pytest.raises(RuntimeError):
            purge_module(space, "events", user)
    receipt = ModulePurgeReceipt.objects.get()
    assert receipt.graph_purged_at is None and Event.objects.filter(pk=accepted.pk).exists()
    assert RestoreRollbackObject.objects.filter(pk=rb.pk).exists()
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 100
    retry_cleanup(receipt.pk, user)
    assert not RestoreRollbackObject.objects.filter(pk=rb.pk).exists()
    assert Makerspace.objects.get(pk=space.pk).storage_bytes_used == 87
