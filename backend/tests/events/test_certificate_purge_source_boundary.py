"""GET render and never-activated cleanup own lock-only source boundaries."""

from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.backup.not_restored import TenantNotRestored
from apps.events import certificate_cleanup, certificate_storage, services_certificates as certificates
from apps.events.models import EventAttendanceCertificate
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.models import SourceMigrationGate
from tests.backup.e7_reservation_test_helpers import persist_restore_state
from tests.events.certificate_recovery_helpers import certificate_case, certificate_io
from tests.makerspaces.purge_test_support import actor, advisory_lock, bounded_source_wait
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def managed_api_client(settings):
    settings.INFRA_HOSTS = {"api.space-works.tech"}
    settings.ALLOWED_HOSTS = ["api.space-works.tech"]
    return APIClient(HTTP_HOST="api.space-works.tech")


@pytest.mark.parametrize("refusal", ["closed", "frozen", "not_restored", "purge"])
def test_get_triggered_download_refuses_before_render_claim_upload_or_activation(refusal, certificate_io):
    case = certificate_case(f"certificate-source-{refusal}")
    if refusal in {"closed", "frozen"}:
        close_gate(case.space, case.actor, state=(SourceMigrationGate.State.DRAINING
                   if refusal == "closed" else SourceMigrationGate.State.QUIESCED))
    elif refusal == "not_restored":
        persist_restore_state({"component_ids": [str(uuid4())]}, makerspace_id=case.space.pk)
    else:
        Makerspace.objects.filter(pk=case.space.pk).update(archived_at=timezone.now(), purge_started_at=timezone.now())
    before = EventAttendanceCertificate.objects.values().get(pk=case.certificate.pk)
    with pytest.raises(TenantNotRestored if refusal == "not_restored" else SourceMigrationGateClosed):
        certificates.download_url(case.certificate)
    assert EventAttendanceCertificate.objects.values().get(pk=case.certificate.pk) == before
    certificate_io.render.assert_not_called()
    certificate_io.upload.assert_not_called()
    certificate_io.download.assert_not_called()
    assert not AuditLog.objects.filter(makerspace=case.space, action="event.certificate_rendered").exists()


def test_real_get_renders_under_shared_boundary_across_short_db_phases(certificate_io, managed_api_client):
    case = certificate_case("certificate-get-boundary")
    root = actor()
    observed = []

    def prove(phase):
        assert not connection.in_atomic_block
        with advisory_lock(case.space.pk) as acquired:
            assert not acquired
        observed.append(phase)

    def upload(key, payload):
        prove("upload")
        assert EventAttendanceCertificate.objects.get(pk=case.certificate.pk).status == "rendering"
        return certificate_io.store(key, payload)

    def presign(key):
        prove("presign")
        assert EventAttendanceCertificate.objects.get(pk=case.certificate.pk).status == "active"
        return "https://storage.example.test/download"

    certificate_io.upload.side_effect = upload
    certificate_io.download.side_effect = presign
    client = managed_api_client
    client.force_authenticate(root)
    url = reverse("admin-event-certificate-download", args=[case.certificate.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert response.data["url"] == "https://storage.example.test/download"
    assert observed == ["upload", "presign"]
    case.certificate.refresh_from_db(); case.space.refresh_from_db()
    assert case.certificate.status == "active"
    assert case.space.storage_bytes_used == len(certificate_io.objects[case.certificate.object_key])
    assert AuditLog.objects.filter(makerspace=case.space, action="event.certificate_rendered").count() == 1
    assert client.get(url).status_code == 200
    assert certificate_io.upload.call_count == 1
    with advisory_lock(case.space.pk) as acquired:
        assert acquired


def test_frozen_real_get_never_claims_pending_certificate(certificate_io, managed_api_client):
    case = certificate_case("certificate-get-frozen")
    close_gate(case.space, case.actor)
    client = managed_api_client
    client.force_authenticate(actor())
    response = client.get(reverse("admin-event-certificate-download", args=[case.certificate.pk]))
    assert response.status_code == 423
    case.certificate.refresh_from_db()
    assert case.certificate.status == "pending"
    certificate_io.upload.assert_not_called()


def test_revoked_never_activated_callback_owns_boundary_without_app_transaction(certificate_io):
    case = certificate_case("certificate-cleanup-lock-only")
    key = case.certificate.object_key
    stage = certificate_storage.staging_key(key)
    certificate_io.objects.update({key: b"abandoned final", stage: b"abandoned staging"})
    observed = []

    def delete(_client, *, bucket, key):
        assert not connection.in_atomic_block
        with advisory_lock(case.space.pk) as acquired:
            assert not acquired
        observed.append(key)
        certificate_io.objects.pop(key)

    certificate_io.cleanup.side_effect = delete
    with transaction.atomic():
        certificates.revoke(case.certificate, actor=case.actor, reason="staff_revoked")
        assert certificate_io.objects and observed == []
    assert observed == [key, stage]
    assert not certificate_io.objects
    case.certificate.refresh_from_db(); case.space.refresh_from_db()
    assert case.certificate.status == "revoked"
    assert case.certificate.rendered_at is None and case.certificate.size_bytes is None
    assert case.space.storage_bytes_used == 0
    assert not AuditLog.objects.filter(makerspace=case.space, action="event.certificate_rendered").exists()
    with advisory_lock(case.space.pk) as acquired:
        assert acquired


def test_cleanup_real_exclusive_contention_retains_bytes_and_zero_credit(
    certificate_io, bounded_source_wait, caplog,
):
    case = certificate_case("certificate-cleanup-contended")
    certificates.revoke(case.certificate, actor=case.actor, reason="staff_revoked")
    certificate_io.cleanup.reset_mock()
    key = case.certificate.object_key
    certificate_io.objects[key] = b"late upload after revoke callback"
    with advisory_lock(case.space.pk) as acquired:
        assert acquired
        certificate_cleanup.cleanup_abandoned_certificate(case.certificate.pk)
    certificate_io.cleanup.assert_not_called()
    assert certificate_io.objects[key] == b"late upload after revoke callback"
    case.space.refresh_from_db()
    assert case.space.storage_bytes_used == 0
    assert "event_certificate_abandoned_cleanup_failed" in caplog.text


def test_revoked_cleanup_also_denies_purge_started_source(certificate_io, caplog):
    case = certificate_case("certificate-cleanup-purge-denial")
    certificates.revoke(case.certificate, actor=case.actor, reason="staff_revoked")
    certificate_io.cleanup.reset_mock()
    certificate_io.objects[case.certificate.object_key] = b"late upload"
    Makerspace.objects.filter(pk=case.space.pk).update(archived_at=timezone.now(), purge_started_at=timezone.now())
    with caplog.at_level("INFO"):
        certificate_cleanup.cleanup_abandoned_certificate(case.certificate.pk)
    certificate_io.cleanup.assert_not_called()
    assert certificate_io.objects[case.certificate.object_key] == b"late upload"
    assert "event_certificate_cleanup_skipped_closed_source_gate" in caplog.text
