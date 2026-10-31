"""Seven production finalizers against GET/conditional PUT, without ORM or S3."""
from importlib import import_module
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.evidence.storage import StorageUnavailable
from tests.atomic_publication.store import Store, error, png

SURFACES = ["machines", "service", "maintenance", "warranty", "procurement", "inventory", "bookings"]


def surface(name, monkeypatch, settings, data=None, mime=None):
    module = import_module({
        "service": "apps.machines.service_storage",
        "inventory": "apps.inventory.public_image_storage",
    }.get(name, f"apps.{name}.storage"))
    image = name in {"inventory", "bookings"}
    maximum = "PUBLIC_IMAGE_MAX_BYTES" if image else {
        "warranty": "WARRANTY_DOC_MAX_BYTES", "procurement": "PROCUREMENT_RECEIPT_MAX_BYTES",
    }.get(name, "MACHINE_DOC_MAX_BYTES")
    setattr(settings, maximum, 128)
    key = "final.png" if image else "final.pdf"
    payload = png() if image else b"%PDF-1.7\nreal document"
    content_type = "image/png" if image else "application/pdf"
    if name == "service":
        key, payload, content_type = "machine/1/2/service/token", b"solid cube\nendsolid", "model/stl"
        file = SimpleNamespace(object_key=key, original_filename="part.stl", content_type=content_type,
                               file_policy_name="documents", file_policy_version=1)
        from apps.machines.service_file_policies import get_policy
        # Use the installed immutable policy, rather than a permissive fake validator.
        policy = get_policy("documents", 1)
        file.file_policy_name, file.file_policy_version = policy.name, policy.version
        invoke = lambda: module.prepare_file(file, max_bytes=128)
    elif image:
        invoke = lambda: module.finalize_upload(key)
    else:
        invoke = lambda: module.prepare_upload(key)
    store = Store()
    store.seed(module.staging_key(key), payload if data is None else data, content_type if mime is None else mime)
    monkeypatch.setattr(module, "_client", lambda: store)
    return module, store, key, payload, content_type, invoke


@pytest.mark.parametrize("name", SURFACES)
def test_real_finalizer_conditionally_publishes_validated_domain_bytes(name, monkeypatch, settings):
    module, store, key, data, mime, invoke = surface(name, monkeypatch, settings)
    result = invoke()
    assert result.size == len(data)
    if hasattr(result, "content_type"):
        assert result.content_type == mime
    else:
        assert result.status == "ok"
    assert store.objects[key][:2] == (data, mime)
    assert module.staging_key(key) not in store.objects
    puts = [kw for operation, kw in store.calls if operation == "put"]
    assert len(puts) == 1 and puts[0]["IfNoneMatch"] == "*"
    assert puts[0]["ContentType"] == mime
    assert all(body.closed for body in store.streams + store.put_bodies)


@pytest.mark.parametrize("name", SURFACES)
@pytest.mark.parametrize("bad", ["mime", "signature", "empty", "oversize"])
def test_real_finalizer_rejects_before_publishing(name, bad, monkeypatch, settings):
    module, store, key, data, mime, invoke = surface(name, monkeypatch, settings)
    payload = {"mime": data, "signature": b"%PDF-disguised" if name == "service" else b"broken bytes", "empty": b"", "oversize": b"x" * 129}[bad]
    store.seed(module.staging_key(key), payload, "text/html" if bad == "mime" else mime)
    if name in {"inventory", "bookings"}:
        assert invoke().status == {"mime": "invalid", "signature": "invalid",
                                   "empty": "empty", "oversize": "too_large"}[bad]
    else:
        with pytest.raises(ValidationError):
            invoke()
    assert key not in store.objects and not store.put_bodies
    assert all(body.closed for body in store.streams)


@pytest.mark.parametrize("name", SURFACES)
def test_real_finalizer_provider_failure_cannot_publish_or_delete_final(name, monkeypatch, settings):
    _module, store, key, _data, _mime, invoke = surface(name, monkeypatch, settings)
    store.before_put = lambda kw: (_ for _ in ()).throw(error("AccessDenied", 403))
    with pytest.raises(StorageUnavailable):
        invoke()
    assert key not in store.objects
    assert len(store.put_bodies) == 1
    assert not any(op == "delete" for op, _ in store.calls)


@pytest.mark.parametrize("name", ["inventory", "bookings"])
def test_decode_invalid_image_never_published(name, monkeypatch, settings):
    _module, store, key, _data, _mime, invoke = surface(name, monkeypatch, settings, data=png()[:30])
    assert invoke().status == "invalid"
    assert key not in store.objects and not store.put_bodies


@pytest.mark.parametrize("name", ["inventory", "bookings"])
def test_attach_polls_transient_missing_staging_with_bounded_sleep(name, monkeypatch, settings):
    module, store, key, data, mime, invoke = surface(name, monkeypatch, settings)
    staging = module.staging_key(key)
    store.objects.pop(staging)
    sleeps = []

    def upload_after_first_poll(delay):
        sleeps.append(delay)
        store.seed(staging, data, mime)

    monkeypatch.setattr("apps.inventory.public_image_publication.time.sleep", upload_after_first_poll)
    assert invoke().status == "ok"
    assert sleeps == [0.2] and store.objects[key][0] == data


@pytest.mark.parametrize("name", ["inventory", "bookings"])
def test_missing_image_poll_stops_after_ten_attempts(name, monkeypatch, settings):
    module, store, key, _data, _mime, invoke = surface(name, monkeypatch, settings)
    store.objects.pop(module.staging_key(key))
    sleeps = []
    monkeypatch.setattr("apps.inventory.public_image_publication.time.sleep", sleeps.append)
    assert invoke().status == "missing"
    assert sleeps == [0.2] * 9
    assert sum(op == "get" for op, _ in store.calls) == 20
    assert not store.put_bodies


@pytest.mark.parametrize("name", ["inventory", "bookings"])
def test_decompression_bomb_is_rejected_before_publication(name, monkeypatch, settings):
    from tests.test_image_validation_decode_errors import _png_with_dimensions
    _module, store, key, _data, _mime, invoke = surface(
        name, monkeypatch, settings, data=_png_with_dimensions(100000, 100000),
    )
    assert invoke().status == "invalid"
    assert key not in store.objects and not store.put_bodies
    assert all(body.closed for body in store.streams)
