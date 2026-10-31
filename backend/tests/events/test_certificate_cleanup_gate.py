"""Deferred certificate cleanup respects the retained tenant's write boundary."""

from uuid import uuid4

import pytest

from apps.events import certificate_cleanup, certificate_storage
from apps.events.models import EventAttendanceCertificate
from apps.events.services_certificates import revoke
from tests.backup.e7_reservation_test_helpers import persist_restore_state
from tests.events.certificate_recovery_helpers import certificate_case, certificate_io
from tests.tenant_migration.source_gate_helpers import close_gate


pytestmark = pytest.mark.django_db


def abandoned_case(slug):
    case = certificate_case(slug)
    revoke(case.certificate, actor=case.actor, reason="staff_revoked")
    case.certificate.refresh_from_db()
    return case


@pytest.mark.parametrize("refusal", ["frozen", "not_restored"])
def test_cleanup_skips_closed_or_not_restored_source(refusal, certificate_io, caplog):
    case = abandoned_case(f"cleanup-gate-{refusal}")
    if refusal == "frozen":
        close_gate(case.space, case.actor)
    else:
        persist_restore_state(
            {"component_ids": [str(uuid4())]}, makerspace_id=case.space.pk,
        )
    before = EventAttendanceCertificate.objects.filter(pk=case.certificate.pk).values().get()

    with caplog.at_level("INFO"):
        certificate_cleanup.cleanup_abandoned_certificate(case.certificate.pk)

    certificate_io.cleanup.assert_not_called()
    assert "event_certificate_cleanup_skipped_closed_source_gate" in caplog.text
    assert EventAttendanceCertificate.objects.filter(pk=case.certificate.pk).values().get() == before
    case.space.refresh_from_db()
    assert case.space.storage_bytes_used == 0


def test_open_source_cleanup_deletes_only_unique_abandoned_keys_without_credit(certificate_io):
    case = abandoned_case("cleanup-gate-open")
    key = case.certificate.object_key
    certificate_io.objects.update({key: b"late final", certificate_storage.staging_key(key): b"late stage"})
    before = EventAttendanceCertificate.objects.filter(pk=case.certificate.pk).values().get()

    certificate_cleanup.cleanup_abandoned_certificate(case.certificate.pk)

    assert certificate_io.objects == {}
    assert [call.kwargs["key"] for call in certificate_io.cleanup.call_args_list] == [
        key, certificate_storage.staging_key(key),
    ]
    case.space.refresh_from_db()
    assert case.space.storage_bytes_used == 0
    assert EventAttendanceCertificate.objects.filter(pk=case.certificate.pk).values().get() == before
