"""Cancellation and staff recovery cannot activate or erase an issued artifact."""

import pytest
from django.core.exceptions import ValidationError as ModelValidationError
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.events import certificate_cleanup, certificate_storage, services, services_certificates as certificates
from apps.events.exceptions import EventInvalidTransition
from apps.events.models import Event, EventAttendanceCertificate
from tests.events.certificate_recovery_helpers import certificate_case, certificate_io, move_to


pytestmark = pytest.mark.django_db


def rendered_audits(case):
    return AuditLog.objects.filter(makerspace=case.space, action="event.certificate_rendered")


@pytest.mark.parametrize("status", ["pending", "failed", "rendering"])
def test_cancel_revokes_unactivated_certificate_and_blocks_all_retries(
    status, certificate_io, django_capture_on_commit_callbacks,
):
    case = certificate_case(f"cancel-{status}")
    certificate = move_to(case.certificate, status)
    before_storage = case.space.storage_bytes_used

    with django_capture_on_commit_callbacks(execute=True):
        services.cancel(case.event, actor=case.actor, notify=False)

    certificate.refresh_from_db(); case.event.refresh_from_db(); case.space.refresh_from_db()
    assert case.event.status == Event.Status.CANCELLED
    assert certificate.status == EventAttendanceCertificate.Status.REVOKED
    assert (certificate.revoked_by_id, certificate.revocation_reason) == (case.actor.pk, "event_cancelled")
    assert certificate.rendered_at is None and certificate.size_bytes is None
    case.event.feedback_survey.refresh_from_db()
    assert not case.event.feedback_survey.is_open
    for operation in (
        lambda: certificates.download_url(certificate),
        lambda: certificates._claim_render(certificate.pk),
        lambda: certificates.reissue(case.registration, actor=case.actor),
    ):
        with pytest.raises(EventInvalidTransition):
            operation()
    assert case.registration.attendance_certificates.count() == 1
    assert case.space.storage_bytes_used == before_storage
    assert not rendered_audits(case).exists()
    assert AuditLog.objects.filter(action="event.certificate_revoked", target_id=str(certificate.pk)).count() == 1
    certificate_io.render.assert_not_called()
    certificate_io.upload.assert_not_called()
    certificate_io.download.assert_not_called()
    assert {call.kwargs["key"] for call in certificate_io.cleanup.call_args_list} == {
        certificate.object_key, certificate_storage.staging_key(certificate.object_key),
    }


def test_cancel_retains_active_artifact_metadata_and_storage_charge(
    certificate_io, django_capture_on_commit_callbacks,
):
    case = certificate_case("cancel-active")
    certificate = move_to(case.certificate, "active")
    before = (certificate.object_key, certificate.size_bytes, certificate.sha256, certificate.rendered_at)
    case.space.refresh_from_db()
    charge = case.space.storage_bytes_used
    assert charge == certificate.size_bytes > 0

    with django_capture_on_commit_callbacks(execute=True):
        services.cancel(case.event, actor=case.actor, notify=False)

    certificate.refresh_from_db(); case.space.refresh_from_db()
    assert certificate.status == "revoked"
    assert (certificate.object_key, certificate.size_bytes, certificate.sha256, certificate.rendered_at) == before
    assert case.space.storage_bytes_used == charge
    assert certificate_io.objects[certificate.object_key]
    certificate_io.cleanup.assert_not_called()
    with pytest.raises(EventInvalidTransition):
        certificates.download_url(certificate)
    certificate.size_bytes += 1
    with pytest.raises(ModelValidationError, match="immutable"):
        certificate.save(update_fields=["size_bytes"])


@pytest.mark.django_db(transaction=True)
def test_cancel_during_store_rejects_activation_and_cleans_late_upload(certificate_io):
    case = certificate_case("cancel-during-upload")
    certificate = case.certificate
    key = certificate.object_key
    staged = certificate_storage.staging_key(key)

    def cancel_then_upload(object_key, payload):
        claimed = EventAttendanceCertificate.objects.get(pk=certificate.pk)
        assert claimed.status == "rendering"
        services.cancel(case.event, actor=case.actor, notify=False)
        # The revoke cleanup has committed before this worker finishes its remote write.
        assert certificate_io.operations == [("delete", key), ("delete", staged)]
        certificate_io.objects[staged] = payload
        return certificate_io.store(object_key, payload)

    certificate_io.upload.side_effect = cancel_then_upload
    with pytest.raises(EventInvalidTransition, match="published or completed"):
        certificates.render_certificate(certificate)

    certificate.refresh_from_db(); case.space.refresh_from_db()
    assert certificate.status == "revoked"
    assert certificate.size_bytes is None and certificate.rendered_at is None
    assert case.space.storage_bytes_used == 0
    assert not rendered_audits(case).exists()
    assert certificate_io.objects == {}
    assert certificate_io.operations == [
        ("delete", key), ("delete", staged), ("upload", key),
        ("delete", key), ("delete", staged),
    ]


def test_abandoned_claim_can_be_revoked_and_reissued_without_reviving_old_worker(
    certificate_io, django_capture_on_commit_callbacks,
):
    case = certificate_case("recover-abandoned")
    old = certificates._claim_render(case.certificate.pk)
    with pytest.raises(EventInvalidTransition, match="in progress"):
        certificates.download_url(old)
    with django_capture_on_commit_callbacks(execute=True):
        certificates.revoke(old, actor=case.actor, reason="staff_revoked")
    new = certificates.reissue(case.registration, actor=case.actor)
    assert new.revision == old.revision + 1
    assert new.serial != old.serial and new.object_key != old.object_key
    assert new.response_id == old.response_id and new.registration_id == old.registration_id
    with pytest.raises(EventInvalidTransition, match="claim was lost"):
        certificates._activate(old.pk, 999, "a" * 64)
    case.space.refresh_from_db()
    assert case.space.storage_bytes_used == 0
    assert not rendered_audits(case).exists()

    prepared, url = certificates.download_url(new)
    repeated, repeated_url = certificates.download_url(prepared)

    old.refresh_from_db(); case.space.refresh_from_db()
    assert old.status == "revoked" and old.size_bytes is None
    assert prepared.status == repeated.status == "active"
    assert url == repeated_url == certificate_io.download.return_value
    assert case.space.storage_bytes_used == prepared.size_bytes
    assert rendered_audits(case).count() == 1
    certificate_io.render.assert_called_once()
    certificate_io.upload.assert_called_once()
    assert {call.kwargs["key"] for call in certificate_io.cleanup.call_args_list} == {
        old.object_key, certificate_storage.staging_key(old.object_key),
    }


def test_reissue_rechecks_disabled_events_module(certificate_io, django_capture_on_commit_callbacks):
    case = certificate_case("reissue-module-off")
    with django_capture_on_commit_callbacks(execute=True):
        certificates.revoke(case.certificate, actor=case.actor, reason="staff_revoked")
    case.space.enabled_modules = [key for key in case.space.enabled_modules if key != "events"]
    case.space.save(update_fields=["enabled_modules"])

    with pytest.raises(ValidationError) as caught:
        certificates.reissue(case.registration, actor=case.actor)

    assert "module" in caught.value.detail
    assert case.registration.attendance_certificates.count() == 1
    assert not AuditLog.objects.filter(makerspace=case.space, action="event.certificate_reissued").exists()


@pytest.mark.parametrize("status", ["pending", "failed", "rendering", "active", "issued_revoked"])
def test_cleanup_never_deletes_or_credits_non_abandoned_artifacts(
    status, certificate_io, django_capture_on_commit_callbacks,
):
    case = certificate_case(f"cleanup-protect-{status}")
    certificate = move_to(case.certificate, "active" if status == "issued_revoked" else status)
    if status == "issued_revoked":
        with django_capture_on_commit_callbacks(execute=True):
            certificates.revoke(certificate, actor=case.actor, reason="staff_revoked")
    case.space.refresh_from_db()
    before_storage = case.space.storage_bytes_used
    before_row = EventAttendanceCertificate.objects.filter(pk=certificate.pk).values().get()

    certificate_cleanup.cleanup_abandoned_certificate(certificate.pk)

    certificate_io.cleanup.assert_not_called()
    case.space.refresh_from_db()
    assert case.space.storage_bytes_used == before_storage
    assert EventAttendanceCertificate.objects.filter(pk=certificate.pk).values().get() == before_row


def test_cleanup_errors_are_logged_and_do_not_block_revocation(
    certificate_io, django_capture_on_commit_callbacks, caplog,
):
    case = certificate_case("cleanup-error-revoke")
    certificate_io.cleanup.side_effect = OSError("storage offline")
    with django_capture_on_commit_callbacks(execute=True):
        revoked = certificates.revoke(case.certificate, actor=case.actor, reason="staff_revoked")

    revoked.refresh_from_db()
    assert revoked.status == "revoked"
    assert certificate_io.cleanup.call_count == 2
    assert "event_certificate_abandoned_cleanup_failed" in caplog.text
    assert AuditLog.objects.filter(action="event.certificate_revoked", target_id=str(revoked.pk)).exists()


@pytest.mark.django_db(transaction=True)
def test_cleanup_error_never_masks_cancelled_activation_error(certificate_io, caplog):
    case = certificate_case("cleanup-error-render")
    certificate_io.cleanup.side_effect = OSError("storage offline")

    def cancel_then_store(key, payload):
        services.cancel(case.event, actor=case.actor, notify=False)
        return certificate_io.store(key, payload)

    certificate_io.upload.side_effect = cancel_then_store
    with pytest.raises(EventInvalidTransition, match="published or completed"):
        certificates.render_certificate(case.certificate)

    case.certificate.refresh_from_db(); case.space.refresh_from_db()
    assert case.certificate.status == "revoked"
    assert case.space.storage_bytes_used == 0
    assert not rendered_audits(case).exists()
    assert certificate_io.cleanup.call_count == 4
    assert "event_certificate_abandoned_cleanup_failed" in caplog.text
