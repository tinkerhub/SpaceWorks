"""Reports on the production module set: off modules leave no report, row, column or field.

The set mirrors a check-in-mode site with events, bookings, membership, payments,
member_accounts, mobile and the chat channels switched off ("off means absent",
docs/INVARIANTS.md).
"""

import csv
import io

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import Makerspace
from apps.operations import reports
from tests.return_helpers import authenticated_client, make_member, make_user


pytestmark = pytest.mark.django_db

ON = [
    "public_inventory", "request_workflow", "staff_admin", "scanner", "evidence_uploads",
    "qr_management", "guest_handover", "printing", "telegram", "bulk_import", "containers",
    "stock_transfers", "stocktake", "reports", "qr_print_batches", "asset_units", "procurement",
    "machines", "machine_service", "maintenance", "notifications", "email",
]
OFF = {"events", "bookings", "membership", "payments", "member_accounts", "mobile", "slack", "mattermost", "discord"}
OFF_REPORTS = {"event-attendance", "booking-utilization", "member-activity", "payment-reconciliation", "community-engagement"}


def _space(slug):
    space = Makerspace.objects.create(name=slug, slug=slug, enabled_modules=list(ON))
    machine_type = MachineType.objects.create(makerspace=space, slug=f"{slug}-type", name="Laser")
    Machine.objects.create(makerspace=space, machine_type=machine_type, name="Cutter")
    return space


def _csv(response):
    return list(csv.reader(io.StringIO(response.content.decode())))


def test_catalog_omits_every_off_module_report_and_column():
    space = _space("offstate-catalog")
    client = authenticated_client(make_member("offstate-catalog-sm", space))

    response = client.get(reverse("report-catalog", args=[space.id]))

    assert response.status_code == 200, response.data
    entries = {row["key"]: row for row in response.data["results"]}
    assert not OFF_REPORTS & set(entries)
    assert all(row["available"] is True for row in entries.values())
    assert {"machine-usage", "maintenance-activity", "inventory-control", "module-operational-health"} <= set(entries)
    fablab_fields = entries["fablab-health"]["fields"]
    assert not [field for field in fablab_fields if field.startswith(("events_", "bookings_"))]
    assert "machines_usage_hours" in fablab_fields
    assert entries["damaged-missing"]["title"] == "Damaged / missing"
    assert entries["qr-scans"]["title"] == "QR scans"


@pytest.mark.parametrize("key", sorted(OFF_REPORTS))
def test_off_module_reports_are_refused_for_preview_and_export(key):
    space = _space(f"offstate-refuse-{key}")
    client = authenticated_client(make_member(f"offstate-refuse-{key}-sm", space))

    preview = client.get(f"/api/v1/admin/makerspace/{space.id}/analytics/{key}")
    export = client.get(f"/api/v1/admin/makerspace/{space.id}/reports/{key}/export?format=csv")

    assert preview.status_code == 400
    assert export.status_code == 400


def test_fablab_health_drops_off_sections_in_preview_and_export():
    space = _space("offstate-fablab")
    client = authenticated_client(make_member("offstate-fablab-sm", space))

    preview = client.get(f"/api/v1/admin/makerspace/{space.id}/analytics/fablab-health")
    export = client.get(f"/api/v1/admin/makerspace/{space.id}/reports/fablab-health/export?format=csv")

    assert preview.status_code == 200, preview.data
    header = preview.data["rows"][0]
    assert not [field for field in header if field.startswith(("events_", "bookings_"))]
    assert header[:4] == ["machines_enabled", "machines_available", "machines_active", "machines_usage_hours"]
    assert set(preview.data["typed_rows"][0]) == set(header)
    assert preview.data["typed_rows"][0]["machines_active"] == 1
    assert export.status_code == 200
    assert _csv(export)[0] == header


def test_module_health_lists_only_installed_modules():
    space = _space("offstate-health")
    client = authenticated_client(make_member("offstate-health-sm", space))

    preview = client.get(f"/api/v1/admin/makerspace/{space.id}/analytics/module-operational-health")
    export = client.get(f"/api/v1/admin/makerspace/{space.id}/reports/module-operational-health/export?format=xlsx")

    assert preview.status_code == 200, preview.data
    keys = {row["module_key"] for row in preview.data["typed_rows"]}
    assert keys == set(ON)
    assert all(row["enabled"] is True for row in preview.data["typed_rows"])
    assert export.status_code == 200


def test_module_health_counts_machine_service_and_print_activity():
    from apps.audit.services import record

    space = _space("offstate-health-activity")
    record(None, "machine_service.submitted", makerspace=space, target=space)
    record(None, "print_request.created", makerspace=space, target=space)

    rows = {row["module_key"]: row for row in reports.report_data("module-operational-health", space.id)["typed_rows"]}

    assert rows["machine_service"]["activity_count"] == 1
    assert rows["printing"]["activity_count"] == 1


def test_community_engagement_keeps_only_installed_rows():
    space = _space("offstate-community")
    space.enabled_modules = [*ON, "membership"]
    space.save(update_fields=["enabled_modules"])

    rows = reports.report_data("community-engagement", space.id)["typed_rows"]

    assert [row["module_key"] for row in rows] == ["membership"]


def test_inventory_report_still_exports_correct_numbers():
    from apps.inventory.models import InventoryProduct

    space = _space("offstate-inventory")
    InventoryProduct.objects.create(makerspace=space, name="Caliper", total_quantity=10, available_quantity=7)
    client = authenticated_client(make_member("offstate-inventory-sm", space))

    summary = client.get(f"/api/v1/admin/makerspace/{space.id}/analytics/summary")
    export = client.get(f"/api/v1/admin/makerspace/{space.id}/reports/recently-added/export?format=csv")

    assert summary.status_code == 200
    assert summary.data["products"] == 1
    assert summary.data["available_quantity"] == 7
    rows = _csv(export)
    assert rows[0] == ["product_name", "created_at", "total_quantity"]
    assert rows[1][0] == "Caliper" and rows[1][2] == "10"


def test_aggregate_catalog_omits_reports_no_eligible_space_runs():
    _space("offstate-aggregate")
    Makerspace.objects.exclude(slug="offstate-aggregate").update(enabled_modules=list(ON))
    superadmin = make_user("offstate-aggregate-admin", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)

    response = authenticated_client(superadmin).get("/api/v1/admin/reports/catalog")

    assert response.status_code == 200, response.data
    assert not OFF_REPORTS & {row["key"] for row in response.data["results"]}
