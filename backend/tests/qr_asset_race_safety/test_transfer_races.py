"""Existing ACTIVE QR: actual AssetQr HTTP versus canonical rebind in both orders."""
import pytest
from django.db import transaction

from apps.makerspaces.models import Makerspace
from tests.box_parent_safety.pg_helpers import (
    assert_maker_mode, blocked_by, maker_lock, workers,
)
from tests.qr_asset_race_safety.helpers import (
    assert_lock_order, assert_no_domain_write, asset_http, asset_lock, backend_pid,
    code, dto, lab, move_http, qr_lock, record_sql, state,
)
from tests.qr_asset_race_safety.move_assertions import assert_moved

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("wait", ["maker", "qr"])
def test_transfer_wins_after_asset_qr_cached_original_tenant(lab, wait, record_property):
    qr = code(lab)
    before = state()
    with workers() as start:
        if wait == "maker":
            # NK conflicts with AssetQr NK but permits the mover's FK KEY SHARE.
            with transaction.atomic():
                Makerspace.objects.select_for_update(no_key=True).get(pk=lab.home.pk)
                api = start(lambda: asset_http(lab))
                pending = blocked_by(api, backend_pid())
                assert_maker_mode(pending, "FOR NO KEY UPDATE")
                # Reaching Maker proves AssetQr already cached its initial A asset.
                mover = start(lambda: move_http(lab, qr))
                moved = assert_moved(lab, qr, before, mover.finish())
                assert not pending.completed  # mover committed under the real NK holder
                assert_no_domain_write(api.statements)
        else:
            mover = start(lambda: move_http(lab, qr), pause=qr_lock)
            mover.paused()
            api = start(lambda: asset_http(lab))
            pending = blocked_by(api, mover.pid, qr_lock)
            maker = next(s for s in api.statements if maker_lock(s))
            assert_maker_mode(maker, "FOR NO KEY UPDATE")
            assert maker.completed  # mover must finish while AssetQr holds Maker NK
            assert not any(asset_lock(s) for s in api.statements)
            moved = assert_moved(lab, qr, before, mover.finish())
        response = api.finish()
    record_property("wait_edge", repr({"waiter": api.pid, "sql": pending.sql,
                                       "params": pending.params, "mover": mover.pid}))
    assert response.status_code == 404, response.data
    assert response.data
    assert state() == moved  # no A orphan, no false qr.created, no quantity changes
    assert_no_domain_write(api.statements)
    assert_lock_order(api)
    record_sql(record_property, api, "asset_qr_full_sql")
    record_sql(record_property, mover, "canonical_move_full_sql")
    assert next(i for i, s in enumerate(mover.statements) if qr_lock(s)) < next(
        i for i, s in enumerate(mover.statements) if asset_lock(s))


def test_asset_qr_reuse_wins_then_allows_legitimate_canonical_move(lab, record_property):
    qr = code(lab)
    before, expected_dto = state(), dto(qr)
    with workers() as start:
        api = start(lambda: asset_http(lab), pause=qr_lock)
        api.paused()
        assert not any(asset_lock(s) for s in api.statements)
        mover = start(lambda: move_http(lab, qr), pause=qr_lock)
        pending = blocked_by(mover, api.pid, qr_lock)
        record_property("wait_edge", repr({"waiter": mover.pid, "blocker": api.pid,
                                           "sql": pending.sql, "params": pending.params}))
        response = api.finish()
        mover.paused()  # real QR acquired; no move mutation yet
        assert response.status_code == 201, response.data
        assert response.data == expected_dto
        assert response.data["makerspace"] == lab.home.pk
        assert state() == before
        assert_lock_order(api)
        moved = assert_moved(lab, qr, before, mover.finish())
    record_sql(record_property, api, "asset_qr_full_sql")
    record_sql(record_property, mover, "canonical_move_full_sql")
    # The response was coherent at its own linearization; later movement is legal.
    assert state() == moved
