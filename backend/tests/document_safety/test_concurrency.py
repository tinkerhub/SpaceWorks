"""Committed-fixture PG races: sparse updates, first creation and stale PATCH."""
import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.machines.models import MachineType
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.makerspaces.module_install import install_module
from apps.procurement.models import ToBuyItem
from apps.warranty.models import Warranty
from tests.document_safety.helpers import jwt_client, lab
from tests.document_safety.pg_helpers import assert_no_maker_upgrade, race, statement
from tests.document_safety.test_warranty import host_url

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["asset", "machine"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_sparse_puts_both_orders_and_absent_first_creation_are_serialized(
    kind, existing, reverse_order, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    url = host_url(case)
    if existing:
        case.target.purchased_on = "2025-01-02"
        case.target.warranty_expires_on = "2028-01-02"
        case.target.save()
    else:
        case.target.delete()
    updates = [{"vendor_name": "Vendor after wait"}, {"vendor_contact": "555-0103"}]
    if reverse_order:
        updates.reverse()

    def put(data):
        return jwt_client(case.actor).put(url, data, format="json")

    first, second, captured, pids, _ = race(
        lambda: put(updates[0]), lambda: put(updates[1]),
        pause_after=statement(
            "inventory_inventoryasset" if kind == "asset" else "machines_machine", "FOR UPDATE",
        ), table="makerspaces_makerspace", clause="FOR NO KEY UPDATE",
    )
    assert first.status_code == second.status_code == 200, (first.data, second.data)
    assert pids["first"] != pids["second"]
    warranty = Warranty.objects.get(makerspace=case.home)
    assert warranty.vendor_name == "Vendor after wait" and warranty.vendor_contact == "555-0103"
    assert first.data["id"] == second.data["id"] == warranty.pk
    if existing:
        assert warranty.purchased_on.isoformat() == "2025-01-02"
        assert warranty.warranty_expires_on.isoformat() == "2028-01-02"
    else:
        assert warranty.purchased_on is warranty.warranty_expires_on is None
    assert AuditLog.objects.filter(action="warranty.created").count() == (0 if existing else 1)
    assert AuditLog.objects.filter(action="warranty.updated").count() == (2 if existing else 1)
    for worker in ("first", "second"):
        assert_no_maker_upgrade(captured, worker)
        sql = [query for query, _ in captured[worker]]
        host_locks = [i for i, query in enumerate(sql) if statement(
            "inventory_inventoryasset" if kind == "asset" else "machines_machine", "FOR UPDATE",
        )(query)]
        warranty_locks = [i for i, query in enumerate(sql) if statement("warranty_warranty", "FOR UPDATE")(query)]
        assert host_locks and warranty_locks and host_locks[0] < warranty_locks[0]


def test_patch_wait_reloads_status_purchaser_and_timestamps(monkeypatch, settings):
    case = lab(monkeypatch, settings)
    url = reverse("procurement:to-buy-detail", kwargs={"pk": case.target.pk})

    def patch(data):
        return jwt_client(case.actor).patch(url, data, format="json")

    first, second, captured, _, _ = race(
        lambda: patch({"status": "received"}), lambda: patch({"vendor_name": "After wait"}),
        pause_after=lambda sql: sql.startswith('UPDATE "procurement_tobuyitem"'),
        table="makerspaces_makerspace", clause="FOR UPDATE",
    )
    assert first.status_code == second.status_code == 200
    case.target.refresh_from_db()
    assert case.target.status == "received" and case.target.purchaser_id == case.actor.pk
    assert case.target.received_at is not None and case.target.ordered_at is None
    assert case.target.vendor_name == "After wait"
    assert second.data["received_at"] == first.data["received_at"]
    assert AuditLog.objects.filter(action="procurement.item_updated").count() == 2
    # The second request actually read the old item before its Maker lock waited.
    reads = [sql for sql, _ in captured["second"] if 'FROM "procurement_tobuyitem"' in sql]
    assert len(reads) >= 3 and any("FOR UPDATE" in sql for sql in reads)


@pytest.mark.parametrize("retag", [False, True])
def test_patch_after_real_procurement_move_reloads_durable_provenance(retag, monkeypatch, settings):
    case = lab(monkeypatch, settings)
    install_module(case.home, "printing", case.actor)
    printer_type, _ = MachineType.objects.get_or_create(
        makerspace=None, slug="3d_printer", defaults={
            "name": "3D printer", "is_builtin": True, "managing_action": "manage_printing",
            "capability_config": PRINTER_CONFIG,
        },
    )
    other_type = MachineType.objects.create(makerspace=case.home, slug="other", name="Other")
    case.target.kind, case.target.status, case.target.machine_type = "printing", "received", printer_type
    case.target.save()
    move_url = reverse("procurement:to-buy-move-to-printing", kwargs={"pk": case.target.pk})
    patch_url = reverse("procurement:to-buy-detail", kwargs={"pk": case.target.pk})

    def move():
        return jwt_client(case.actor).post(
            move_url, {"target": "printer", "name": "Actual received printer", "model": "MK4"},
            format="json",
        )

    changes = {"machine_type": other_type.pk} if retag else {"vendor_name": "Retain provenance"}
    first, second, _, _, _ = race(
        move, lambda: jwt_client(case.actor).patch(patch_url, changes, format="json"),
        pause_after=lambda sql: sql.startswith('UPDATE "procurement_tobuyitem"'),
        table="makerspaces_makerspace", clause="FOR UPDATE",
    )
    assert first.status_code == 200, first.data
    assert second.status_code == (400 if retag else 200), second.data
    case.target.refresh_from_db()
    assert case.target.resulting_machine_id == first.data["resulting_machine"]
    assert case.target.moved_to_inventory_at is not None
    assert case.target.machine_type_id == printer_type.pk
    assert case.target.resulting_machine.machine_type_id == printer_type.pk
    if retag:
        assert "machine_type" in second.data
    else:
        assert second.data["resulting_machine"] == first.data["resulting_machine"]
    assert AuditLog.objects.filter(action="procurement.moved_to_printing").count() == 1
