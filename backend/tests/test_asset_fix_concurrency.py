"""Real issue/repair races revalidate fresh unit state after PostgreSQL locks."""
import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APIClient

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.evidence.models import EvidenceUploadFinalization
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.makerspaces.module_install import uninstall_module
from apps.operations.models import InventoryAdjustment
from tests.asset_fix_concurrency_helpers import asset_reads, race
from tests.inventory_lending_evidence_helpers import photo, uploaded_images
from tests.inventory_lending_helpers import assert_surfaces, make_lab
from tests.test_individual_fix_boundaries import fix_url, park_unit
from tests.test_individual_fix_lifecycle import (
    accept_one, assert_issued_trace, issue_payload, return_one,
)
from tests.test_issue import issue_url

pytestmark = pytest.mark.django_db(transaction=True)


def worker_client(lab):
    actor = get_user_model().objects.get(pk=lab.actor.pk)
    client = APIClient()
    client.force_authenticate(user=actor)
    return client


def hold_real_audit(monkeypatch, lab, action, reached, release):
    record = audit.record

    def observed(actor, observed_action, **kwargs):
        entry = record(actor, observed_action, **kwargs)
        if (observed_action == action and kwargs["target"].pk == lab.assets[0].pk
                and not reached.is_set()):
            assert connection.in_atomic_block
            reached.set()
            assert release.wait(12), "Real asset audit pause was not released"
        return entry

    monkeypatch.setattr(audit, "record", observed)


@pytest.mark.parametrize("operation", ["shelve", "metadata"])
def test_issue_wins_and_waiting_asset_edit_rechecks_eligibility(monkeypatch, settings, operation):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    store = uploaded_images(monkeypatch, settings)
    loan = accept_one(lab)
    evidence = photo(lab, store, "issue")
    asset = lab.assets[0]
    metadata_fields = ("notes", "serial_number", "asset_tag", "box_id", "public_self_checkout_enabled")
    metadata = {field: getattr(asset, field) for field in metadata_fields}
    reached, release = threading.Event(), threading.Event()
    adapter = notifications.notify_lifecycle

    def observe_issued_notification(*args, **kwargs):
        result = adapter(*args, **kwargs)
        if kwargs.get("event") == "issued":
            # Real QR validation, image decode/promotion, bucket movement and audits
            # have all happened; their domain transaction is still uncommitted.
            assert connection.in_atomic_block
            assert InventoryAsset.objects.get(pk=asset.pk).status == "issued"
            assert AuditLog.objects.filter(
                makerspace=lab.space, action="request.issued", target_id=str(loan.pk),
            ).count() == 1
            assert EvidenceUploadFinalization.objects.get(evidence=evidence).status == "finalized"
            reached.set()
            assert release.wait(12), "Real issue notification pause was not released"
        return result

    monkeypatch.setattr(notifications, "notify_lifecycle", observe_issued_notification)
    reads = []

    def issue():
        return worker_client(lab).post(issue_url(loan), issue_payload(lab, evidence), format="json")

    def contender():
        client = worker_client(lab)
        with asset_reads(asset.pk) as statuses:
            if operation == "shelve":
                response = client.post(fix_url(asset), {"action": "shelve"}, format="json")
            else:
                response = client.patch(
                    f"/api/v1/admin/assets/{asset.pk}", {"notes": "stale edit"}, format="json",
                )
            reads.extend(statuses)
            return response

    def still_committed_available():
        assert InventoryAsset.objects.get(pk=asset.pk).status == "available"
        assert HardwareRequest.objects.get(pk=loan.pk).status == "accepted"

    issued, refused, pids, query = race(
        issue, contender, reached, release, table="makerspaces_makerspace",
        clause="FOR NO KEY UPDATE", before_second=still_committed_available,
    )

    assert len(set(pids.values())) == 2
    # Reviewed issue now holds Maker NO KEY UPDATE before asset/QR locks. The
    # edit waits at that shared guard, then still materializes the fresh issued unit.
    assert 'FROM "makerspaces_makerspace"' in query
    assert [issued.status_code, refused.status_code] == [200, 400], (issued.data, refused.data)
    # post_init observed the endpoint's actual initial and freshly locked objects.
    assert reads == ["available", "issued"]
    detail = str(refused.data)
    expected = "Only available or damaged assets" if operation == "shelve" else "currently issued or reserved"
    assert expected in detail
    asset.refresh_from_db()
    assert asset.status == "issued"
    assert {field: getattr(asset, field) for field in metadata_fields} == metadata
    assert not AuditLog.objects.filter(
        makerspace=lab.space, action__in=[
            "inventory.asset_needs_fix_shelve", "inventory.asset_needs_fix_repair", "inventory.asset_updated",
        ],
    ).exists()
    assert not InventoryAdjustment.objects.filter(makerspace=lab.space).exists()
    assert_issued_trace(lab, loan, evidence)
    return_one(lab, loan, store)


def test_waiting_repair_rechecks_committed_repair_without_duplicate_audit(monkeypatch, settings):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    park_unit(lab)
    reached, release = threading.Event(), threading.Event()
    hold_real_audit(monkeypatch, lab, "inventory.asset_needs_fix_repair", reached, release)
    reads = []

    def repair():
        return worker_client(lab).post(fix_url(lab.assets[0]), {"action": "repair"}, format="json")

    def stale_repair():
        with asset_reads(lab.assets[0].pk) as statuses:
            response = repair()
            reads.extend(statuses)
            return response

    def still_committed_maintenance():
        assert InventoryAsset.objects.get(pk=lab.assets[0].pk).status == "maintenance"

    repaired, refused, _, query = race(
        repair, stale_repair, reached, release, table="makerspaces_makerspace",
        clause="FOR NO KEY UPDATE", before_second=still_committed_maintenance,
    )

    # Unlike issue, a competing fix holds the module's makerspace lock itself.
    assert 'FROM "makerspaces_makerspace"' in query
    assert [repaired.status_code, refused.status_code] == [200, 400], (repaired.data, refused.data)
    assert reads == ["maintenance", "available"]
    assert "Only assets on the fix shelf" in str(refused.data)
    entries = AuditLog.objects.filter(makerspace=lab.space, action="inventory.asset_needs_fix_repair")
    entry = entries.get()
    assert entry.target_id == str(lab.assets[0].pk) and entry.actor_id == lab.actor.pk
    assert not AuditLog.objects.filter(makerspace=lab.space, action="inventory.asset_updated").exists()
    assert not InventoryAdjustment.objects.filter(makerspace=lab.space).exists()
    assert_surfaces(lab, 1, 0, 0, {})


def test_fix_module_lock_still_serializes_actual_module_configuration(monkeypatch, settings):
    lab = make_lab(monkeypatch, settings, total=1, tracking_mode=TrackingMode.INDIVIDUAL)
    park_unit(lab)
    reached, release = threading.Event(), threading.Event()
    hold_real_audit(monkeypatch, lab, "inventory.asset_needs_fix_repair", reached, release)

    def repair():
        return worker_client(lab).post(fix_url(lab.assets[0]), {"action": "repair"}, format="json")

    def disable_units():
        actor = get_user_model().objects.get(pk=lab.actor.pk)
        return uninstall_module(lab.space, "asset_units", actor=actor)

    repaired, removed, _, query = race(
        repair, disable_units, reached, release, table="makerspaces_makerspace", clause="FOR UPDATE",
    )

    assert 'FROM "makerspaces_makerspace"' in query
    assert repaired.status_code == 200, repaired.data
    assert removed == ["asset_units"]
    lab.space.refresh_from_db()
    assert "asset_units" not in lab.space.enabled_modules
    assert_surfaces(lab, 1, 0, 0, {})
    assert AuditLog.objects.filter(
        makerspace=lab.space, action="inventory.asset_needs_fix_repair",
    ).count() == 1
    assert AuditLog.objects.filter(
        makerspace=lab.space, action="makerspace.capabilities_changed", actor=lab.actor,
    ).count() == 1
    response = lab.client.post(fix_url(lab.assets[0]), {"action": "shelve"}, format="json")
    assert response.status_code == 400, response.data
    lab.assets[0].refresh_from_db()
    assert lab.assets[0].status == "available"
    assert not AuditLog.objects.filter(
        makerspace=lab.space, action="inventory.asset_needs_fix_shelve",
    ).exists()
