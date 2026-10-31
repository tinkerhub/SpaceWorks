"""Static checks for concrete service/callback owners outside ordinary HTTP writes."""

import ast
from pathlib import Path

from .source_gate_ast import all_functions
from .source_gate_conditional_guards import validate_conditional_service_boundaries


# Exact state writers include callbacks with no direct storage call. A declaration
# alone is insufficient: each must retain its actual decorator/assertion boundary.
SERVICE_WRITER_BOUNDARIES = {
    "apps.makerspaces.module_purge.purge_module": "purge_boundary",
    "apps.makerspaces.module_purge_receipts.retry_cleanup": "purge_boundary",
    "apps.makerspaces.module_install.install_module": "boundary_tenant_write",
    "apps.makerspaces.module_install.uninstall_module": "boundary_tenant_write",
    "apps.makerspaces.module_install.apply_profile": "boundary_tenant_write",
    "apps.backup.rollback_cleanup.cleanup_rollback_objects": "deployment_operation_lock",
    "apps.backup.rollback_cleanup.cleanup_expired_rollback_objects": "deployment_operation_lock",
    "apps.backup.rollback_cleanup._cleanup_expired": "fanout_tenant_write",
    "apps.backup.rollback_cleanup._cleanup_restore": "fanout_tenant_write",
    "apps.makerspaces.profile_services.save_profile": "storage_lifecycle",
    "apps.machines.public_service_intake.submit_typed_request": "storage_lifecycle",
    "apps.machines.public_printer_service.submit_request": "storage_lifecycle",
    "apps.admin_api.bulk_import_apply.apply_import": "boundary_tenant_write",
    "apps.events.services_series.update_series": "storage_lifecycle",
    "apps.events.services.update_event": "storage_lifecycle",
    "apps.object_storage_lifecycle.storage_lifecycle": "boundary_tenant_write",
    "apps.machines.document_lifecycle.attach_document": "storage_lifecycle",
    "apps.machines.document_lifecycle.remove_document": "storage_lifecycle",
    "apps.machines.service_file_lifecycle.finalize_file": "storage_lifecycle",
    "apps.machines.service_file_lifecycle.delete_staged_file": "storage_lifecycle",
    "apps.maintenance.services_documents.finalize_log_document": "storage_lifecycle",
    "apps.maintenance.services_documents.delete_log_document": "storage_lifecycle",
    "apps.events.services_images.update_image": "storage_lifecycle",
    "apps.events.services_images.remove_image": "storage_lifecycle",
    "apps.events.services_series_images.update_image": "storage_lifecycle",
    "apps.events.services_series_images.remove_image": "storage_lifecycle",
    "apps.machines.services.update_image": "storage_lifecycle",
    "apps.machines.services.remove_image": "storage_lifecycle",
    "apps.makerspaces.profile_images.set_avatar": "storage_lifecycle",
    "apps.makerspaces.profile_images.set_project_image": "storage_lifecycle",
    "apps.inventory.tenant_object_callbacks.delete_public_image": "storage_lifecycle",
    "apps.inventory.tenant_object_callbacks.release_public_image": "storage_lifecycle",
    "apps.data_export.lifecycle._claim_job": "gated_job",
    "apps.data_export.lifecycle._finalize_job": "gated_job",
    "apps.data_export.lifecycle._fail_job": "gated_job",
    "apps.data_export.lifecycle.fail_dispatch": "gated_job",
    "apps.data_export.lifecycle.recover_expired_job": "gated_job",
    "apps.data_export.lifecycle.purge_expired_job": "gated_job",
    "apps.data_export.lifecycle._mark_failed_locked": "assert_write_allowed",
    "apps.data_export.services.run_export_job": "gated_job",
    "apps.data_export.storage.upload_archive": "gated_archive_upload",
    "apps.data_export.storage._upload_archive_bytes": "assert_boundary_held",
    "apps.events.services_certificates.render_certificate": "boundary_tenant_write",
    "apps.events.services_certificates.download_url": "boundary_tenant_write",
    "apps.events.certificate_cleanup.cleanup_abandoned_certificate": "boundary_tenant_write",
    "apps.backup.reconciliation.reconcile_artifact_uploads": "deployment_operation_lock",
    "apps.tenant_migration.services_export_job.run_migration_export_job": "source_archive_boundary",
}

# These inner owners inherit one concrete outer boundary; verify both functions
# and the direct call edge so an extraction cannot silently make a declaration stale.
INHERITED_WRITER_BOUNDARIES = (
    ("apps.makerspaces.module_purge_receipts.execute_cleanup", "apps.makerspaces.module_purge.purge_module"),
    ("apps.makerspaces.module_purge_receipts.execute_cleanup", "apps.makerspaces.module_purge_receipts.retry_cleanup"),
    ("apps.makerspaces.module_purge_receipts.prepare_intent", "apps.makerspaces.module_purge.purge_module"),
    ("apps.backup.rollback_cleanup._cleanup_restore", "apps.backup.rollback_cleanup.cleanup_rollback_objects"),
    ("apps.backup.rollback_cleanup._cleanup_expired", "apps.backup.rollback_cleanup.cleanup_expired_rollback_objects"),
    ("apps.backup.rollback_cleanup._delete_bytes", "apps.backup.rollback_cleanup._cleanup_restore"),
    ("apps.backup.rollback_cleanup._delete_bytes", "apps.backup.rollback_cleanup._cleanup_expired"),
    ("apps.events.services_series._update_series", "apps.events.services_series.update_series"),
    ("apps.events.services._update_event", "apps.events.services.update_event"),
    ("apps.events.services_images._update_image", "apps.events.services_images.update_image"),
    ("apps.events.services_images._remove_image", "apps.events.services_images.remove_image"),
    ("apps.events.services_series_images._update_image", "apps.events.services_series_images.update_image"),
    ("apps.events.services_series_images._remove_image", "apps.events.services_series_images.remove_image"),
    ("apps.machines.services._update_image", "apps.machines.services.update_image"),
    ("apps.machines.services._remove_image", "apps.machines.services.remove_image"),
    ("apps.backup.reconciliation._reconcile_artifact_uploads_locked",
     "apps.backup.reconciliation.reconcile_artifact_uploads"),
    ("apps.data_export.storage._upload_archive_bytes", "apps.data_export.storage.upload_archive"),
    ("apps.events.services_certificates._render_certificate", "apps.events.services_certificates.render_certificate"),
    ("apps.events.services_certificates._claim_render", "apps.events.services_certificates._render_certificate"),
    ("apps.events.services_certificates._activate", "apps.events.services_certificates._render_certificate"),
    ("apps.events.services_certificates._fail_render", "apps.events.services_certificates._render_certificate"),
)


def calls_named(node, name):
    return any(isinstance(item, ast.Call) and (
        getattr(item.func, "id", None) or getattr(item.func, "attr", None)
    ) == name for item in ast.walk(node))


def _names_decorator(node, name):
    return any((getattr(item, "id", None) or getattr(item, "attr", None)) == name
               for item in node.decorator_list)


def validate_service_writer_boundaries(apps_dir, error_class):
    functions = all_functions(apps_dir)
    for target, boundary in SERVICE_WRITER_BOUNDARIES.items():
        node = functions.get(target)
        if node is None or not (calls_named(node, boundary) or _names_decorator(node, boundary)):
            raise error_class(f"service writer lost its actual source boundary: {target}")
    for target, owner in INHERITED_WRITER_BOUNDARIES:
        if target not in functions or owner not in functions or not calls_named(
            functions[owner], target.rsplit(".", 1)[-1],
        ):
            raise error_class(f"inherited writer boundary drifted: {owner} -> {target}")
    outer = functions["apps.events.services_certificates.render_certificate"]
    if any((getattr(item, "attr", None) == "atomic") for item in outer.decorator_list):
        raise error_class("certificate rendering must not hold an outer database transaction")
    _validate_storage_admin_boundary(apps_dir, error_class)
    validate_conditional_service_boundaries(functions, error_class)
    from .source_gate_module_guards import validate_module_cleanup_boundaries

    validate_module_cleanup_boundaries(apps_dir, functions, error_class)


def _validate_storage_admin_boundary(apps_dir, error_class):
    # all_functions deliberately covers module functions only. This exact class
    # check keeps the admin callback's real guard/entry ownership from going blind.
    tree = ast.parse((Path(apps_dir) / "object_storage_admin.py").read_text())
    klass = next((node for node in tree.body if isinstance(node, ast.ClassDef)
                  and node.name == "StorageDocumentDeleteAdminMixin"), None)
    methods = {node.name: node for node in klass.body if isinstance(node, ast.FunctionDef)} if klass else {}
    required = {"_release_images", "delete_view", "delete_model", "delete_queryset"}
    if not required <= methods.keys():
        raise error_class("storage admin lifecycle owner disappeared")
    releases = [node for node in ast.walk(methods["_release_images"])
                if isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "release_public_image_on_commit"]
    if len(releases) != 1 or not any(keyword.arg == "guard"
            and isinstance(keyword.value, ast.Name) and keyword.value.id == "guard"
            for keyword in releases[0].keywords):
        raise error_class("storage admin cleanup lost its checked guard argument")
    for name in ("delete_view", "delete_queryset"):
        if not calls_named(methods[name], "storage_lifecycle"):
            raise error_class(f"storage admin entry lost lifecycle: {name}")
    for name in ("delete_model", "delete_queryset"):
        if not calls_named(methods[name], "verify") or not calls_named(methods[name], "_release_images"):
            raise error_class(f"storage admin deletion lost verified cleanup ownership: {name}")
