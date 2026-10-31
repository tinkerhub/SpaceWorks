"""Bounded scans progress without turning a cursor into deletion authority."""

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.backup import rollback_cleanup
from apps.backup.models import RestoreOperation
from apps.backup.rollback_cleanup_progress import MAX_LAST_ID
from apps.makerspaces.models import ModulePurgeReceipt
from apps.tenant_migration.models_source_gate import SourceMigrationGate
from tests.backup.rollback_cleanup_outcome_helpers import (
    assert_boundaries, assert_retained, case, snapshot,
)
from tests.backup.rollback_cleanup_progress_helpers import (
    additional_case, assert_cleaned, assert_owner_retained, cleanup_env, freeze_module,
    module_store, outcome_store, save_cursor, saved_cursor,
)


pytestmark = pytest.mark.django_db(transaction=True)
Stage = RestoreOperation.Stage


def sweep(limit=1):
    return rollback_cleanup.cleanup_expired_rollback_objects(limit=limit)


def test_limit_one_failed_then_completed_cleans_on_second_persisted_sweep(cleanup_env, outcome_store):
    failed = case(outcome_store, stage=Stage.FAILED)
    healthy = case(outcome_store, stage=Stage.COMPLETED)
    before = snapshot(failed, outcome_store)
    assert failed.row.pk < healthy.row.pk
    assert sweep() == {"status": "retained", "cleaned": 0, "skipped": 1}
    assert saved_cursor() == failed.row.pk
    assert_retained(failed, outcome_store, before)
    outcome_store.on_list = lambda _params: assert_boundaries(healthy)
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == healthy.row.pk
    assert_cleaned(healthy, outcome_store)
    assert_owner_retained(failed, before)
    assert outcome_store.objects == {key: value for key, value in before.objects.items()
                                     if key not in healthy.copies}


def test_retained_prefix_cannot_starve_later_eligible_row_within_four_calls(cleanup_env, outcome_store):
    failed = case(outcome_store, stage=Stage.FAILED)
    prefix = [failed, additional_case(failed, outcome_store, global_row=True),
              additional_case(failed, outcome_store)]
    healthy = case(outcome_store, stage=Stage.COMPLETED)
    before = [snapshot(item, outcome_store) for item in prefix]
    for item in prefix:
        assert sweep() == {"status": "retained", "cleaned": 0, "skipped": 1}
        assert saved_cursor() == item.row.pk
    assert outcome_store.calls == [] and outcome_store.client_requests == []
    outcome_store.on_list = lambda _params: assert_boundaries(healthy)
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == healthy.row.pk
    assert_cleaned(healthy, outcome_store)
    for item, original in zip(prefix, before, strict=True):
        assert_owner_retained(item, original)
    assert outcome_store.objects == {key: value for key, value in before[0].objects.items()
                                     if key not in healthy.copies}


def test_closed_tenant_and_real_frozen_receipt_advance_without_deleting_or_crediting(
    cleanup_env, outcome_store, monkeypatch,
):
    closed = case(outcome_store)
    frozen = additional_case(closed, outcome_store)
    healthy = additional_case(closed, outcome_store)
    now = timezone.now()
    SourceMigrationGate.objects.create(
        makerspace=closed.space, state="quiesced", owner_id=uuid4(), heartbeat_at=now,
        lease_expires_at=now + timezone.timedelta(hours=1),
    )
    receipt = freeze_module(frozen, outcome_store, monkeypatch)
    receipt_before = ModulePurgeReceipt.objects.values().get(pk=receipt.pk)
    before = [snapshot(item, outcome_store) for item in (closed, frozen)]
    for item, original in zip((closed, frozen), before, strict=True):
        assert sweep() == {"status": "checked", "cleaned": 0, "skipped": 1}
        assert saved_cursor() == item.row.pk
        assert_retained(item, outcome_store, original)
    outcome_store.on_list = lambda _params: assert_boundaries(healthy)
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == healthy.row.pk
    assert_cleaned(healthy, outcome_store)
    for item, original in zip((closed, frozen), before, strict=True):
        assert_owner_retained(item, original)
    assert outcome_store.objects == {key: value for key, value in before[0].objects.items()
                                     if key not in healthy.copies}
    assert ModulePurgeReceipt.objects.values().get(pk=receipt.pk) == receipt_before


def test_wrap_shares_one_limit_never_repeats_a_row_and_revisits_all_retained(cleanup_env, outcome_store):
    first = case(outcome_store)
    items = [first, additional_case(first, outcome_store, global_row=True),
             additional_case(first, outcome_store)]
    before = [snapshot(item, outcome_store) for item in items]
    by_key = {item.row.copy_key: item for item in items}
    seen = []

    def listing(params):
        item = by_key[params["Prefix"]]
        assert_boundaries(item)
        seen.append(item.row.pk)

    outcome_store.on_list = listing
    outcome_store.failure = "listing"  # Retain every row through the actual provider boundary.
    ids = [item.row.pk for item in items]
    save_cursor(ids[1])
    for limit, expected in ((2, [ids[2], ids[0]]), (2, [ids[1], ids[2]]),
                            (2, [ids[0], ids[1]]), (10, [ids[2], ids[0], ids[1]])):
        seen.clear()
        assert sweep(limit) == {"status": "checked", "cleaned": 0, "skipped": len(expected)}
        assert seen == expected and len(seen) == len(set(seen))
        assert len(seen) <= limit
        assert saved_cursor() == expected[-1]
    assert outcome_store.objects == before[0].objects
    for item, original in zip(items, before, strict=True):
        assert_owner_retained(item, original)


def test_high_then_genuinely_deleted_then_absent_cursor_each_finds_remaining_rows(cleanup_env, outcome_store):
    first = case(outcome_store)
    save_cursor(MAX_LAST_ID)
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == first.row.pk  # Cursor now points at a genuinely cleaned/deleted row.
    assert_cleaned(first, outcome_store)
    second = additional_case(first, outcome_store)
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == second.row.pk
    assert_cleaned(second, outcome_store)
    third = additional_case(first, outcome_store)
    cleanup_env.unlink()
    assert saved_cursor() == 0
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == third.row.pk
    for item in (first, second, third):
        assert_cleaned(item, outcome_store)


def test_provider_failure_advances_keeps_locator_and_quota_then_retries_healthy(cleanup_env, outcome_store):
    failed = case(outcome_store)
    healthy = additional_case(failed, outcome_store, global_row=True)
    before = snapshot(failed, outcome_store)

    def listing(params):
        item = failed if params["Prefix"] == failed.row.copy_key else healthy
        assert_boundaries(item)
        if item is failed:
            raise OSError("temporary provider outage for this exact rollback key")

    outcome_store.on_list = listing
    assert sweep() == {"status": "checked", "cleaned": 0, "skipped": 1}
    assert saved_cursor() == failed.row.pk
    assert_owner_retained(failed, before)
    assert outcome_store.objects == before.objects
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == healthy.row.pk
    assert_cleaned(healthy, outcome_store)
    assert_owner_retained(failed, before)
    outcome_store.on_list = lambda _params: assert_boundaries(failed)
    assert sweep() == {"status": "checked", "cleaned": 1, "skipped": 0}
    assert saved_cursor() == failed.row.pk
    assert_cleaned(failed, outcome_store)
    calls = list(outcome_store.calls)
    assert sweep() == {"status": "checked", "cleaned": 0, "skipped": 0}
    for item in (failed, healthy):
        assert_cleaned(item, outcome_store)
    assert outcome_store.calls == calls
