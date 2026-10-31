"""Exact persisted snapshots, with global OIDC protocol metadata separated explicitly."""
from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from apps.audit.models import AuditLog
from apps.tenant_migration.models_source_gate import SourceMigrationGate
from tests.qr_http_ownership_safety.assertions import all_rows

from .conftest import DOMAIN_MODELS


def domain():
    return all_rows(*DOMAIN_MODELS)


def tenant_and_transition_audits(*, allow_oidc_metadata=False):
    rows = AuditLog.objects.all()
    if allow_oidc_metadata:
        rows = rows.exclude(action__in=[
            "auth.oidc_browser_attempt_consumed", "auth.social_login_failed",
        ])
    return list(rows.order_by("pk").values())


def frozen(space, actor):
    now = timezone.now()
    return SourceMigrationGate.objects.create(makerspace=space, actor=actor,
        state=SourceMigrationGate.State.QUIESCED, owner_id=uuid4(), fencing_token=1,
        heartbeat_at=now, lease_expires_at=now + timedelta(hours=1),
        presign_drain_until=now, quiesced_at=now)
