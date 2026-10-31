"""Resolve the export tenant before taking any job/object row locks."""

from functools import wraps

from apps.tenant_migration.gate_runtime import boundary_tenant_write


def gated_job(function):
    @wraps(function)
    def guarded(job_or_id, *args, **kwargs):
        from .models import DataExportJob

        job_id = getattr(job_or_id, "pk", job_or_id)
        makerspace_id = DataExportJob.objects.filter(pk=job_id).values_list(
            "makerspace_id", flat=True,
        ).first()
        if makerspace_id is None:
            return function(job_or_id, *args, **kwargs)
        with boundary_tenant_write(makerspace_id):
            return function(job_or_id, *args, **kwargs)
    return guarded


def gated_archive_upload(function):
    @wraps(function)
    def guarded(object_key, *args, **kwargs):
        from .errors import ExportIntegrityError
        from .models import DataExportJob

        makerspace_id = DataExportJob.objects.filter(object_key=object_key).values_list(
            "makerspace_id", flat=True,
        ).first()
        if makerspace_id is None:
            raise ExportIntegrityError("The export upload has no live owning job.")
        with boundary_tenant_write(makerspace_id):
            return function(object_key, *args, **kwargs)
    return guarded
