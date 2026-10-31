"""Byte publication contracts; these tests need neither SQL nor a provider."""
from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace

import pytest
from botocore.exceptions import ParamValidationError

from apps import object_publication as publication
from apps.evidence.storage import StorageUnavailable
from tests.atomic_publication.store import Store, error, png


@dataclass
class Metadata:
    size: int
    content_type: str


def validate(observed):
    assert observed.data().startswith(b"%PDF-")
    assert observed.content_type == "application/pdf"
    return Metadata(observed.size, observed.content_type)


def publish(store, validator=validate, maximum=128):
    return publication.publish(store, bucket="private", key="final",
                               staging_key="staging/final", max_bytes=maximum,
                               validator=validator)


def test_same_size_rewrite_after_snapshot_publishes_original_get_bytes_and_mime(monkeypatch):
    store, spools = Store(), []
    original = b"%PDF-original"
    store.seed("staging/final", original, " Application/PDF ")
    factory = publication.SpooledTemporaryFile

    def tracked_spool(**kwargs):
        spool = factory(**kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(publication, "SpooledTemporaryFile", tracked_spool)
    store.before_put = lambda kwargs: store.seed("staging/final", b"%PDF-replaced", "text/plain")
    result = publish(store)
    assert store.objects["final"][:2] == (original, "application/pdf")
    assert (result.size, result.content_type) == (len(original), "application/pdf")
    puts = [args for name, args in store.calls if name == "put"]
    assert len(puts) == 1 and puts[0]["Metadata"] == {"origin": "same-get"}
    assert puts[0]["Body"] in spools and puts[0]["IfNoneMatch"] == "*"
    assert sum(name == "get" and args["Key"] == "staging/final" for name, args in store.calls) == 1
    assert all(stream.closed for stream in store.streams + spools)


@pytest.mark.parametrize("size", [0, 129], ids=["empty", "max-plus-one"])
def test_actual_size_rejected_before_validation_or_publication(size):
    store = Store()
    store.seed("staging/final", b"x" * size)
    with pytest.raises(publication.InvalidObjectSize) as caught:
        publish(store, lambda _: pytest.fail("invalid length reached validator"))
    assert caught.value.size == size
    assert "final" not in store.objects and not store.put_bodies
    assert all(body.closed for body in store.streams)


def test_snapshot_bounds_reads_and_closes_spool_on_size_failure(monkeypatch):
    requested, spools = [], []

    class TrackingBody(BytesIO):
        def read(self, count=-1):
            requested.append(count)
            return super().read(count)

    body = TrackingBody(b"x" * 10000)
    factory = publication.SpooledTemporaryFile

    def tracked(**kwargs):
        spool = factory(**kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(publication, "SpooledTemporaryFile", tracked)
    client = SimpleNamespace(get_object=lambda **kw: {"Body": body})
    with pytest.raises(publication.InvalidObjectSize):
        with publication.snapshot(client, "b", "k", 17):
            pytest.fail("oversized snapshot exposed")
    assert requested == [18]
    assert body.closed and all(spool.closed for spool in spools)


def test_legacy_valid_final_wins_without_reading_replayed_staging():
    store = Store()
    winner = b"%PDF-legacy"
    store.seed("final", winner)
    store.seed("staging/final", b"%PDF-evil-replay")
    result = publish(store)
    assert result.size == len(winner)
    assert store.objects["final"][0] == winner
    assert [name for name, _ in store.calls] == ["get"]


def test_412_uses_actual_winner_metadata_not_losing_staging():
    store = Store()
    store.seed("staging/final", b"%PDF-loser")
    from apps.evidence.image_validation import image_mime_from_bytes
    winner = png()
    store.before_put = lambda kwargs: store.seed("final", winner, "image/png")
    def documents_or_image(observed):
        actual = "application/pdf" if observed.data().startswith(b"%PDF-") else image_mime_from_bytes(observed.data())
        assert actual == observed.content_type
        return Metadata(observed.size, actual)
    result = publish(store, documents_or_image)
    assert (result.size, result.content_type) == (len(winner), "image/png")
    assert store.objects["final"][0] == winner
    assert len(store.put_bodies) == 1 and all(body.closed for body in store.streams + store.put_bodies)


def test_412_missing_winner_refuses_instead_of_republishing():
    store = Store()
    store.seed("staging/final", b"%PDF-source")
    store.before_put = lambda kwargs: (_ for _ in ()).throw(error("PreconditionFailed", 412))
    with pytest.raises(StorageUnavailable):
        publish(store)
    assert len(store.put_bodies) == 1 and "final" not in store.objects


def test_409_retries_same_snapshot_bounded_then_typed_busy():
    store = Store()
    store.seed("staging/final", b"%PDF-source")
    store.before_put = lambda kwargs: (_ for _ in ()).throw(error("ConditionalRequestConflict", 409))
    with pytest.raises(StorageUnavailable):
        publish(store)
    assert len(store.put_bodies) == 3
    assert len({id(body) for body in store.put_bodies}) == 1
    assert all(body.closed for body in store.streams + store.put_bodies)


@pytest.mark.parametrize(("code", "status"), [
    ("AccessDenied", 403), ("InternalError", 500), ("NoSuchBucket", 404),
    ("NoSuchKey", 403), ("NoSuchKey", 500), ("UnknownProviderFailure", 418),
])
def test_nonmissing_get_errors_fail_closed_without_staging_or_write(code, status):
    store = Store()
    store.before_get = lambda kwargs: (_ for _ in ()).throw(error(code, status))
    with pytest.raises(StorageUnavailable):
        publish(store)
    assert len(store.calls) == 1 and store.calls[0][0] == "get"


@pytest.mark.parametrize("failure", [
    error("AccessDenied", 403), error("InternalError", 500), error("NoSuchBucket", 404),
    error("Unknown", 400), ParamValidationError(report="Unknown parameter IfNoneMatch"),
    TypeError("unsupported SDK argument"),
], ids=["403", "500", "bucket-404", "unknown", "sdk-parameter", "sdk-unsupported"])
def test_put_failures_never_fallback_to_unconditional_copy(failure):
    store = Store()
    store.seed("staging/final", b"%PDF-source")
    store.before_put = lambda kwargs: (_ for _ in ()).throw(failure)
    with pytest.raises(StorageUnavailable):
        publish(store)
    assert len(store.put_bodies) == 1 and "final" not in store.objects
    assert all(body.closed for body in store.streams + store.put_bodies)


@pytest.mark.parametrize("response", [None, {}, {"Body": object()}, {"Body": BytesIO(b"x")}],
                         ids=["not-dict", "missing-body", "unreadable", "validator-error"])
def test_malformed_response_and_validator_failure_close_resources(response):
    client = SimpleNamespace(get_object=lambda **kwargs: response)
    expected = AssertionError if isinstance(response, dict) and isinstance(response.get("Body"), BytesIO) else StorageUnavailable
    with pytest.raises(expected):
        publish(client)
    if isinstance(response, dict) and isinstance(response.get("Body"), BytesIO):
        assert response["Body"].closed


def test_malformed_body_bytes_fail_typed_and_close():
    body = SimpleNamespace(read=lambda n: "not bytes", close=lambda: closed.append(True))
    closed = []
    with pytest.raises(StorageUnavailable):
        with publication.snapshot(SimpleNamespace(get_object=lambda **kw: {"Body": body}), "b", "k", 10):
            pytest.fail("malformed body exposed")
    assert closed == [True]


def test_successful_put_without_readable_final_refuses_metadata_result():
    store = Store()
    store.seed("staging/final", b"%PDF-source")
    def unreadable_winner(kwargs):
        if kwargs["Key"] == "final" and "final" in store.objects:
            raise error("AccessDenied", 403)
    store.before_get = unreadable_winner
    with pytest.raises(StorageUnavailable):
        publish(store)
    assert store.objects["final"][0] == b"%PDF-source"
    assert len(store.put_bodies) == 1
    assert all(stream.closed for stream in store.streams + store.put_bodies)


def test_conflict_winner_is_validated_even_when_source_was_valid():
    store = Store()
    store.seed("staging/final", b"%PDF-source")
    store.before_put = lambda kwargs: store.seed("final", b"<html>invalid winner</html>", "text/html")
    with pytest.raises(AssertionError):
        publish(store)
    assert store.objects["final"][0] == b"<html>invalid winner</html>"
    assert len(store.put_bodies) == 1


def test_stream_read_failure_closes_both_body_and_spool(monkeypatch):
    spools, closed = [], []
    factory = publication.SpooledTemporaryFile
    def track(**kwargs):
        spool = factory(**kwargs)
        spools.append(spool)
        return spool
    monkeypatch.setattr(publication, "SpooledTemporaryFile", track)
    def failed_read(count):
        raise OSError("transport failed")
    body = SimpleNamespace(read=failed_read, close=lambda: closed.append(True))
    client = SimpleNamespace(get_object=lambda **kw: {"Body": body, "ContentType": "application/pdf"})
    with pytest.raises(StorageUnavailable):
        with publication.snapshot(client, "b", "k", 128):
            pytest.fail("unreadable stream yielded")
    assert closed == [True] and all(spool.closed for spool in spools)


def test_409_then_success_reuses_original_snapshot_despite_staging_replay():
    store = Store()
    original = b"%PDF-original"
    store.seed("staging/final", original)
    attempts = []
    def conflict_once(kwargs):
        attempts.append(kwargs["Body"])
        if len(attempts) == 1:
            store.seed("staging/final", b"%PDF-replaced")
            raise error("ConditionalRequestConflict", 409)
    store.before_put = conflict_once
    assert publish(store).size == len(original)
    assert len(attempts) == 2 and attempts[0] is attempts[1]
    assert store.objects["final"][0] == original
