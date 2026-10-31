"""Source N blocks before Maker/QR/item and survives real Audit INSERT/commit."""
import threading

import pytest
from django.db import transaction

from tests.box_parent_safety.pg_helpers import blocked_by, maker_lock, workers
from tests.qr_print_race_safety.helpers import (
    add_http, assert_item, assert_no_writes, assert_order, audit_insert,
    evidence, item_write, lab, prepare, qr_lock, record_protocol,
)
from tests.qr_print_race_safety.source_helpers import (
    assert_shared, atomic_request, exclusive, locks, source_select, try_exclusive,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_real_source_exclusive_blocks_actual_http_before_maker_qr_or_item(
    lab, kind, record_property,
):
    case = prepare(lab, kind)
    with workers() as start:
        with exclusive(lab.home.pk) as owner:
            api = start(atomic_request(lambda: add_http(lab, case)))
            pending = blocked_by(api, owner, lambda s: source_select(s, lab.home.pk))
            evidence(record_property, pending, owner)
            assert (owner, "ExclusiveLock", True) in locks(lab.home.pk)
            assert (api.pid, "ShareLock", False) in locks(lab.home.pk)
            assert not any(maker_lock(s) or qr_lock(s) or item_write(s) for s in api.statements)
            assert not any('FROM "boxes_qrcode"' in s.sql
                           or 'FROM "operations_qrprintbatchitem"' in s.sql for s in api.statements)
            assert_no_writes(api.statements)
        assert_item(lab, case, api.finish())  # actual HTTP succeeds when N opens
    assert_order(api, lab, case, wrote=True)
    record_protocol(record_property, api)


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_source_shared_survives_actual_audit_insert_http_return_and_outer_commit(lab, kind):
    case = prepare(lab, kind)
    returned, commit = threading.Event(), threading.Event()
    observed = {}

    def outer():
        with transaction.atomic():
            response = add_http(lab, case)
            observed["response"] = response
            returned.set()
            assert commit.wait(20), "Controller did not allow outer commit"
        return response

    with workers() as start:
        api = start(outer, pause=audit_insert)
        try:
            api.paused()  # real AuditLog INSERT succeeded; no audit mock is involved
            assert any(audit_insert(s) and s.completed for s in api.statements)
            first_maker = next(i for i, s in enumerate(api.statements) if maker_lock(s))
            source = [i for i, s in enumerate(api.statements) if source_select(s, lab.home.pk)]
            assert source and max(source) < first_maker
            assert_shared(api.pid, lab.home.pk)
            assert try_exclusive(lab.home.pk) is False
            assert_order(api, lab, case, wrote=True)
            api.release.set()
            assert returned.wait(10), (api.error, api.statements)
            assert observed["response"].status_code == 201, observed["response"].data
            # View/service nested atomics and HTTP have exited. Only caller's
            # actual outer transaction retains shared N, Maker NK and QR locks.
            assert_shared(api.pid, lab.home.pk)
            assert try_exclusive(lab.home.pk) is False
            assert not any(source_select(s, lab.home.pk) for s in api.statements[first_maker + 1:])
        finally:
            commit.set()
        assert_item(lab, case, api.finish())
    assert try_exclusive(lab.home.pk) is True
