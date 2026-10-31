"""Committed domain fixtures and bounded, independently connected PG observers."""
from io import StringIO
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection, connections
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.admin_api.views_makerspace_images import (
    MakerspaceCoverImageView, MakerspaceLogoImageView,
)
from apps.backup.models import DeploymentRecoveryState
from apps.inventory import public_image_storage as storage
from apps.makerspaces.models import Makerspace
from apps.tenant_migration import gate_locks
from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE as NS
from tests.atomic_publication.store import Store, png
from tests.tenant_migration.source_gate_helpers import make_actor, make_space

WAIT = 8


def sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchall() if cursor.description else None


def locks(key):
    return sql("""SELECT pid, mode, granted, objsubid, pg_blocking_pids(pid)
                  FROM pg_locks WHERE locktype = 'advisory'
                  AND classid = %s AND objid = %s AND database = (SELECT oid
                  FROM pg_database WHERE datname = current_database())""", [NS, key])


def await_lock(key, mode, *, granted, blocker=None):
    deadline = monotonic() + WAIT
    while monotonic() < deadline:
        for row in locks(key):
            if row[1:4] == (mode, granted, 2) and (blocker is None or blocker in row[4]):
                return row[0]
        Event().wait(0.02)
    pytest.fail(f"No real {mode} granted={granted} key={key}, blocker={blocker}: {locks(key)}")


def counter(space):
    return Makerspace.objects.get(pk=space.pk).storage_bytes_used


def recompute(space, output=None):
    output = output if output is not None else StringIO()
    call_command("recompute_storage", space.slug, stdout=output)
    return output.getvalue()


def image_request(space, actor, *, field="logo_key", key=None):
    factory = APIRequestFactory()
    request = (factory.delete("/api/v1/admin/makerspaces/image") if key is None else
               factory.put("/api/v1/admin/makerspaces/image", {"object_key": key}, format="json"))
    force_authenticate(request, user=actor)
    view = MakerspaceLogoImageView if field == "logo_key" else MakerspaceCoverImageView
    response = view.as_view()(request, makerspace_id=space.pk)
    assert response.status_code == 200, response.data
    return response


@pytest.fixture
def storage_case(settings, monkeypatch):
    assert connection.vendor == "postgresql", "This suite requires real PostgreSQL"
    assert connection.get_autocommit() and not connection.in_atomic_block
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    settings.INFRA_HOSTS = {"testserver"}
    settings.PUBLIC_IMAGE_BUCKET = "recompute-public"
    settings.PUBLIC_IMAGE_MAX_BYTES = 100000
    settings.PUBLIC_IMAGE_ALLOWED_MIME = ["image/png"]
    # Use the migration/conftest singleton; never change immutable recovery authority.
    state, _ = DeploymentRecoveryState.objects.get_or_create(pk=1)
    assert state.mode == DeploymentRecoveryState.Mode.NORMAL
    new_connection = gate_locks._new_lock_connection

    def bounded_connection():
        raw = new_connection()
        with raw.cursor() as cursor:
            cursor.execute("SET statement_timeout = '12s'")
        raw.commit()
        return raw

    monkeypatch.setattr(gate_locks, "_new_lock_connection", bounded_connection)

    def outside_atomic():
        assert not connection.in_atomic_block, "Provider call held an application transaction"

    store = Store(boundary=outside_atomic)
    monkeypatch.setattr(storage, "_client", lambda: store)
    space, actor = make_space("recompute-exclusive"), make_actor("recompute-exclusive")
    Makerspace.objects.filter(pk=space.pk).update(resource_limit_overrides={"storage": 100000})
    space.refresh_from_db()

    def staged(target=space, color="blue"):
        key = storage.build_object_key("makerspace", target.pk, ".png")
        data = png(color)
        store.seed(storage.staging_key(key), data, "image/png")
        return key, len(data)

    return SimpleNamespace(space=space, actor=actor, store=store, staged=staged)


class Job:
    def __init__(self, operation):
        self.done, self.ready = Event(), Event()
        self.error = self.value = self.pid = None

        def run():
            close_old_connections()
            try:
                self.pid = sql("SELECT pg_backend_pid()")[0][0]
                sql("SET statement_timeout = '15s'")
                sql("SET lock_timeout = '12s'")
                self.ready.set()
                self.value = operation()
            except BaseException as exc:
                self.error = exc
            finally:
                connections.close_all()
                self.done.set()

        self.thread = Thread(target=run, daemon=True)
        self.thread.start()
        assert self.ready.wait(WAIT), "Worker did not establish its Django connection"

    def result(self):
        assert self.done.wait(20), "Worker did not finish within SQL timeouts"
        if self.error:
            raise self.error
        return self.value


@pytest.fixture
def jobs():
    running, releases = [], []

    def spawn(operation):
        job = Job(operation)
        running.append(job)
        return job

    def pause():
        entered, release = Event(), Event()
        releases.append(release)

        def wait():
            entered.set()
            assert release.wait(15), "Parent did not release the bounded provider/SQL pause"

        return entered, release, wait

    yield SimpleNamespace(spawn=spawn, pause=pause)
    for release in releases:
        release.set()
    for job in running:
        job.thread.join(timeout=20)
        assert not job.thread.is_alive(), "A DB worker survived test cleanup"
