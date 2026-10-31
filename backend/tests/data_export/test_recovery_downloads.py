from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.data_export import services, storage
from apps.data_export.models import DataExportJob
from tests.data_export.recovery_test_helpers import events, make_job, recovery_case
from tests.data_export.test_api import download_path

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("fidelity", ("REDACTED", "PORTABLE"))
@pytest.mark.parametrize("retention_seconds", (15, 3600), ids=("retention-cap", "token-cap"))
def test_download_token_ends_at_earlier_of_ttl_and_archive_retention(
    recovery_case, settings, monkeypatch, fidelity, retention_seconds,
):
    now = timezone.now()
    settings.DATA_EXPORT_DOWNLOAD_TTL_SECONDS = 60
    monkeypatch.setattr(services.timezone, "now", lambda: now)
    job = make_job(
        recovery_case, fidelity=fidelity, status=DataExportJob.Status.AVAILABLE,
        expires_at=now + timedelta(seconds=retention_seconds),
    )

    token, expires_at = services.issue_download_token(job, recovery_case.actor)

    job.refresh_from_db()
    assert expires_at == now + timedelta(seconds=min(60, retention_seconds))
    assert job.download_token_expires_at == expires_at
    assert job.download_token_consumed_at is None
    assert token not in str(events(job, "data_export.download_url_issued").get().meta)


@pytest.mark.parametrize("fidelity", ("REDACTED", "PORTABLE"))
@pytest.mark.parametrize("after_seconds", (0, 1), ids=("at-expiry", "after-expiry"))
def test_archive_expiry_refuses_legacy_long_lived_token_without_consuming_or_reading(
    recovery_case, monkeypatch, fidelity, after_seconds,
):
    now = timezone.now()
    deadline = now + timedelta(seconds=10)
    job = make_job(
        recovery_case, fidelity=fidelity, status=DataExportJob.Status.AVAILABLE,
        expires_at=deadline,
    )
    token, _ = services.issue_download_token(job, recovery_case.actor)
    # Simulate a token issued before retention clamping was introduced.
    DataExportJob.objects.filter(pk=job.pk).update(
        download_token_expires_at=deadline + timedelta(hours=1),
    )
    monkeypatch.setattr(services.timezone, "now", lambda: deadline + timedelta(seconds=after_seconds))
    reads = []
    monkeypatch.setattr(storage, "open_archive", lambda key: reads.append(key))

    response = APIClient().get(download_path(job, token))

    assert response.status_code == 404
    with pytest.raises(services.DownloadTokenError):
        services.consume_download_token(job.pk, token)
    with pytest.raises(ValidationError):
        services.issue_download_token(job, recovery_case.actor)
    job.refresh_from_db()
    assert job.download_token_consumed_at is None
    assert job.download_token_digest
    assert events(job, "data_export.downloaded").count() == 0
    assert events(job, "data_export.download_url_issued").count() == 1
    assert reads == []


@pytest.mark.parametrize("fidelity", ("REDACTED", "PORTABLE"))
def test_token_can_be_consumed_immediately_before_archive_expiry(
    recovery_case, monkeypatch, fidelity,
):
    deadline = timezone.now() + timedelta(seconds=10)
    job = make_job(
        recovery_case, fidelity=fidelity, status=DataExportJob.Status.AVAILABLE,
        expires_at=deadline,
    )
    token, _ = services.issue_download_token(job, recovery_case.actor)
    just_before = deadline - timedelta(microseconds=1)
    monkeypatch.setattr(services.timezone, "now", lambda: just_before)

    assert services.consume_download_token(job.pk, token).pk == job.pk

    job.refresh_from_db()
    assert job.download_token_consumed_at == just_before
    assert events(job, "data_export.downloaded").count() == 1
