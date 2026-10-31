"""Missing context refuses a debit atomically while retaining the published winner."""
import pytest

from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from tests.document_safety.helpers import accepted_body, cap, finalize, lab, presign, snapshot, usage
from tests.document_quota.helpers import KINDS, clear_identity

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("broken", ["identity", "endpoint", "bucket"])
def test_missing_or_invalid_context_is_typed_503_rolls_back_and_retries_without_put(
    kind, broken, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    body = accepted_body("application/pdf")
    cap(case, len(body) + 900, used=900)
    case.store.seed(case.module.staging_key(key), body)
    endpoint, bucket = settings.AWS_S3_ENDPOINT_URL, settings.AWS_STORAGE_BUCKET_NAME
    if broken == "identity":
        clear_identity()
    elif broken == "endpoint":
        settings.AWS_S3_ENDPOINT_URL = "https://objects.example.test/?unexpected=query"
    else:
        settings.AWS_STORAGE_BUCKET_NAME = ""
    before = snapshot(case)
    result = finalize(case, key)
    assert result.status_code == 503, result.data
    assert result.data == {"detail": "Storage is unavailable.", "code": "storage_unavailable"}
    assert snapshot(case) == before and usage(case) == 900
    assert case.store.objects[key][0] == body
    winner = case.store.objects[key][2]
    puts = len(case.store.put_bodies)
    assert puts == 1
    if broken == "identity":
        assert not DeploymentDatabaseIdentity.objects.exists()  # No runtime seeding.
        DeploymentDatabaseIdentity.objects.create(pk=1)
    settings.AWS_S3_ENDPOINT_URL, settings.AWS_STORAGE_BUCKET_NAME = endpoint, bucket
    case.store.seed(case.module.staging_key(key), b"hostile replay", "text/html")
    result = finalize(case, key)
    assert result.status_code == 201, result.data
    assert usage(case) == 900 + len(body)
    assert case.store.objects[key][2] == winner and len(case.store.put_bodies) == puts
    state, calls = snapshot(case), list(case.store.calls)
    assert finalize(case, key).status_code == 201
    assert snapshot(case) == state and case.store.calls == calls
