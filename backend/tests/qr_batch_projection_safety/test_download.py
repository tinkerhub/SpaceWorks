import pytest

from tests.qr_batch_projection_safety.helpers import (
    collect, detail_url, item_rows, move, read_state,
)
from tests.qr_batch_projection_safety.zip_helpers import (
    NO_PRINTABLE, assert_owned_zip, owned_pair,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_a_only_partial_zip_contains_exact_owned_svgs_without_rewriting_history(lab, kind):
    moved = collect(lab, kind=kind)
    owned = owned_pair(lab)
    snapshots = item_rows(lab.batch)
    move(lab, moved, kind)
    before = read_state()

    response = lab.client.get(f"{detail_url(lab)}/download")

    assert_owned_zip(response, lab, owned)
    assert item_rows(lab.batch) == snapshots
    assert read_state() == before


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_all_moved_api_refuses_empty_zip_and_preserves_history(lab, kind):
    moved = collect(lab, kind=kind)
    snapshots = item_rows(lab.batch)
    move(lab, moved, kind)
    before = read_state()

    response = lab.client.get(f"{detail_url(lab)}/download")

    assert response.status_code == 400
    assert response.json() == [NO_PRINTABLE]
    assert response["Content-Type"] == "application/json"
    assert "Content-Disposition" not in response
    assert item_rows(lab.batch) == snapshots
    assert read_state() == before


def test_empty_api_batch_refuses_download_without_side_effects(lab):
    before = read_state()
    response = lab.client.get(f"{detail_url(lab)}/download")
    assert response.status_code == 400
    assert response.json() == [NO_PRINTABLE]
    assert "Content-Disposition" not in response
    assert read_state() == before


def test_full_owned_api_zip_remains_usable_and_b_only_cannot_download(lab):
    owned = owned_pair(lab)
    before = read_state()
    assert_owned_zip(lab.client.get(f"{detail_url(lab)}/download"), lab, owned)
    refused = lab.b_client.get(f"{detail_url(lab)}/download")
    assert refused.status_code == 404
    assert refused["Content-Type"] == "application/json"
    assert "Content-Disposition" not in refused
    assert read_state() == before
