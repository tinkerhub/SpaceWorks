"""Concrete task-exempt import owners and restore barriers; no policy-only bypass."""

import ast

from .source_gate_ast import all_functions
from .source_gate_service_guards import calls_named

IMPORT_WRITERS = {
    "services_import_job": ("create_import_job", "claim_import_job", "run_import_job"),
    "import_execution": ("run_import_job",),
    "import_finalization": ("finalize_import_job",),
    "import_job_cleanup": ("cleanup_expired_import_jobs", "cleanup_abandoned_import_objects", "resume_expired_finalizing_import_jobs"),
    "import_staging": ("stage_encrypted_upload",),
    "materialization": ("materialize_tenant",),
    "object_import": ("prepare_import_objects", "rollback_import_objects", "delete_staging_objects"),
    "object_promotion": ("promote_import_objects",),
    "object_storage": ("upload_staged", "copy_from_staging", "delete_object", "choose_target_key"),
}
RESTORE_BARRIERS = (
    "apps.tenant_migration.tenant_restore_target_state.establish_target_import_state",
    "apps.tenant_migration.tenant_restore_target_state.set_target_normal",
    "apps.backup.recovery.enter_quarantine",
    "apps.backup.compound_restore_target.DatabaseStateTarget.acknowledge_recovery",
)


def validate_import_publication_boundaries(apps_dir, error_class):
    functions = all_functions(apps_dir)
    for module, names in IMPORT_WRITERS.items():
        for name in names:
            target = f"apps.tenant_migration.{module}.{name}"
            node = functions.get(target)
            if node is None or not any(getattr(d, "id", None) == "import_writer" for d in node.decorator_list):
                raise error_class(f"task-exempt import lost its real boundary: {target}")
    for target, call in (
        ("apps.tenant_migration.import_boundary.import_write_boundary", "unscoped_writer_shared_boundary"),
        ("apps.tenant_migration.import_boundary.import_writer", "import_write_boundary"),
        ("apps.tenant_migration.services_import_job.run_import_job", "execute"),
        ("apps.tenant_migration.import_execution.run_import_job", "materialize_tenant"),
        ("apps.tenant_migration.import_execution.run_import_job", "finalize_import_job"),
        ("apps.tenant_migration.import_execution.run_import_job", "rollback_import_objects"),
        ("apps.tenant_migration.materialization.materialize_tenant", "prepare_import_objects"),
        ("apps.tenant_migration.materialization.materialize_tenant", "handle_materialization_failure"),
        ("apps.tenant_migration.import_finalization.finalize_import_job", "promote_import_objects"),
        ("apps.tenant_migration.import_finalization.finalize_import_job", "verify_import_objects"),
    ):
        if target not in functions or not calls_named(functions[target], call):
            raise error_class(f"import boundary call chain drifted: {target} -> {call}")
    callback = functions.get("apps.tenant_migration.archive_retention.schedule_import_archive_unlink")
    unlink = next((n for n in ast.walk(callback) if isinstance(n, ast.FunctionDef) and n.name == "unlink"), None) if callback else None
    if (unlink is None or not any(getattr(d, "id", None) == "import_writer" for d in unlink.decorator_list)
            or not calls_named(callback, "owns_cleanup")):
        raise error_class("deferred archive cleanup lost its execution boundary or scheduling-time purge ownership")
    # all_functions deliberately only returns module functions; resolve the one
    # class method explicitly without changing whole-tree discovery semantics.
    from pathlib import Path

    target_tree = ast.parse((Path(apps_dir) / "backup" / "compound_restore_target.py").read_text())
    klass = next(n for n in target_tree.body if isinstance(n, ast.ClassDef) and n.name == "DatabaseStateTarget")
    method = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "acknowledge_recovery")
    functions[RESTORE_BARRIERS[-1]] = method
    for target in RESTORE_BARRIERS:
        if target not in functions or not calls_named(functions[target], "invalidate_restored_receipts"):
            raise error_class(f"restore readiness lost receipt invalidation: {target}")
