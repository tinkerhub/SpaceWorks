"""Small real-row fixtures shared by the recovery regressions."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.data_export.models import DataExportJob
from apps.makerspaces import limits
from tests.data_export.test_api import grant_manager, space, user


@pytest.fixture
def recovery_case(monkeypatch):
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    suffix = uuid.uuid4().hex
    actor = user(f"recovery-{suffix}")
    makerspace = space(f"recovery-{suffix}")
    makerspace.resource_limit_overrides = {"data_exports": 1, "storage": 100_000}
    makerspace.save(update_fields=("resource_limit_overrides",))
    grant_manager(actor, makerspace)
    return SimpleNamespace(actor=actor, space=makerspace)


def make_job(case, **overrides):
    now = timezone.now()
    values = {
        "makerspace": case.space,
        "requested_by": case.actor,
        "object_key": f"data-exports/{case.space.pk}/{uuid.uuid4()}.zip",
        "expires_at": now + timedelta(days=1),
    }
    values.update(overrides)
    return DataExportJob.objects.create(**values)


def manifest():
    return {
        "snapshot_at": timezone.now().isoformat(),
        "row_counts": {"inventory/products.csv": 2},
        "total_rows": 2,
    }


def events(job, action):
    return AuditLog.objects.filter(target_id=str(job.pk), action=action)


def usage(case):
    case.space.refresh_from_db()
    return case.space.storage_bytes_used
