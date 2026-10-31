import pytest
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from tests.qr_batch_projection_safety.helpers import collect, item_rows, move, read_state
from tests.qr_batch_projection_safety.zip_helpers import (
    NO_PRINTABLE, assert_owned_zip, owned_pair,
)

pytestmark = pytest.mark.django_db


def native_action(lab):
    client = Client(HTTP_HOST="testserver")
    client.force_login(lab.global_actor)
    url = reverse("admin:operations_qrprintbatch_changelist")
    response = client.post(url, {
        "action": "download_zip_selected", "index": "0",
        ACTION_CHECKBOX_NAME: [str(lab.batch.pk)],
    })
    return response, url


@pytest.mark.parametrize("contents", ["empty", "product", "asset"])
def test_native_empty_or_all_moved_action_reports_error_without_download(lab, contents):
    if contents != "empty":
        moved = collect(lab, kind=contents)
        move(lab, moved, contents)
    before = read_state()

    response, url = native_action(lab)

    assert response.status_code == 302
    assert response["Location"] == url
    assert response.get("Content-Type") != "application/zip"
    assert "Content-Disposition" not in response
    errors = list(get_messages(response.wsgi_request))
    assert len(errors) == 1
    assert errors[0].level == messages.ERROR
    assert NO_PRINTABLE in str(errors[0])
    assert read_state() == before


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_native_partial_action_streams_only_owned_labels(lab, kind):
    moved = collect(lab, kind=kind)
    owned = owned_pair(lab)
    snapshots = item_rows(lab.batch)
    move(lab, moved, kind)
    before = read_state()

    response, _url = native_action(lab)

    assert_owned_zip(response, lab, owned)
    assert list(get_messages(response.wsgi_request)) == []
    assert item_rows(lab.batch) == snapshots
    assert read_state() == before
