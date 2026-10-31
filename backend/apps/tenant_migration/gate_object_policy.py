"""Exact non-view object mutation owners (re-exported by gate_policy)."""

# Non-view object mutations whose caller supplies the request/task session gate or a
# service-owned transaction gate. These are participation declarations, not bypasses;
# the AST guard rejects stale targets.
OBJECT_MUTATION_PARTICIPANTS = {
    "apps.backup.rollback_cleanup._delete_bytes": "Only the two operation-locked rollback_cleanup owners call this helper, after actual known-tenant source fences and frozen receipt binding checks; source_gate_module_guards pins both edges.",
    "apps.events.services_series._update_series": "update_series retains storage_lifecycle and passes its verified guard through inherited image cleanup.",
    "apps.object_storage_admin.StorageDocumentDeleteAdminMixin._release_images": "Guard-checked release_public_image_on_commit refuses missing ownership; delete entry points retain the lifecycle through commit.",
    "apps.events.services_images._remove_image": "The actual remove_image storage lifecycle retains the source boundary and explicit guard.",
    "apps.events.services_images._update_image": "The actual update_image storage lifecycle retains the source boundary and explicit guard.",
    "apps.events.services_series_images._remove_image": "The actual series remove_image wrapper retains the source boundary and guard.",
    "apps.events.services_series_images._update_image": "The actual series update_image wrapper retains the source boundary and guard.",
    "apps.machines.services._remove_image": "The actual machine remove_image wrapper retains the source boundary and guard.",
    "apps.machines.services._update_image": "The actual machine update_image wrapper retains the source boundary and guard.",
    "apps.data_export.lifecycle._fail_job": "gated_job retains the actual tenant boundary across state and byte cleanup.",
    "apps.data_export.lifecycle.recover_expired_job": "gated_job retains the tenant boundary across timeout recovery.",
    "apps.data_export.lifecycle.purge_expired_job": "gated_job fences byte-first periodic cleanup and accounting.",
    "apps.admin_api.bulk_import_apply._attach_image": "Runs inside the tenant-resolved admin bulk-import route.",
    "apps.data_export.services.run_export_job": (
        "The export task resolves and holds the tenant gate for this lifecycle."
    ),
    "apps.evidence.finalization.finalize_upload": "Reached only through the already-declared handover, return and direct-loan entry points.",
    "apps.evidence.services_retention._sweep_makerspace": (
        "The fan-out service owns one tenant source-gate boundary at a time."
    ),
    "apps.events.services_images.update_image": "Called by the tenant-resolved event image route.",
    "apps.events.services_series_images.update_image": "Called by the tenant-resolved event series image route.",
    "apps.events.services._update_event": (
        "The update_event wrapper owns storage_lifecycle when image inheritance may release "
        "a key; other event changes retain the tenant-resolved HTTP write boundary."
    ),
    "apps.hardware_requests.direct_loan_returns.validate_evidence_upload": "Runs inside the guarded direct-loan return transaction.",
    "apps.hardware_requests.handover_workflow.issue_request": "Runs inside the request route's tenant transaction.",
    "apps.hardware_requests.return_workflow.return_items": "Runs inside the request route's tenant transaction.",
    "apps.inventory.public_image_attach._delete_upload": "Called only by finalize_product_image below.",
    "apps.inventory.public_image_attach.finalize_product_image": (
        "Reached only through the tenant-resolved inventory image route and admin bulk import."
    ),
    "apps.machines.public_printer_service.submit_request": "Runs inside the public-slug printer request route.",
    "apps.machines.public_service_intake.submit_typed_request": (
        "Runs inside the public-slug machine-service request route's tenant boundary."
    ),
    "apps.machines.services.update_image": "Runs inside the model-resolved machine image route.",
    "apps.maintenance.services_documents.delete_log_document": "Runs inside the model-resolved maintenance document route.",
    "apps.makerspaces.lifecycle_storage._delete_public_image_keys": "Tenant purge is an express source-gate exclusion.",
    "apps.makerspaces.profile_images._swap": "Runs inside the authenticated member profile image route.",
    "apps.tenant_migration.tenant_dump_cleanup.cleanup_refused_tenant_dump_artifacts": (
        "Deletes only private Lane D coordination artifacts after a refused run."
    ),
    "apps.tenant_migration.tenant_dump_publication._delete_unpublished": (
        "Post-commit cleanup of a refused Lane D coordination artifact."
    ),
    "apps.tenant_migration.tenant_dump_publication._discard_failed_registration": (
        "Fail-closed cleanup of an unpublished Lane D coordination artifact."
    ),
    "apps.tenant_migration.tenant_dump_publication.register_unpublished_artifact": (
        "Offline Lane D sealing writes only a private publication-staging object."
    ),
    "apps.tenant_migration.services_export_job.run_migration_export_job": (
        "The migration export reasserts source_archive_boundary with its exact live lease before upload."
    ),
}
