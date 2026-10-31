"""Ordinary cleanup deletes a proven version snapshot, never a mutable key."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from apps.object_storage import delete_accepted_object_versions, delete_all_versions
from tests.atomic_publication.store import Store, error


@pytest.mark.parametrize("helper", [delete_accepted_object_versions, delete_all_versions],
                         ids=["ordinary", "terminal"])
def test_empty_exact_listing_never_bare_deletes_later_import(helper):
    store = Store()
    original = store.list_object_versions

    def list_then_publish(**kwargs):
        page = original(**kwargs)
        store.seed("key", b"concurrent import")
        return page

    store.list_object_versions = list_then_publish
    helper(store, bucket="private", key="key")
    assert store.objects["key"][0] == b"concurrent import"
    assert not any(op == "delete" for op, _ in store.calls)


def test_exact_version_snapshot_preserves_new_import_and_neighbor_keys():
    store = Store()
    old = store.seed("key", b"old")
    store.seed("key/neighbor", b"neighbor")
    store.before_delete = lambda kwargs: store.seed("key", b"new import")
    delete_accepted_object_versions(store, bucket="private", key="key")
    assert store.objects["key"][0] == b"new import"
    assert store.objects["key/neighbor"][0] == b"neighbor"
    deleted = [args for op, args in store.calls if op == "delete"]
    assert deleted[0]["Delete"]["Objects"] == [{"Key": "key", "VersionId": old}]


@pytest.mark.parametrize("status", [None, "Suspended", "Disabled"])
def test_unversioned_cleanup_fails_closed_before_listing_or_delete(status):
    client = Mock()
    client.get_bucket_versioning.return_value = {} if status is None else {"Status": status}
    with pytest.raises(ClientError):
        delete_accepted_object_versions(client, bucket="private", key="key")
    client.list_object_versions.assert_not_called()
    client.delete_objects.assert_not_called()
    client.delete_object.assert_not_called()


@pytest.mark.parametrize("page", [
    None, {}, {"IsTruncated": "False"}, {"IsTruncated": False, "Versions": {}},
    {"IsTruncated": False, "Versions": [{"Key": "key"}]},
    {"IsTruncated": False, "Versions": [{"Key": "key", "VersionId": ""}]},
    {"IsTruncated": False, "Versions": [{"Key": "key", "VersionId": 123}]},
    {"IsTruncated": False, "Versions": [{"Key": "key", "VersionId": "v"}] * 2},
    {"IsTruncated": True, "Versions": [{"Key": "key", "VersionId": "v"}]},
], ids=["not-dict", "missing-truncated", "malformed-truncated", "malformed-group",
        "missing-id", "empty-id", "numeric-id", "duplicate-id", "missing-cursor"])
def test_malformed_version_proof_never_partially_deletes(page):
    client = Mock()
    client.get_bucket_versioning.return_value = {"Status": "Enabled"}
    client.list_object_versions.return_value = page
    with pytest.raises(ClientError):
        delete_accepted_object_versions(client, bucket="private", key="key")
    client.delete_objects.assert_not_called()
    client.delete_object.assert_not_called()


def test_duplicate_across_pages_refuses_entire_snapshot():
    client = Mock()
    client.get_bucket_versioning.return_value = {"Status": "Enabled"}
    client.list_object_versions.side_effect = [
        {"IsTruncated": True, "NextKeyMarker": "key", "NextVersionIdMarker": "v",
         "Versions": [{"Key": "key", "VersionId": "v"}]},
        {"IsTruncated": False, "DeleteMarkers": [{"Key": "key", "VersionId": "v"}]},
    ]
    with pytest.raises(ClientError):
        delete_accepted_object_versions(client, bucket="private", key="key")
    client.delete_objects.assert_not_called()


@pytest.mark.parametrize("enabled", [True, False])
def test_retained_null_id_requires_currently_enabled_versioning(enabled):
    client = Mock()
    client.get_bucket_versioning.return_value = {"Status": "Enabled" if enabled else "Suspended"}
    client.list_object_versions.return_value = {
        "IsTruncated": False, "Versions": [{"Key": "key", "VersionId": "null"}],
    }
    client.delete_objects.return_value = {}
    if enabled:
        delete_accepted_object_versions(client, bucket="private", key="key")
        assert client.delete_objects.call_args.kwargs["Delete"]["Objects"] == [{"Key": "key", "VersionId": "null"}]
    else:
        with pytest.raises(ClientError):
            delete_accepted_object_versions(client, bucket="private", key="key")
        client.delete_objects.assert_not_called()
    client.delete_object.assert_not_called()


def test_unsupported_listing_is_closed_for_ordinary_but_terminal_policy_retained():
    client = Mock()
    client.get_bucket_versioning.return_value = {"Status": "Enabled"}
    client.list_object_versions.side_effect = error("NotImplemented", 501)
    with pytest.raises(ClientError):
        delete_accepted_object_versions(client, bucket="private", key="key")
    client.delete_object.assert_not_called()
    delete_all_versions(client, bucket="private", key="key")
    client.delete_object.assert_called_once_with(Bucket="private", Key="key")
