"""Provider protocol proofs: pagination, exact identities and physical aliases."""

from unittest.mock import Mock

import pytest

from apps.makerspaces import purge_storage
from tests.makerspaces.purge_test_support import purge_store


def test_paginated_versions_and_delete_markers_are_all_materialized():
    client = Mock()
    client.list_object_versions.side_effect = [
        {"IsTruncated": True, "Versions": [{"Key": "evidence/1/a", "VersionId": "old"}],
         "NextKeyMarker": "evidence/1/a", "NextVersionIdMarker": "old"},
        {"IsTruncated": False, "DeleteMarkers": [{"Key": "evidence/1/a", "VersionId": "marker"}],
         "Versions": [{"Key": "evidence/1/b", "VersionId": "null"}]},
    ]
    rows = purge_storage.list_versions(client, "bucket", "evidence/1/")
    assert {(row["Key"], row["VersionId"]) for row in rows} == {
        ("evidence/1/a", "old"), ("evidence/1/a", "marker"), ("evidence/1/b", "null"),
    }
    assert client.list_object_versions.call_args_list[1].kwargs == {
        "Bucket": "bucket", "Prefix": "evidence/1/",
        "KeyMarker": "evidence/1/a", "VersionIdMarker": "old",
    }


@pytest.mark.parametrize("page", [
    {}, {"IsTruncated": "false"}, {"IsTruncated": True},
    {"IsTruncated": False, "Versions": [{"Key": "evidence/11/a", "VersionId": "v"}]},
    {"IsTruncated": False, "DeleteMarkers": [{"Key": "evidence/1/a"}]},
    {"IsTruncated": False, "Versions": [{"Key": "evidence/1/a", "VersionId": ""}]},
    {"IsTruncated": False, "Versions": [{"Key": "evidence/1/a", "VersionId": "v"}] * 2},
], ids=["unsupported", "untyped-truncated", "missing-marker", "foreign-prefix", "no-marker-id", "empty-id", "duplicate-version"])
def test_incomplete_or_ambiguous_version_proof_refuses_without_delete(page):
    client = Mock()
    client.list_object_versions.return_value = page
    with pytest.raises(purge_storage.PurgeStorageRefused):
        purge_storage.list_versions(client, "bucket", "evidence/1/")
    client.delete_objects.assert_not_called()


def test_all_keys_are_enumerated_before_any_delete_and_prefix_neighbors_survive(purge_store):
    bucket = purge_storage.bucket_name("private")
    first, second = "evidence/1/a", "evidence/1/z"
    purge_store.put(bucket, first)
    neighbor = purge_store.put(bucket, first + "-neighbor")
    purge_store.put(bucket, second)

    def refuse_last(params):
        if params["Prefix"] == second:
            raise OSError("last key cannot be listed")

    purge_store.on_list = refuse_last
    closure = {("private", first), ("private", second)}
    with pytest.raises(purge_storage.PurgeStorageRefused):
        purge_storage.delete_and_verify(purge_store, closure, lambda: None)
    assert not purge_store.deletes
    purge_store.on_list = None
    purge_storage.delete_and_verify(purge_store, closure, lambda: None)
    assert set(purge_store.objects) == {neighbor}


def test_same_physical_bucket_alias_deletes_each_version_once(purge_store, settings):
    settings.PUBLIC_IMAGE_BUCKET = settings.AWS_STORAGE_BUCKET_NAME
    bucket = purge_storage.bucket_name("private")
    key = "items/1/shared-logical-alias"
    version = purge_store.put(bucket, key)
    purge_storage.delete_and_verify(purge_store, {("private", key), ("public_image", key)}, lambda: None)
    assert not purge_store.objects
    deleted = [row for call in purge_store.deletes for row in call["Delete"]["Objects"]]
    assert deleted == [{"Key": key, "VersionId": version[2]}]
