"""Maintenance preparation and manual/log namespace contention."""
from threading import Event

import pytest
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.machines import services, storage as manual_storage
from apps.machines.models import MachineDocument
from apps.maintenance import storage
from apps.maintenance.models import MaintenanceLog, MaintenanceLogDocument
from apps.maintenance.services_documents import finalize_log_document
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.atomic_publication.threading import workers

pytestmark = pytest.mark.django_db(transaction=True)


def test_maintenance_and_manual_cannot_both_claim_log_key(monkeypatch):
    space, actor, machine = setup_machine("atomic-manual-log", monkeypatch)
    log = MaintenanceLog.objects.create(machine=machine, summary="Calibration", performed_by=actor)
    key = storage.log_document_object_key(space.pk, machine.pk, "pdf")
    store = bind_store(monkeypatch, storage, manual_storage)
    data = b"%PDF-maintenance calibration"
    store.seed(storage.staging_key(key), data)
    preparing, proceed, manual_started, manual_done = Event(), Event(), Event(), Event()
    def pause(kwargs):
        preparing.set()
        assert proceed.wait(4)
    store.before_put = pause
    with workers() as spawn:
        first = spawn(lambda: finalize_log_document(log, actor=actor, object_key=key))
        assert preparing.wait(4)
        def manual():
            manual_started.set()
            try:
                with pytest.raises(ValidationError):
                    services.attach_document(machine, actor, key, "manual", "manual.pdf")
            finally:
                manual_done.set()
        second = spawn(manual)
        try:
            assert manual_started.wait(3)
            assert not manual_done.wait(0.15)
        finally:
            proceed.set()
        first.result(timeout=8)
        second.result(timeout=8)
    assert MaintenanceLogDocument.objects.filter(log=log, object_key=key).count() == 1
    assert not MachineDocument.objects.filter(object_key=key).exists()
    space.refresh_from_db()
    assert space.storage_bytes_used == len(data) and store.objects[key][0] == data
    assert AuditLog.objects.filter(makerspace=space, action="maintenance.document_added").count() == 1


def test_retained_manual_claim_prevents_maintenance_publication(monkeypatch):
    space, actor, machine = setup_machine("atomic-retained-manual", monkeypatch)
    log = MaintenanceLog.objects.create(machine=machine, summary="Calibration", performed_by=actor)
    key = storage.log_document_object_key(space.pk, machine.pk, "pdf")
    MachineDocument.objects.create(machine=machine, doc_type="manual", object_key=key,
                                   original_filename="legacy.pdf", content_type="application/pdf", size_bytes=8)
    store = bind_store(monkeypatch, storage)
    with pytest.raises(ValidationError):
        finalize_log_document(log, actor=actor, object_key=key)
    assert store.calls == [] and not MaintenanceLogDocument.objects.filter(log=log).exists()
