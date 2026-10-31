"""Narrow HTTP ownership, signed reopen denial, and task gate regressions."""

from types import SimpleNamespace

import pytest
from django.db import connection
from django.test import RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone

from apps.makerspaces.models import Makerspace
from apps.makerspaces.purge_intent import PurgeInProgress
from apps.tenant_migration import cutover
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_http_ownership import service_owns_http_boundary
from apps.tenant_migration.protocol_errors import TransitionConflictError
from apps.tenant_migration.source_gate_ast import APPS_DIR
from apps.tenant_migration.source_gate_owned_http_guards import validate_service_owned_http_boundaries
from config.admin_source_gate import admin_tenant_write
from tests.makerspaces.purge_test_support import actor, advisory_lock, archived_space, receipt
from tests.tenant_migration.object_helpers import encryption_key
from tests.tenant_migration.protocol_helpers import signed_envelope, source_pairing
from tests.tenant_migration.test_source_gate_task_locks import _register_observation, observable_gate_task

pytestmark = pytest.mark.django_db(transaction=True)


def test_signed_abort_cannot_reopen_purge_started_source():
    user, space = actor(), archived_space()
    pairing, target, key = source_pairing(user, space)
    envelope = signed_envelope(pairing, "target_abort", target, key)
    Makerspace.objects.filter(pk=space.pk).update(purge_started_at=timezone.now())
    with pytest.raises(TransitionConflictError, match="Purge has started"):
        cutover.reopen_source(pairing=pairing, makerspace=space, receipt_envelope=envelope, actor=user)
    space.refresh_from_db()
    assert space.archived_at is not None and space.purge_started_at is not None


def test_tenant_resolved_task_refuses_purge_before_dispatch(monkeypatch):
    space = archived_space()
    Makerspace.objects.filter(pk=space.pk).update(purge_started_at=timezone.now())

    def forbidden():
        pytest.fail("purge-started tenant task dispatched")

    _register_observation(monkeypatch, forbidden)
    with pytest.raises(PurgeInProgress):
        observable_gate_task.apply(args=(space.pk,), throw=True)


def test_other_admin_writes_keep_shared_locks_and_no_app_transaction():
    space = Makerspace.objects.create(name="admin shared", slug="admin-shared")
    with admin_tenant_write([space.pk]):
        assert not connection.in_atomic_block
        with advisory_lock(space.pk) as acquired:
            assert not acquired
    with advisory_lock(space.pk) as acquired:
        assert acquired


@pytest.mark.parametrize("route", ["confirm", "retry"])
def test_runtime_resolver_grants_only_exact_non_atomic_protected_post(route):
    row = receipt()
    name = "admin:makerspaces_makerspace_purge_confirmed" if route == "confirm" else "admin:makerspaces_purgereceipt_retry_cleanup"
    url = reverse(name, args=[] if route == "confirm" else [row.pk])
    match = resolve(url)
    factory = RequestFactory()
    assert service_owns_http_boundary(factory.post(url), match)
    assert not service_owns_http_boundary(factory.get(url), match)
    assert not service_owns_http_boundary(factory.post(url), SimpleNamespace(view_name="admin:makerspaces_makerspace_changelist"))
    for defect in ("wrong_handler", "missing_nonatomic", "csrf_exempt"):
        def wrong_handler(request):
            return None

        wrong_handler._non_atomic_requests = {"default"}
        if defect != "wrong_handler":
            wrong_handler.__wrapped__ = match.func
        if defect == "missing_nonatomic":
            wrong_handler._non_atomic_requests = set()
        if defect == "csrf_exempt":
            wrong_handler.csrf_exempt = True
        forged = SimpleNamespace(view_name=name, func=wrong_handler)
        with pytest.raises(SourceMigrationGateUnavailable):
            service_owns_http_boundary(factory.post(url), forged)


@pytest.mark.parametrize("mutation", ["duplicate", "lost_nonatomic", "wrong_import", "wrong_service"])
def test_source_ownership_guard_rejects_route_or_service_drift(tmp_path, mutation):
    # Copy only this boundary's owners; no whole-repository recursive gate run.
    files = (
        "makerspaces/urls_admin_purge.py", "makerspaces/urls_admin_purge_receipts.py",
        "makerspaces/admin_purge.py", "makerspaces/admin_purge_receipts.py",
        "makerspaces/lifecycle_purge.py", "makerspaces/purge_receipts.py",
        "tenant_migration/gate_http_ownership.py",
        "makerspaces/urls_admin_module_purge_receipts.py",
        "makerspaces/admin_module_purge_receipts.py", "makerspaces/module_purge_receipts.py",
    )
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((APPS_DIR / relative).read_text())
    validate_service_owned_http_boundaries(tmp_path, RuntimeError)
    route = tmp_path / "makerspaces/urls_admin_purge.py"
    if mutation == "duplicate":
        (tmp_path / "makerspaces/urls_duplicate.py").write_text(route.read_text())
    elif mutation == "lost_nonatomic":
        route.write_text(route.read_text().replace("non_atomic_requests", "atomic"))
    elif mutation == "wrong_import":
        route.write_text(route.read_text().replace("apps.makerspaces.admin_purge import", "apps.makerspaces.admin import"))
    else:
        service = tmp_path / "makerspaces/lifecycle_purge.py"
        service.write_text(service.read_text().replace("with purge_boundary(", "with unrelated_boundary("))
    with pytest.raises(RuntimeError):
        validate_service_owned_http_boundaries(tmp_path, RuntimeError)
