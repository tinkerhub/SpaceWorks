"""SQL fixtures; only clock and provider byte operations are replaced."""

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence import storage
from apps.evidence.models import EvidencePhoto
from apps.evidence.reports import build_evidence_compliance
from apps.evidence.services_retention import sweep_evidence_retention
from apps.hardware_requests.models import HardwareRequest, ReturnEvent
from apps.operations.models import ReportMetricRollup
from apps.operations.report_rollups import finalize_evidence_rollups
from tests.return_helpers import make_member, make_space


def instant(value):
    return datetime.fromisoformat(value)


CREATED = instant("2026-02-01T06:00:00+00:00")
THROUGH = instant("2026-02-03T00:00:00+05:30")
AS_OF = instant("2026-04-15T12:00:00+00:00")
HISTORICAL = (
    "period", "evidence_type", "created_count", "attached_count",
    "unattached_count", "metadata_retained_count", "bytes", "attachment_rate_percent",
)


class ByteStore:
    """Current bytes at both keys, not a simulation of S3 version-listing rules."""

    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail_deletes = set()

    def size(self, key):
        self.calls.append(("size", key))
        value = self.objects.get(key)
        return None if value is None else len(value)

    def exists(self, key):
        self.calls.append(("exists", key))
        return key in self.objects

    def delete(self, key):
        self.calls.append(("delete", key))
        if key in self.fail_deletes:
            raise storage.StorageUnavailable("provider fixture failure")
        value = self.objects.pop(key, None)
        return "deleted" if value is not None else "absent_or_version_only"


class ReportLab:
    def __init__(self, store):
        self.store = store
        self.space = make_space("object-expiry-report")
        self.actor = make_member("object-expiry-reporter", self.space)

    def photo(self, *, space=None, when=CREATED, kind="issue", size=17, attached=False):
        space = space or self.space
        # auto_now_add gets the controlled instant on INSERT. Never UPDATE/backdate.
        with patch("django.utils.timezone.now", return_value=when):
            photo = EvidencePhoto.objects.create(
                makerspace=space, evidence_type=kind, uploaded_by=self.actor,
                object_key=f"evidence/{space.pk}/{uuid4().hex}.jpg",
                content_type="image/jpeg", size_bytes=size,
            )
        for key in (photo.object_key, storage.staging_key(photo.object_key)):
            self.store.objects[key] = b"x" * (size or 0)
        if attached:
            request = HardwareRequest.objects.create(
                makerspace=space, requester=self.actor,
                requester_username=self.actor.username,
                issue_evidence=photo if kind == "issue" else None,
            )
            if kind == "return":
                ReturnEvent.objects.create(
                    request=request, makerspace=space, evidence=photo,
                    actor=self.actor, remark="Returned with evidence.",
                )
        return photo

    def sweep(self, *, now=AS_OF):
        with patch("django.utils.timezone.now", return_value=now):
            return sweep_evidence_retention(now=now, batch_size=100)

    def roll(self, *, space=None, through=THROUGH, start_at=None):
        return finalize_evidence_rollups(
            space or self.space, through=through, start_at=start_at, actor=self.actor,
        )

    def report(self, space_id="default", **kwargs):
        if space_id == "default":
            space_id = self.space.pk
        calls = list(self.store.calls)
        result = build_evidence_compliance(space_id, **kwargs)
        assert self.store.calls == calls, "Report attempted provider byte operations"
        basis = result.meta["object_count_basis"].lower()
        assert "presence are unknown" in basis
        assert "no object-store probe" in basis
        assert "not current storage or quota usage" in basis
        assert "snapshot" in basis
        return result


@pytest.fixture
def report_lab(settings, monkeypatch):
    assert connection.vendor == "postgresql", "These cases require real PostgreSQL SQL/triggers"
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    settings.EVIDENCE_RETENTION_BATCH_SIZE = 100
    store = ByteStore()
    monkeypatch.setattr(storage, "object_size", store.size)
    monkeypatch.setattr(storage, "delete_object_strict", store.delete)
    monkeypatch.setattr(storage, "object_exists", store.exists)
    monkeypatch.setattr(
        storage, "_client", lambda: pytest.fail("External provider access is forbidden"),
    )
    with timezone.override("Asia/Kolkata"):
        yield ReportLab(store)


def historical(records):
    return [{key: row[key] for key in HISTORICAL} for row in records]


def metadata_snapshot(space):
    return list(EvidencePhoto.objects.filter(makerspace=space).order_by("pk").values())


def attachment_snapshot(space):
    return (
        list(HardwareRequest.objects.filter(makerspace=space).order_by("pk").values(
            "id", "issue_evidence_id", "status", "created_at",
        )),
        list(ReturnEvent.objects.filter(makerspace=space).order_by("pk").values()),
    )


def rollup_snapshot(space):
    return list(ReportMetricRollup.objects.filter(makerspace=space).order_by("pk").values())


def report_audit_snapshot(space):
    return list(AuditLog.objects.filter(
        makerspace=space, action__startswith="report.",
    ).order_by("pk").values())


def assert_metrics(row, *, created, attached, size, expired):
    assert {key: row[key] for key in (
        "created_count", "attached_count", "unattached_count", "bytes",
        "metadata_retained_count", "object_expired_count", "object_live_count",
        "attachment_rate_percent",
    )} == {
        "created_count": created, "attached_count": attached,
        "unattached_count": created - attached, "bytes": size,
        "metadata_retained_count": created, "object_expired_count": expired,
        "object_live_count": created - expired,
        "attachment_rate_percent": round(attached / created * 100, 2),
    }
