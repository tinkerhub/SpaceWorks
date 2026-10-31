"""Exercise authorization and the real series key/presign builders together."""

from unittest.mock import Mock

import pytest
from django.urls import reverse

from apps.inventory import public_image_storage
from tests.events.test_event_series import (
    client_for,
    create_daily_series,
    make_manager,
    make_space,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def image_case(monkeypatch, settings):
    settings.PUBLIC_IMAGE_BUCKET = "series-covers"
    settings.PUBLIC_IMAGE_URL_TTL_SECONDS = 137
    settings.PUBLIC_IMAGE_MAX_BYTES = 4096
    settings.STORAGE_PRESIGN_METHOD = "post"
    space = make_space("series-image-presign")
    manager = make_manager(space, "series-image-presign-manager")
    series, _created = create_daily_series(space, manager)
    transport = Mock(spec=["generate_presigned_post", "generate_presigned_url"])
    transport.generate_presigned_post.return_value = {
        "url": "https://storage.invalid/upload", "fields": {"policy": "signed-policy"},
    }
    transport.generate_presigned_url.return_value = "https://storage.invalid/signed-put"
    monkeypatch.setattr(public_image_storage, "_public_client", lambda: transport)
    return space, manager, series, transport


@pytest.mark.parametrize("method", ["post", "put"])
@pytest.mark.parametrize("content_type,extension", [
    pytest.param("image/png", "png", id="png"),
    pytest.param("image/jpeg", "jpg", id="jpeg"),
    pytest.param("image/webp", "webp", id="webp"),
])
def test_authorized_series_image_presign_uses_tenant_key_and_allowed_mime(
    image_case, settings, method, content_type, extension
):
    space, manager, series, transport = image_case
    settings.STORAGE_PRESIGN_METHOD = method

    result = client_for(manager).post(
        reverse("admin-event-series-image", kwargs={"pk": series.pk}),
        {"content_type": content_type, "filename": f"cover.{extension}"},
        format="json",
    )

    assert result.status_code == 201, result.data
    key = result.data["object_key"]
    assert key.startswith(f"event-series/{space.pk}/")
    assert key.endswith(f".{extension}")
    if method == "post":
        transport.generate_presigned_post.assert_called_once_with(
            Bucket="series-covers", Key=f"staging/{key}",
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, 4096]],
            ExpiresIn=137,
        )
        transport.generate_presigned_url.assert_not_called()
        assert result.data["url"] == "https://storage.invalid/upload"
        assert result.data["fields"] == {"policy": "signed-policy"}
    else:
        transport.generate_presigned_url.assert_called_once_with(
            "put_object", Params={
                "Bucket": "series-covers", "Key": f"staging/{key}",
                "ContentType": content_type,
            }, ExpiresIn=137,
        )
        transport.generate_presigned_post.assert_not_called()
        assert result.data["method"] == "PUT"
        assert result.data["headers"] == {"Content-Type": content_type}
    series.refresh_from_db()
    assert series.image_key == ""


@pytest.mark.parametrize("guard,expected_status", [
    pytest.param("foreign-tenant", 404, id="foreign-tenant"),
    pytest.param("module-withdrawn", 400, id="module-withdrawn"),
    pytest.param("invalid-mime", 400, id="invalid-mime"),
])
def test_series_image_guards_reject_before_presigning(image_case, guard, expected_status):
    space, manager, series, transport = image_case
    payload = {"content_type": "image/png", "filename": "cover.png"}
    if guard == "foreign-tenant":
        manager = make_manager(make_space("foreign-series-image"), "foreign-image-manager")
    elif guard == "module-withdrawn":
        space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
        space.save(update_fields=["enabled_modules"])
    else:
        payload = {"content_type": "text/html", "filename": "cover.html"}

    result = client_for(manager).post(
        reverse("admin-event-series-image", kwargs={"pk": series.pk}), payload, format="json"
    )

    assert result.status_code == expected_status, result.data
    assert transport.mock_calls == []
