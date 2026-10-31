"""Capture refuses partial purge graphs; new compound artifacts omit receipts."""

from unittest.mock import Mock

import pytest
from django.db import transaction
from django.utils import timezone

from apps.backup import archive_payload, main_projection
from apps.backup.main_projection_registry import RowDisposition, table_rules
from apps.data_export.datasets import DATASET_SPECS
from apps.makerspaces.models import Makerspace, PurgeReceipt
from apps.makerspaces.purge_intent import PurgeInProgress, assert_capture_allowed
from tests.makerspaces.purge_test_support import archived_space, receipt

pytestmark = pytest.mark.django_db(transaction=True)


def test_new_compound_projection_omits_receipt_rows_with_real_immutable_trigger():
    row = receipt()
    rules = table_rules()
    rule = next(rule for rule in rules if rule.model is PurgeReceipt)
    assert rule.disposition == RowDisposition.OMIT_OPERATIONAL
    assert "makerspaces.PurgeReceipt" not in DATASET_SPECS
    # Exercise the real projection rather than emulating its DELETE. Roll it back
    # because this is the live test DB, not the producer's disposable scratch DB.
    with transaction.atomic():
        main_projection._apply_projection("default", rules, [])
        assert not PurgeReceipt.objects.exists()
        transaction.set_rollback(True)
    assert PurgeReceipt.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("scope", ["deployment", "included", "other"])
def test_capture_refuses_included_purge_started_tenant_only(scope):
    doomed, other = archived_space(), archived_space("unaffected")
    Makerspace.objects.filter(pk=doomed.pk).update(purge_started_at=timezone.now())
    if scope == "other":
        assert_capture_allowed([other.pk])
    else:
        with pytest.raises(PurgeInProgress):
            assert_capture_allowed(None if scope == "deployment" else [doomed.pk])


def test_tenant_payload_refuses_before_projecting_rows_or_writing_files(tmp_path, monkeypatch):
    space = archived_space()
    Makerspace.objects.filter(pk=space.pk).update(purge_started_at=timezone.now())
    raw = Mock(side_effect=AssertionError("partial purge graph was captured"))
    monkeypatch.setattr(archive_payload, "raw_records", raw)
    destination = tmp_path / "tenant-payload"
    with pytest.raises(PurgeInProgress):
        archive_payload._tenant_payload(space.pk, destination)
    raw.assert_not_called()
    assert not destination.exists()


def test_pre_purge_makerspace_default_has_null_intent_and_no_receipt():
    space = Makerspace.objects.create(name="pre-purge", slug="pre-purge")
    space.refresh_from_db()
    assert space.purge_started_at is None
    assert not PurgeReceipt.objects.exists()


def test_legacy_fixture_omitting_intent_restores_null_without_creating_receipt():
    import json
    from django.core import serializers
    from apps.makerspaces.lifecycle_purge import _delete_object_graph

    space = archived_space()
    source_id = space.pk
    records = json.loads(serializers.serialize("json", [space]))
    records[0]["fields"].pop("purge_started_at")
    with transaction.atomic():
        _delete_object_graph(space)
    for restored in serializers.deserialize("json", json.dumps(records)):
        restored.save()
    restored = Makerspace.objects.get(pk=source_id)
    assert restored.purge_started_at is None
    assert not PurgeReceipt.objects.exists()
