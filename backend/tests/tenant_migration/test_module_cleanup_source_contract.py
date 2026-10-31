"""Negative controls exercise the new narrow source guards, never a workflow gate."""
import ast
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.test import RequestFactory
from django.urls import resolve, reverse

from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_http_ownership import service_owns_http_boundary
from apps.tenant_migration.source_gate_ast import APPS_DIR, all_functions
from apps.tenant_migration.source_gate_module_guards import validate_module_cleanup_boundaries
from apps.tenant_migration.source_gate_owned_http_guards import validate_service_owned_http_boundaries


@pytest.fixture
def narrow_source(tmp_path):
    root = tmp_path / "backend/apps"
    paths = (
        "backup/management/commands/backup_control.py", "backup/object_restore.py",
        "makerspaces/admin_capabilities.py", "makerspaces/management/commands/recompute_storage.py",
        "makerspaces/urls_admin_module_purge_receipts.py", "makerspaces/admin_module_purge_receipts.py",
        "makerspaces/module_purge_receipts.py", "makerspaces/module_purge.py", "makerspaces/module_install.py",
        "backup/rollback_cleanup.py", "backup/rollback_cleanup_outcomes.py", "backup/tasks.py",
        "makerspaces/urls_admin_purge.py", "makerspaces/urls_admin_purge_receipts.py",
        "makerspaces/admin_purge.py", "makerspaces/admin_purge_receipts.py",
        "makerspaces/lifecycle_purge.py", "makerspaces/purge_receipts.py",
        "tenant_migration/gate_http_ownership.py",
    )
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((APPS_DIR / relative).read_text())
    script = tmp_path / "scripts/restore.sh"
    script.parent.mkdir()
    script.write_text((APPS_DIR.parent.parent / "scripts/restore.sh").read_text())
    return root


FUNCTION_MUTATIONS = [
    ("makerspaces.module_purge.purge_module", "purge_boundary"),
    ("makerspaces.module_purge_receipts.retry_cleanup", "purge_boundary"),
    ("makerspaces.module_purge_receipts.retry_cleanup", "validate_receipt"),
    ("makerspaces.module_purge.purge_module", "validate_receipt"),
    ("makerspaces.module_install.install_module", "boundary_tenant_write"),
    ("makerspaces.module_install.uninstall_module", "boundary_tenant_write"),
    ("makerspaces.module_install.apply_profile", "boundary_tenant_write"),
    ("makerspaces.module_install._apply", "enabling_modules"),
    ("backup.rollback_cleanup.cleanup_rollback_objects", "deployment_operation_lock"),
    ("backup.rollback_cleanup.cleanup_expired_rollback_objects", "deployment_operation_lock"),
    ("backup.rollback_cleanup.cleanup_rollback_objects", "unscoped_writer_shared_boundary"),
    ("backup.rollback_cleanup._cleanup_restore", "fanout_tenant_write"),
    ("backup.rollback_cleanup._cleanup_restore", "_frozen"),
    ("backup.rollback_cleanup._cleanup_expired", "_frozen"),
    ("backup.rollback_cleanup._cleanup_expired", "fanout_tenant_write"),
    ("backup.tasks.cleanup_expired_restore_rollbacks_task", "cleanup_expired_rollback_objects"),
    ("makerspaces.module_purge_receipts.execute_cleanup", "synchronous_cleanup"),
    ("makerspaces.module_purge_receipts.execute_cleanup", "atomic"),
    ("makerspaces.module_purge_receipts.execute_cleanup", "record"),
]


@pytest.mark.parametrize("target,call", FUNCTION_MUTATIONS)
def test_actual_module_boundary_guard_rejects_removed_owner_or_call_edge(narrow_source, target, call):
    functions = all_functions(narrow_source)
    validate_module_cleanup_boundaries(narrow_source, functions, RuntimeError)
    functions = deepcopy(functions)
    for node in ast.walk(functions[f"apps.{target}"]):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == call:
                node.func.id = "unowned_operation"
            elif isinstance(node.func, ast.Attribute) and node.func.attr == call:
                node.func.attr = "unowned_operation"
    with pytest.raises(RuntimeError):
        validate_module_cleanup_boundaries(narrow_source, functions, RuntimeError)


@pytest.mark.parametrize("path,old,new", [
    ("makerspaces/admin_capabilities.py", "assert_boundary_held(obj.pk)", "unowned_operation(obj.pk)"),
    ("makerspaces/admin_capabilities.py", "with boundary_tenant_write(maker_id)", "with unowned_operation(maker_id)"),
    ("makerspaces/management/commands/recompute_storage.py", "assert_no_inprogress([makerspace.pk])", "unowned_operation([makerspace.pk])"),
    ("makerspaces/management/commands/recompute_storage.py", "with fanout_tenant_write(", "with unowned_operation("),
    ("makerspaces/management/commands/recompute_storage.py", "exclusive=True", "exclusive=False"),
    ("makerspaces/management/commands/recompute_storage.py", "makerspace = self._admit(makerspace.pk)", "makerspace = makerspace"),
    ("makerspaces/management/commands/recompute_storage.py", "assert_boundary_held(makerspace_id)", "unowned_operation(makerspace_id)"),
    ("makerspaces/management/commands/recompute_storage.py", "assert_no_inprogress([makerspace_id])", "unowned_operation([makerspace_id])"),
    ("makerspaces/management/commands/recompute_storage.py", "pk=1, mode=DeploymentRecoveryState.Mode.NORMAL", "pk=1, mode=DeploymentRecoveryState.Mode.QUIESCED"),
    ("makerspaces/management/commands/recompute_storage.py", "servable_queryset().filter(pk=makerspace_id).first()", "servable_queryset().first()"),
    ("makerspaces/management/commands/recompute_storage.py", "self._admit(makerspace_id)", "unowned_operation(makerspace_id)"),
    ("makerspaces/management/commands/recompute_storage.py", "lock_connection = _exclusive_boundary_connection(makerspace_id)", "lock_connection = connection"),
    ("makerspaces/management/commands/recompute_storage.py", "with lock_connection.cursor()", "with connection.cursor()"),
    ("makerspaces/management/commands/recompute_storage.py", "WHERE id = 1 AND mode = 'normal'", "WHERE id = 1"),
    ("makerspaces/management/commands/recompute_storage.py", "[total, makerspace_id]", "[makerspace_id, total]"),
    ("makerspaces/management/commands/recompute_storage.py", "cursor.rowcount != 1", "cursor.rowcount < 0"),
    ("makerspaces/management/commands/recompute_storage.py", "lock_connection.commit()", "connection.commit()"),
    ("makerspaces/management/commands/recompute_storage.py", "lock_connection.commit()", "lock_connection.flush()"),
    ("backup/object_restore.py", "cleanup_rollback_objects,", "unowned_operation,"),
    ("backup/management/commands/backup_control.py", "cleanup_rollback_objects(RestoreOperation.objects.get(pk=restore_id))", "unowned_operation(RestoreOperation.objects.get(pk=restore_id))"),
])
def test_actual_owner_file_guards_refuse_removed_admin_counter_or_command_boundary(narrow_source, path, old, new):
    functions = all_functions(narrow_source)
    validate_module_cleanup_boundaries(narrow_source, functions, RuntimeError)
    source = narrow_source / path
    text = source.read_text()
    assert old in text
    source.write_text(text.replace(old, new))
    with pytest.raises(RuntimeError):
        validate_module_cleanup_boundaries(narrow_source, all_functions(narrow_source), RuntimeError)


def test_supervised_restore_source_guard_forbids_nested_cleanup_while_flock_held(narrow_source):
    functions = all_functions(narrow_source)
    validate_module_cleanup_boundaries(narrow_source, functions, RuntimeError)
    script = narrow_source.parent.parent / "scripts/restore.sh"
    # The guarded shell wrapper delegates locking to the fixed Python controller.
    assert '"$ROOT/scripts/restore-host.py" restore' in script.read_text()
    controller = (APPS_DIR.parent.parent / "scripts/restore-host.py").read_text()
    assert "with host_operation_lock(transport.ops, require_root_owned=True)" in controller
    with script.open("a") as output:
        output.write('\ncontrol cleanup-rollback --restore "$RESTORE_ID"\n')
    with pytest.raises(RuntimeError, match="supervised restore"):
        validate_module_cleanup_boundaries(narrow_source, functions, RuntimeError)


@pytest.mark.parametrize("defect", ["duplicate", "non-atomic", "csrf-wrapper", "wrong-import", "post", "service"])
def test_exact_module_route_guard_refuses_broadened_or_unprotected_route(narrow_source, defect):
    validate_service_owned_http_boundaries(narrow_source, RuntimeError)
    route = narrow_source / "makerspaces/urls_admin_module_purge_receipts.py"
    if defect == "duplicate":
        (route.parent / "urls_duplicate.py").write_text(route.read_text())
    elif defect in {"non-atomic", "csrf-wrapper", "wrong-import"}:
        before, after = {
            "non-atomic": ("non_atomic_requests", "atomic"),
            "csrf-wrapper": ("admin_view", "unprotected_view"),
            "wrong-import": ("apps.makerspaces.admin_module_purge_receipts import", "apps.makerspaces.admin import"),
        }[defect]
        route.write_text(route.read_text().replace(before, after))
    elif defect == "post":
        handler = route.parent / "admin_module_purge_receipts.py"
        handler.write_text(handler.read_text().replace("@require_POST", "@require_GET"))
    else:
        owner = route.parent / "module_purge_receipts.py"
        owner.write_text(owner.read_text().replace("with purge_boundary(", "with unowned_operation("))
    with pytest.raises(RuntimeError):
        validate_service_owned_http_boundaries(narrow_source, RuntimeError)


def test_runtime_module_route_exemption_is_exact_protected_non_atomic_post():
    name = "admin:makerspaces_modulepurgereceipt_retry_cleanup"
    url = reverse(name, args=[uuid4()])
    match, factory = resolve(url), RequestFactory()
    assert service_owns_http_boundary(factory.post(url), match)
    assert not service_owns_http_boundary(factory.get(url), match)
    assert not service_owns_http_boundary(factory.post(url), SimpleNamespace(view_name="admin:makerspaces_modulepurgereceipt_changelist"))
    for defect in ("wrong-handler", "atomic", "csrf"):
        def forged(request):
            return None
        forged._non_atomic_requests = {"default"}
        if defect != "wrong-handler":
            forged.__wrapped__ = match.func
        if defect == "atomic":
            forged._non_atomic_requests = set()
        if defect == "csrf":
            forged.csrf_exempt = True
        with pytest.raises(SourceMigrationGateUnavailable):
            service_owns_http_boundary(factory.post(url), SimpleNamespace(view_name=name, func=forged))


@pytest.mark.parametrize("owner", ["_cleanup_restore", "_cleanup_expired"])
def test_rollback_guard_rejects_global_branch_broadening(narrow_source, owner):
    functions = all_functions(narrow_source)
    validate_module_cleanup_boundaries(narrow_source, functions, RuntimeError)
    functions = deepcopy(functions)
    node = functions[f"apps.backup.rollback_cleanup.{owner}"]
    matched = False
    for item in ast.walk(node):
        if isinstance(item, ast.If) and ast.dump(item.test) == ast.dump(ast.parse("row.makerspace_id is None", mode="eval").body):
            item.test = ast.Constant(value=True)
            matched = True
    assert matched
    with pytest.raises(RuntimeError, match="escaped"):
        validate_module_cleanup_boundaries(narrow_source, functions, RuntimeError)
