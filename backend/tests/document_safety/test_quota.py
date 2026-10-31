"""Exact accepted bytes, finite admission and rollback through actual staff APIs."""
import pytest
from django.urls import reverse

from apps.audit import services as audit
from apps.audit.models import AuditLog
from tests.atomic_publication.store import error
from tests.document_safety.helpers import (
    accepted_body, assert_storage_boundary, cap, fail_after_audit, finalize, lab,
    presign, snapshot, usage,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("method", ["put", "post"])
@pytest.mark.parametrize("mime", ["application/pdf", "image/png"])
def test_accepted_bytes_charge_once_and_same_key_retry_has_no_io(
    kind, method, mime, monkeypatch, settings,
):
    settings.STORAGE_PRESIGN_METHOD = method
    case = lab(monkeypatch, settings, kind)
    data = accepted_body(mime)
    cap(case, len(data) + 7, used=7)
    key, upload = presign(case, mime)
    name, args = case.store.calls[-1]
    assert args["Key"] == case.module.staging_key(key)
    if method == "put":
        assert name == "presign-put" and upload["method"] == "PUT"
        assert upload["headers"] == {"Content-Type": mime}
        assert args["ContentType"] == mime
    else:
        assert name == "presign-post"
        assert args["Fields"] == {"Content-Type": mime}
        assert ["content-length-range", 1, 100000] in args["Conditions"]
    case.store.seed(case.module.staging_key(key), data, mime)
    case.store.boundary = lambda: assert_storage_boundary(case)
    before = AuditLog.objects.count()
    first = finalize(case, key)
    assert first.status_code == 201, first.data
    row = case.model.objects.get(object_key=key)
    assert row.uploaded_by_id == case.actor.pk
    assert usage(case) == 7 + len(data)
    assert AuditLog.objects.count() == before + 1
    assert case.store.objects[key][:2] == (data, mime)
    assert case.module.staging_key(key) not in case.store.objects
    if kind != "receipt":
        assert (row.size_bytes, row.content_type) == (len(data), mime)
    calls, state = list(case.store.calls), snapshot(case)
    repeated = finalize(case, key)
    assert repeated.status_code == 201 and repeated.data["id"] == first.data["id"]
    assert snapshot(case) == state and case.store.calls == calls
    assert len(case.store.put_bodies) == 1
    assert all(stream.closed for stream in case.store.streams + case.store.put_bodies)


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("winner_mode", ["existing", "conditional-conflict"])
@pytest.mark.parametrize("mime", ["application/pdf", "image/png"])
@pytest.mark.parametrize("method", ["put", "post"])
def test_cap_uses_final_winner_size_even_when_staging_size_differs(
    kind, winner_mode, mime, method, monkeypatch, settings,
):
    settings.STORAGE_PRESIGN_METHOD = method
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case, mime)
    loser, winner = accepted_body(mime), accepted_body(mime, variant=True)
    assert len(loser) != len(winner)
    cap(case, len(winner) + 11, used=11)
    case.store.seed(case.module.staging_key(key), loser, mime)
    if winner_mode == "existing":
        case.store.seed(key, winner, mime)
    else:
        case.store.before_put = lambda kwargs: case.store.seed(key, winner, mime)
    response = finalize(case, key)
    assert response.status_code == 201, response.data
    assert usage(case) == 11 + len(winner)
    assert case.store.objects[key][:2] == (winner, mime)
    assert case.model.objects.filter(object_key=key).count() == 1
    if kind != "receipt":
        row = case.model.objects.get(object_key=key)
        assert (row.size_bytes, row.content_type) == (len(winner), mime)


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("method", ["put", "post"])
def test_finite_cap_refusal_keeps_published_winner_without_metadata_debit_audit(
    kind, method, monkeypatch, settings,
):
    settings.STORAGE_PRESIGN_METHOD = method
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    body = accepted_body("application/pdf")
    case.store.seed(case.module.staging_key(key), body)
    cap(case, len(body) + 4, used=5)
    before = snapshot(case)
    response = finalize(case, key)
    assert response.status_code == 400 and "limit" in response.data
    assert snapshot(case) == before
    assert case.store.objects[key][0] == body
    winner_version = case.store.objects[key][2]
    # Retry after capacity is raised must validate the retained final, not replay.
    cap(case, len(body) + 5, used=5)
    case.store.seed(case.module.staging_key(key), b"<html>replay</html>", "text/html")
    puts = len(case.store.put_bodies)
    assert finalize(case, key).status_code == 201
    assert usage(case) == len(body) + 5
    assert case.store.objects[key][2] == winner_version
    assert len(case.store.put_bodies) == puts


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
def test_real_audit_insert_failure_rolls_back_debit_and_metadata_then_retry(
    kind, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    body = accepted_body("application/pdf")
    cap(case, len(body) + 9, used=9)
    case.store.seed(case.module.staging_key(key), body)
    case.store.boundary = lambda: assert_storage_boundary(case)
    action = "procurement.receipt_added" if kind == "receipt" else "warranty.document_added"
    before = snapshot(case)
    original, inserted = fail_after_audit(monkeypatch, action)
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        finalize(case, key)
    assert inserted and snapshot(case) == before
    assert case.store.objects[key][0] == body
    monkeypatch.setattr(audit, "record", original)
    calls = len(case.store.calls)
    case.store.seed(case.module.staging_key(key), b"malicious replay", "text/html")
    response = finalize(case, key)
    assert response.status_code == 201, response.data
    assert usage(case) == 9 + len(body)
    assert AuditLog.objects.filter(action=action).count() == 1
    reads = [args["Key"] for name, args in case.store.calls[calls:] if name == "get"]
    assert reads == [key], reads
    assert len(case.store.put_bodies) == 1


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("failure_at", ["get", "put"])
def test_provider_failure_precedes_metadata_debit_and_audit(kind, failure_at, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    case.store.seed(case.module.staging_key(key), accepted_body("application/pdf"))
    def unavailable(kwargs):
        raise error("AccessDenied", 403)
    setattr(case.store, f"before_{failure_at}", unavailable)
    before = snapshot(case)
    response = finalize(case, key)
    assert response.status_code == 503, response.data
    assert snapshot(case) == before and key not in case.store.objects


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("charged", [False, True])
def test_delete_never_speculates_storage_credit_for_legacy_or_charged_metadata(
    kind, charged, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    cap(case, 1000000, used=900)
    body = accepted_body("application/pdf")
    if charged:
        case.store.seed(case.module.staging_key(key), body)
        assert finalize(case, key).status_code == 201
        row = case.model.objects.get(object_key=key)
    else:
        fields = {"to_buy_item": case.target} if kind == "receipt" else {
            "warranty": case.target, "original_filename": "legacy.pdf",
            "size_bytes": 800, "content_type": "application/pdf",
        }
        row = case.model.objects.create(object_key=key, uploaded_by=case.actor, **fields)
        case.store.seed(key, body)
    before = usage(case)
    case.store.boundary = lambda: assert_storage_boundary(case)
    response = case.client.delete(reverse(f"{case.prefix}-detail", kwargs={"pk": row.pk}))
    assert response.status_code == 204
    assert not case.model.objects.filter(pk=row.pk).exists()
    assert key not in case.store.objects
    assert before == 900 + (len(body) if charged else 0)
    assert usage(case) == 900
