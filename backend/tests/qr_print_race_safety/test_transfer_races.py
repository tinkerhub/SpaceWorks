"""Actual item-add HTTP versus canonical cross-maker PRODUCT/ASSET movement."""
import pytest
from django.db import connection, transaction

from apps.makerspaces.models import Makerspace
from apps.operations.models import QrPrintBatchItem
from tests.box_parent_safety.pg_helpers import (
    assert_maker_mode, blocked_by, maker_lock, workers,
)
from tests.qr_print_race_safety.helpers import (
    add_http, assert_item, assert_moved, assert_no_writes, assert_order,
    events, evidence, item_write, lab, move_http, prepare, qr_lock, record_protocol, row, state,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("wait", ["maker", "qr"])
@pytest.mark.parametrize("existing", [False, True], ids=["create", "update"])
def test_transfer_first_rechecks_cached_a_qr_before_any_item_mutation(
    lab, kind, wait, existing, record_property,
):
    case = prepare(lab, kind)
    if existing:
        response = add_http(lab, case, label_text="Keep original", sort_order=8)
        assert response.status_code == 201, response.data
    before_items = list(QrPrintBatchItem.objects.order_by("pk").values())
    before_events = list(events().values())

    # A changed label/sort would mutate an existing row if the stale QR were used.
    operation = lambda: add_http(lab, case, label_text="Stale overwrite", sort_order=17)
    with workers() as start:
        if wait == "maker":
            with transaction.atomic():
                Makerspace.objects.select_for_update(no_key=True).get(pk=lab.home.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    owner = cursor.fetchone()[0]
                api = start(operation)
                pending = blocked_by(api, owner)
                assert_maker_mode(pending, "FOR NO KEY UPDATE")
                assert not any(qr_lock(s) or item_write(s) for s in api.statements)
                mover = start(lambda: move_http(lab, case))
                assert_moved(lab, case, mover.finish())
                # Canonical mover committed while this real NK holder remained held.
                assert not pending.completed
                assert_no_writes(api.statements)
                moved = state()
        else:
            mover = start(lambda: move_http(lab, case), pause=qr_lock)
            mover.paused()  # actual canonical QR lock; its mutation has not run yet
            api = start(operation)
            pending = blocked_by(api, mover.pid, qr_lock)
            owner = mover.pid
            maker = next(s for s in api.statements if maker_lock(s))
            assert_maker_mode(maker, "FOR NO KEY UPDATE")
            assert maker.completed
            assert not any(item_write(s) for s in api.statements)
            # No UPDATE upgrade: mover completes its FK checks while API holds NK.
            assert_moved(lab, case, mover.finish())
            moved = state()
        evidence(record_property, pending, owner)
        response = api.finish()
    assert response.status_code == 404, response.data
    assert response.data["detail"].code == "not_found"
    assert_order(api, lab, case, wrote=False)
    record_protocol(record_property, api)
    assert state() == moved  # no orphan, no hidden QR write, no falsely attributed audit
    assert list(QrPrintBatchItem.objects.order_by("pk").values()) == before_items
    assert list(events().values()) == before_events


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_item_first_records_coherent_snapshot_then_allows_legitimate_move(
    lab, kind, record_property,
):
    case = prepare(lab, kind)
    with workers() as start:
        api = start(lambda: add_http(lab, case), pause=qr_lock)
        api.paused()
        assert not any(item_write(s) for s in api.statements)
        mover = start(lambda: move_http(lab, case), pause=qr_lock)
        pending = blocked_by(mover, api.pid, qr_lock)
        evidence(record_property, pending, api.pid)
        response = api.finish()
        mover.paused()  # its real QR lock now succeeds; mutation remains paused
        item = assert_item(lab, case, response)
        original_item, original_events = row(QrPrintBatchItem, item.pk), list(events().values())
        assert_order(api, lab, case, wrote=True)
        record_protocol(record_property, api)
        assert_moved(lab, case, mover.finish())
    # Ownership is checked at mutation. The historical FK and A target snapshot
    # survive a legitimate later move; live nested QR projection belongs elsewhere.
    assert row(QrPrintBatchItem, item.pk) == original_item
    assert list(events().values()) == original_events
