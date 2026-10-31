"""Deterministic clock and versioned byte store; all domain/lock code stays real."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from django.db import connection, connections
from django.utils import timezone

from apps.accounts.models import User
from apps.backup.models import DeploymentRecoveryState
from apps.makerspaces import purge_storage
from apps.makerspaces.models import Makerspace, PurgeReceipt
from apps.makerspaces.purge_intent import PurgePending, storage_origins
from apps.makerspaces.purge_object_closure import tenant_prefixes
from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE


class VersionedStore:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.failure = None
        self.on_list = None
        self.on_delete = None
        self.sequence = 0

    def put(self, bucket, key, payload=b"bytes", *, marker=False):
        self.sequence += 1
        identity = (bucket, key, str(self.sequence))
        self.objects[identity] = (payload, marker)
        return identity

    def list_object_versions(self, **params):
        assert not connection.in_atomic_block, "provider listing held an application transaction"
        self.calls.append(("list", params.copy()))
        if self.on_list:
            self.on_list(params)
        if self.failure == "listing":
            raise OSError("version listing unavailable")
        if self.failure == "unsupported":
            return {"Contents": []}
        page = {"IsTruncated": False, "Versions": [], "DeleteMarkers": []}
        for (bucket, key, version), (_, marker) in sorted(self.objects.items()):
            if bucket == params["Bucket"] and key.startswith(params["Prefix"]):
                page["DeleteMarkers" if marker else "Versions"].append(
                    {"Key": key, "VersionId": version},
                )
        return page

    def delete_objects(self, *, Bucket, Delete):
        assert not connection.in_atomic_block, "provider deletion held an application transaction"
        assert Delete["Quiet"] is False
        assert all(set(row) == {"Key", "VersionId"} for row in Delete["Objects"])
        self.calls.append(("delete", {"Bucket": Bucket, "Delete": Delete}))
        if self.on_delete:
            self.on_delete(Bucket, Delete)
        if self.failure == "storage":
            raise OSError("deletion unavailable")
        deleted = []
        for row in Delete["Objects"]:
            identity = (Bucket, row["Key"], row["VersionId"])
            if self.failure != "readback":
                self.objects.pop(identity, None)
            deleted.append(row.copy())
            if self.failure == "partial":
                return {"Deleted": deleted, "Errors": [{"Code": "AccessDenied"}]}
        if self.failure == "acknowledgement":
            return {"Deleted": []}
        return {"Deleted": deleted}

    @property
    def deletes(self):
        return [params for operation, params in self.calls if operation == "delete"]

    def has_key(self, bucket, key):
        return any(b == bucket and k == key for b, k, _ in self.objects)


@pytest.fixture
def purge_store(monkeypatch, settings, tmp_path):
    settings.BACKUP_OPS_DIR = str(tmp_path / "purge-operations" / "work")
    store = VersionedStore()
    monkeypatch.setattr(purge_storage, "client", lambda: store)
    return store


@pytest.fixture
def purge_clock(monkeypatch):
    clock = SimpleNamespace(now=timezone.now())
    monkeypatch.setattr(timezone, "now", lambda: clock.now)
    return clock


def actor(label="purge", **overrides):
    values = dict(role=User.Role.SUPERADMIN, is_superuser=True, is_staff=True, is_active=True,
                  access_status="active", must_change_password=False)
    values.update(overrides)
    return User.objects.create_user(username=label, email=f"{label}@example.test", **values)


def archived_space(slug="purge-space", **overrides):
    return Makerspace.objects.create(name=slug, slug=slug, archived_at=timezone.now(), **overrides)


def arm(space, user, clock):
    from apps.makerspaces.lifecycle_purge import purge

    with pytest.raises(PurgePending) as pending:
        purge(space, user)
    space.refresh_from_db()
    clock.now = pending.value.not_before
    return pending.value.not_before


def receipt(source_id=2147000001, *, keys=()):
    now = timezone.now()
    return PurgeReceipt.objects.create(
        source_makerspace_id=source_id, source_purge_started_at=now,
        graph_purged_at=now,
        auth_generation=DeploymentRecoveryState.objects.get(pk=1).auth_generation,
        storage_origins=storage_origins(), exact_keys=[list(key) for key in keys],
        namespace_prefixes=[[kind, prefix] for kind in ("private", "public_image")
                            for prefix in tenant_prefixes(source_id, kind)],
    )


@contextmanager
def advisory_lock(key, *, shared=False):
    """Separate real PostgreSQL connection; bounded try-locks never sleep."""
    db = connections["default"].copy()
    function = "pg_try_advisory_xact_lock_shared" if shared else "pg_try_advisory_xact_lock"
    try:
        db.set_autocommit(False)
        with db.cursor() as cursor:
            cursor.execute(f"SELECT {function}(%s, %s)", [SOURCE_GATE_LOCK_NAMESPACE, key])
            acquired = bool(cursor.fetchone()[0])
        yield acquired
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def bounded_source_wait(monkeypatch):
    from apps.tenant_migration import gate_locks

    original = gate_locks._new_lock_connection

    def bounded():
        db = original()
        db.autocommit = True
        with db.cursor() as cursor:
            cursor.execute("SET lock_timeout = '100ms'")
        return db

    monkeypatch.setattr(gate_locks, "_new_lock_connection", bounded)
