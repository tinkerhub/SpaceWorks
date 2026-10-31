"""Exact SDK snapshots: only confirmed DATA IDs authorize accounting settlement."""
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from apps.object_storage import delete_accepted_object_versions as cleanup
from apps.procurement import storage as receipts
from apps.warranty import storage as warranty
from tests.atomic_publication.store import error
from tests.document_quota.version_store import VersionStore


def test_default_result_is_none_and_opt_in_separates_data_from_markers():
    for requested in (False, True):
        store = VersionStore(page_size=1)
        first = store.seed("exact", b"first")
        second = store.seed("exact", b"second")
        marker = store.mark_deleted("exact")
        neighbor = store.seed("exact-neighbor", b"keep")
        result = cleanup(store, bucket="private", key="exact", report_data_versions=requested)
        assert result == (frozenset({first, second}) if requested else None)
        batches = [args["Delete"]["Objects"] for name, args in store.calls if name == "delete"]
        assert {row["VersionId"] for batch in batches for row in batch} == {first, second, marker}
        assert all(row["Key"] == "exact" for batch in batches for row in batch)
        assert store.objects["exact-neighbor"][2] == neighbor
        assert not store.versions["exact"] and not store.markers["exact"]
        lists = [args for name, args in store.calls if name == "list"]
        assert len(lists) == 4 and all("KeyMarker" in args for args in lists[1:])


@pytest.mark.parametrize("count", [0, 1])
def test_empty_and_marker_only_snapshots_report_no_data(count):
    store = VersionStore()
    if count:
        store.mark_deleted("exact")
    assert cleanup(store, bucket="private", key="exact", report_data_versions=True) == frozenset()
    assert not store.markers.get("exact")


def test_all_pages_gathered_and_every_batch_succeeds_before_receipt_is_returned():
    store = VersionStore(page_size=317)
    versions = {store.seed("exact", b"v") for _ in range(2001)}
    def before_delete(_):
        assert len([1 for name, _ in store.calls if name == "list"]) == 7
    store.before_delete = before_delete
    assert cleanup(store, bucket="private", key="exact", report_data_versions=True) == versions
    batches = [args["Delete"]["Objects"] for name, args in store.calls if name == "delete"]
    assert [len(batch) for batch in batches] == [1000, 1000, 1]
    assert not store.versions["exact"]


@pytest.mark.parametrize("failure", [None, False, {"Errors": [{"Code": "AccessDenied"}]}])
def test_partial_batch_failure_never_returns_a_credit_receipt(failure):
    store = VersionStore(page_size=5000)
    for _ in range(1001):
        store.seed("exact", b"v")
    store.delete_responses = [{}, failure]
    with pytest.raises(ClientError, match="ObjectCleanupUnconfirmed"):
        cleanup(store, bucket="private", key="exact", report_data_versions=True)
    assert len(store.versions["exact"]) == 1


def test_new_promotion_after_listing_survives_exact_snapshot_deletion():
    store = VersionStore()
    original = store.seed("exact", b"old")
    late = []
    store.before_delete = lambda _: late.append(store.seed("exact", b"imported later"))
    assert cleanup(store, bucket="private", key="exact", report_data_versions=True) == {original}
    assert set(store.versions["exact"]) == set(late)
    assert store.objects["exact"][0] == b"imported later"


@pytest.mark.parametrize("module", [receipts, warranty])
def test_storage_adapters_preserve_boolean_default_and_opt_in_failure_contract(module, monkeypatch):
    store = VersionStore()
    monkeypatch.setattr(module, "_client", lambda: store)
    assert module.delete_object("absent") is True
    assert module.delete_object("absent", report_versions=True) == frozenset()
    store.seed("exact", b"data")
    def denied(**kwargs):
        raise error("AccessDenied", 403)
    monkeypatch.setattr(store, "list_object_versions", denied)
    assert module.delete_object("exact") is False
    assert module.delete_object("exact", report_versions=True) is None
    assert store.versions["exact"]






@pytest.mark.parametrize("response", [None, False, {"Errors": None}, {"Errors": {}}, {"Errors": "denied"}])
def test_nonconfirming_delete_response_never_returns_data_receipt(response):
    client = Mock()
    client.get_bucket_versioning.return_value = {"Status": "Enabled"}
    client.list_object_versions.return_value = {
        "IsTruncated": False, "Versions": [{"Key": "exact", "VersionId": "v1"}],
    }
    client.delete_objects.return_value = response
    with pytest.raises(ClientError, match="ObjectCleanupUnconfirmed"):
        cleanup(client, bucket="private", key="exact", report_data_versions=True)
