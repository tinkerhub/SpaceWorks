"""Explicit module cleanup fixtures: real locks/services, strict versioned provider."""
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from django.db import connection
from django.utils import timezone

from apps.backup.models import DeploymentRecoveryState, RestoreRollbackObject
from apps.events.models import Event
from apps.makerspaces import limits, purge_storage
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_purge_namespaces import clauses
from apps.makerspaces.purge_intent import storage_origins
from tests.makerspaces.purge_test_support import VersionedStore, actor

H = "a" * 32
U = "12345678-1234-4234-8234-123456789abc"


class ModuleStore(VersionedStore):
    def __init__(self):
        super().__init__()
        self.on_head = None

    def head_object(self, *, Bucket, Key):
        assert not connection.in_atomic_block, "HEAD held an application transaction"
        self.calls.append(("head", {"Bucket": Bucket, "Key": Key}))
        if self.on_head:
            self.on_head(Bucket, Key)
        if self.failure == "head":
            raise OSError("HEAD unavailable")
        rows = [(int(v), payload, marker) for (b, k, v), (payload, marker) in self.objects.items()
                if b == Bucket and k == Key]
        if rows:
            _, payload, marker = max(rows)
            if not marker:
                return {"ContentLength": len(payload)}
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")

    def delete_object(self, *, Bucket, Key, VersionId):
        assert not connection.in_atomic_block
        self.calls.append(("delete_version", {"Bucket": Bucket, "Key": Key, "VersionId": VersionId}))
        self.objects.pop((Bucket, Key, VersionId), None)
        return {"VersionId": VersionId}


@pytest.fixture
def module_store(monkeypatch, settings, tmp_path):
    settings.BACKUP_OPS_DIR = str(tmp_path / "module-cleanup-ops" / "work")
    settings.MANAGED_POSTGRES = True
    store = ModuleStore()
    monkeypatch.setattr(purge_storage, "client", lambda: store)
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    return store


def module_space(slug="module-cleanup", **values):
    return Makerspace.objects.create(name=slug, slug=slug, enabled_modules=[], **values)


def event(space, key=""):
    now = timezone.now()
    return Event.objects.create(makerspace=space, title="Retained until bytes verified",
                                starts_at=now, ends_at=now + timezone.timedelta(hours=1), image_key=key)


def module_receipt(space, module="events", *, completed=False, **values):
    now = timezone.now()
    fields = dict(source_makerspace_id=space.pk, source_public_code=space.public_code,
                  source_created_at=space.created_at, module_key=module,
                  auth_generation=DeploymentRecoveryState.objects.get(pk=1).auth_generation,
                  storage_origins=storage_origins(), exact_keys=[], namespace_clauses=clauses(module, space.pk),
                  holder_sites=[], charge_obligations=[], rollback_bindings=[], graph_digest="a" * 64,
                  intent_created_at=now)
    if completed:
        fields.update(graph_purged_at=now, last_attempt_at=now, last_verified_at=now)
    fields.update(values)
    return ModulePurgeReceipt.objects.create(**fields)


def privileged_restored_orphan_receipt():
    """Deliberate restored admission input; never constructed by the purge service."""
    from apps.makerspaces.module_purge_receipt_authority import validate_receipt

    source_id = 2147000001
    assert not Makerspace.objects.filter(pk=source_id).exists()
    incarnation = SimpleNamespace(pk=source_id, public_code="ORPH", created_at=timezone.now())
    row = module_receipt(incarnation, completed=True)
    validate_receipt(row)  # Valid frozen grammar/incarnation fields, but no live source.
    return row


def purge_archived_tenant(space, user, clock):
    """Use the supported full purge, including its real intent and handoff proof."""
    from apps.makerspaces.lifecycle_purge import purge
    from tests.makerspaces.purge_test_support import arm

    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    space.refresh_from_db()
    arm(space, user, clock)
    return purge(space, user)


def seed_versions(store, kind, key, payload=b"original"):
    bucket = purge_storage.bucket_name(kind)
    return {store.put(bucket, alias, data, marker=marker)
            for alias in (key, f"staging/{key}")
            for data, marker in ((b"older", False), (payload, False), (b"", True))}


def rollback(restore, space, module, kind, key, size=7):
    return RestoreRollbackObject.objects.create(
        restore=restore, makerspace=space, module_key=module, bucket_kind=kind,
        source_key=key, copy_key=f"rollback/{restore.pk}/{kind}/{key}", size_bytes=size,
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )


def purged_event_case(store, *, slug="module-event", size=4096):
    space, user = module_space(slug, storage_bytes_used=10000), actor(slug)
    key = f"event/{space.pk}/{H}.png"
    row = event(space, key)
    store.put(purge_storage.bucket_name("public_image"), key, b"x" * size)
    return space, user, row, key


def delete_historical_context(space, module, pattern):
    """An admitted presign can outlive its actual context row before cleanup starts."""
    context_id = 987654321
    if module == "bookings":
        from apps.bookings.models import BookableSpace
        row = BookableSpace.objects.create(makerspace=space, name="Deleted historical room")
    elif module == "procurement":
        from apps.procurement.models import ToBuyItem
        row = ToBuyItem.objects.create(pk=context_id, makerspace=space, kind="hardware", name="Deleted purchase")
    elif module in {"maintenance", "machine_service"}:
        from apps.machines.models import Machine, MachineType, ServiceQueue
        kind = MachineType.objects.create(makerspace=space, name="Historical context", slug="historical")
        if "queue-" in pattern:
            row = ServiceQueue.objects.create(pk=context_id, makerspace=space, machine_type=kind, name="Deleted queue")
        else:
            row = Machine.objects.create(pk=context_id, makerspace=space, machine_type=kind, name="Deleted machine")
    else:
        return
    model, pk = type(row), row.pk
    assert model.objects.filter(pk=pk).exists()
    row.delete()
    assert not model.objects.filter(pk=pk).exists()
    return pk
