"""Local domain snapshots and hostile storage seams; tenant locks stay real."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.inventory.models import Category, InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MemberProfile, MemberProject
from tests.return_helpers import make_member, make_space


class CallerRollback(Exception):
    pass


@pytest.fixture
def no_storage(monkeypatch):
    """Do not replace storage_lifecycle or the independent source-gate connection."""
    targets = (
        "apps.object_storage_lifecycle._new_lock_connection",
        "apps.object_storage_lifecycle.StorageGuard.verify",
        "apps.inventory.public_image_storage._client",
        "apps.inventory.public_image_storage._public_client",
        "apps.inventory.public_image_storage.finalize_upload",
        "apps.inventory.public_image_storage.release_public_image_on_commit",
        "apps.machines.service_storage._client",
        "apps.machines.service_storage._public_client",
        "apps.machines.public_service_intake.prepare_files",
        "apps.machines.public_printer_service.prepare_files",
        "apps.machines.public_service_intake.finalize_file",
        "apps.machines.public_printer_service.finalize_file",
        "apps.admin_api.bulk_import_apply.finalize_product_image",
    )
    mocks = []
    for target in targets:
        mock = Mock(side_effect=AssertionError(f"Metadata touched storage: {target}"))
        monkeypatch.setattr(target, mock)
        mocks.append(mock)
    yield mocks
    # Some production failure paths catch exceptions. Checking calls also catches
    # accidentally swallowed provider assertions.
    for mock in mocks:
        mock.assert_not_called()


def snapshot(space):
    from apps.admin_api.models import BulkImportJob
    from apps.events.models import Event, EventRegistration, EventSeries
    from apps.machines.models import MachineConsumablePool, MachineServiceRequest, ServiceQueue, ServiceRequestFile

    queries = (
        Makerspace.objects.filter(pk=space.pk),
        MemberProfile.objects.filter(membership__makerspace=space),
        MemberProject.objects.filter(profile__membership__makerspace=space),
        InventoryProduct.objects.filter(makerspace=space),
        Category.objects.filter(makerspace=space),
        ServiceQueue.objects.filter(makerspace=space),
        MachineServiceRequest.objects.filter(makerspace=space),
        MachineConsumablePool.objects.filter(makerspace=space),
        ServiceRequestFile.objects.filter(makerspace=space),
        EventSeries.objects.filter(makerspace=space),
        Event.objects.filter(makerspace=space),
        EventRegistration.objects.filter(event__makerspace=space),
        BulkImportJob.objects.filter(makerspace=space),
        AuditLog.objects.all(),
    )
    return tuple(list(query.order_by("pk").values()) for query in queries)


def account_images(space, size=231):
    space.storage_bytes_used = size
    space.save(update_fields=["storage_bytes_used"])


def profile_case(slug="metadata-profile"):
    space = make_space(slug)
    actor = make_member(f"{slug}-member", space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=actor)
    profile = MemberProfile.objects.create(
        membership=membership, headline="Original", avatar_key=f"member/{space.pk}/avatar.png",
    )
    project = MemberProject.objects.create(
        profile=profile, title="Original project", image_key=f"member/{space.pk}/project.png",
    )
    account_images(space)
    return SimpleNamespace(space=space, actor=actor, membership=membership, profile=profile, project=project)


def bulk_case(slug="metadata-bulk"):
    space = make_space(slug)
    actor = make_member(f"{slug}-manager", space)
    product = InventoryProduct.objects.create(
        makerspace=space, name="Lamp", total_quantity=3, available_quantity=2,
        issued_quantity=1, image_key=f"items/{space.pk}/existing.png",
    )
    account_images(space)
    return SimpleNamespace(space=space, actor=actor, product=product)


def intake_case(lab, mode, *, queue=True):
    from apps.machines import public_printer_service, public_service_intake
    from apps.machines.models import ServiceQueue

    space, actor, _client, generic, printer = lab
    kind = generic if mode == "typed-generic" else printer
    target = ServiceQueue.objects.create(makerspace=space, machine_type=kind, name="Public Requests") if queue else None
    data = {"machine_type_id": kind.pk, "title": "Enclosure", "file_ids": []}
    if target:
        data["queue_id"] = target.pk
    def invoke():
        if mode == "legacy-printer":
            return public_printer_service.submit_request(space, data, actor)
        return public_service_intake.submit_typed_request(space, data, actor)
    return SimpleNamespace(space=space, actor=actor, kind=kind, queue=target, data=data, invoke=invoke)


def fence(space, actor, state):
    if state == "frozen":
        from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
        from tests.tenant_migration.source_gate_helpers import close_gate

        close_gate(space, actor)
        return SourceMigrationGateClosed
    if state == "not-restored":
        from apps.backup.not_restored import TenantNotRestored
        from tests.backup.test_not_restored_state_e7 import _component, _operation

        # A real active component is sufficient for the servability fence. Keep
        # the operation VERIFIED; never advance stages before installing facts.
        _component(_operation(makerspace_id=space.pk), space.pk)
        return TenantNotRestored
    if state == "purge-started":
        from apps.makerspaces.purge_intent import PurgeInProgress, commit_intent
        from tests.makerspaces.purge_test_support import actor as purge_actor

        space.archived_at = timezone.now()
        space.save(update_fields=["archived_at"])
        commit_intent(space.pk, purge_actor(f"metadata-purge-{space.pk}"), expected_slug=space.slug)
        space.refresh_from_db()
        assert space.purge_started_at is not None
        return PurgeInProgress
    raise AssertionError(state)


def assert_caller_rollback(space, write, check):
    original = snapshot(space)
    with pytest.raises(CallerRollback), transaction.atomic():
        value = write()
        check(value)
        raise CallerRollback
    assert snapshot(space) == original
