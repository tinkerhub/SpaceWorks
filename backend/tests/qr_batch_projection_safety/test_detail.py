import pytest

from apps.boxes.rebind import rebind_qr_target
from apps.boxes.services import revoke_qr_code
from tests.qr_batch_projection_safety.helpers import (
    assert_qr, collect, detail_url, item_rows, move, read_state, snapshot_fields,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_moved_live_qr_is_null_for_a_only_both_and_global_readers(lab, kind):
    original = collect(lab, kind=kind)
    owned = collect(lab, label="A still owns this", order=10)
    snapshots = item_rows(lab.batch)
    move(lab, original, kind)
    before = read_state()

    for client in (lab.client, lab.both_client, lab.global_client):
        response = client.get(detail_url(lab))
        assert response.status_code == 200, response.data
        body = response.json()
        assert (body["id"], body["makerspace"], body["title"]) == (
            lab.batch.pk, lab.home.pk, "Historical A batch",
        )
        assert [item["id"] for item in body["items"]] == [owned.item.pk, original.item.pk]
        historical = body["items"][1]
        # Exact object equality forbids every fresh B payload/target/timestamp field,
        # while deliberately retaining the asset's historical numeric target ID.
        assert historical == {**snapshot_fields(original.item), "qr_code": None}
        current = body["items"][0]
        assert {key: value for key, value in current.items() if key != "qr_code"} == snapshot_fields(owned.item)
        assert_qr(current["qr_code"], owned.code)

    denied = lab.b_client.get(detail_url(lab))
    assert denied.status_code == 404
    assert denied.json() == {"detail": "No QrPrintBatch matches the given query."}
    assert item_rows(lab.batch) == snapshots
    assert read_state() == before


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("rebound", [False, True], ids=["unchanged", "same-maker-rebind"])
def test_same_maker_full_nested_qr_preserves_historical_target(lab, kind, rebound):
    original = collect(lab, kind=kind)
    snapshots = item_rows(lab.batch)
    if rebound:
        replacement = collect(lab, kind=kind, label="Replacement target", order=30)
        # A new target must have no active QR. Revoke through the canonical service.
        revoke_qr_code(lab.actor, replacement.code)
        all_snapshots = item_rows(lab.batch)
        rebind_qr_target(lab.actor, original.code.pk, {
            "target_type": kind, "target_id": replacement.target.pk,
        })
        original.code.refresh_from_db()
        assert original.code.target_id == replacement.target.pk
        assert item_rows(lab.batch) == all_snapshots
    before = read_state()
    response = lab.client.get(detail_url(lab))
    assert response.status_code == 200, response.data
    item = next(item for item in response.json()["items"] if item["id"] == original.item.pk)
    assert {key: value for key, value in item.items() if key != "qr_code"} == snapshot_fields(original.item)
    assert_qr(item["qr_code"], original.code)
    assert item_rows(lab.batch)[0] == snapshots[0]
    assert read_state() == before
