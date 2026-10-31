from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.maintenance import services
from apps.maintenance.models import MaintenanceLog, MaintenanceLogDocument
from tests.maintenance.helpers import make_machine_setup


pytestmark = pytest.mark.django_db(transaction=True)


def test_finalize_and_delete_charge_exact_validated_size(monkeypatch):
    _, manager, machine, _ = make_machine_setup("maintenance-accounting")
    log = MaintenanceLog.objects.create(
        machine=machine, performed_by=manager, summary="Ready",
    )
    key = f"machines/{machine.makerspace_id}/{machine.id}/logs/file.pdf"
    add_storage = Mock()
    free_storage = Mock()
    delete_object = Mock(return_value=True)
    monkeypatch.setattr(
        "apps.maintenance.storage.prepare_upload",
        lambda key: SimpleNamespace(size=321, content_type="application/pdf"),
    )
    monkeypatch.setattr("apps.maintenance.storage.delete_object", delete_object)
    monkeypatch.setattr("apps.maintenance.storage.cleanup_upload", Mock())
    monkeypatch.setattr("apps.maintenance.services_documents.limits.add_storage", add_storage)
    monkeypatch.setattr("apps.maintenance.services_documents.limits.free_storage", free_storage)

    document = services.finalize_log_document(
        log, actor=manager, object_key=key,
    )
    assert document.size_bytes == 321
    add_storage.assert_called_once_with(machine.makerspace, 321)

    services.delete_log_document(document, actor=manager)
    free_storage.assert_called_once_with(machine.makerspace, 321)
    delete_object.assert_called_once_with(key)
    assert MaintenanceLog.objects.filter(pk=log.pk).exists()
    assert not MaintenanceLogDocument.objects.filter(pk=document.pk).exists()


def test_quota_failure_retains_prepared_final_and_creates_no_metadata(monkeypatch):
    _, manager, machine, _ = make_machine_setup("maintenance-quota")
    log = MaintenanceLog.objects.create(machine=machine, summary="Ready")
    key = f"machines/{machine.makerspace_id}/{machine.id}/logs/file.pdf"
    from apps.maintenance import storage
    from tests.atomic_publication.store import Store
    store = Store()
    store.seed(storage.staging_key(key), b"%PDF-ready", "application/pdf")
    monkeypatch.setattr(storage, "_client", lambda: store)
    monkeypatch.setattr(
        "apps.maintenance.services_documents.limits.add_storage",
        Mock(side_effect=ValidationError({"limit": "full"})),
    )
    with pytest.raises(ValidationError):
        services.finalize_log_document(log, actor=manager, object_key=key)
    assert store.objects[key][0] == b"%PDF-ready"
    assert not MaintenanceLogDocument.objects.exists()
