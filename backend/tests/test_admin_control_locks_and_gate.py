"""/control/ locks history-bearing rows, and custom write views honour the source gate."""

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import QrCode, QrScanEvent
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory.models import InventoryProduct
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace, MakerspaceMembership, PurgeReceipt
from apps.makerspaces import purge_storage
from apps.makerspaces.purge_intent import load_intent
from django.utils.dateparse import parse_datetime
from tests.makerspaces.purge_test_support import purge_clock, purge_store
from apps.makerspaces.roles import ensure_default_roles
from apps.operations.models import (
    InventoryAdjustment,
    StockTransfer,
    StocktakeLine,
    StocktakeSession,
)
from tests.admin_form_helpers import page_data
from tests.return_helpers import make_product, make_space, make_user
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db


def _superadmin(username):
    return make_user(
        username, role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        is_staff=True, is_superuser=True,
    )


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _messages(response):
    return " ".join(str(message) for message in get_messages(response.wsgi_request))


def test_product_quantities_and_tracking_are_read_only_from_the_first_save():
    client = _client(_superadmin("ctl-lock-product"))
    product = make_product(make_space("ctl-lock-product"))

    add_form = client.get(reverse("admin:inventory_inventoryproduct_add")).context["adminform"].form

    assert not {"tracking_mode", "total_quantity", "available_quantity"} & set(add_form.fields)
    delete_url = reverse("admin:inventory_inventoryproduct_delete", args=[product.pk])
    assert client.post(delete_url, {"post": "yes"}).status_code == 403
    assert InventoryProduct.objects.filter(pk=product.pk).exists()


def test_scan_history_and_adjustment_ledger_are_view_only():
    user = _superadmin("ctl-lock-ledger")
    space = make_space("ctl-lock-ledger")
    product = make_product(space)
    qr = QrCode.objects.create(
        makerspace=space, target_type=QrCode.TargetType.PRODUCT, target_id=product.pk
    )
    scan = QrScanEvent.objects.create(
        qr_code=qr, makerspace=space, actor=user, context=QrScanEvent.Context.SCANNER_LOOKUP
    )
    adjustment = InventoryAdjustment.objects.create(
        makerspace=space, product=product, delta_available=1, reason="Ledger", created_by=user
    )
    client = _client(user)

    for name, pk in (
        ("boxes_qrscanevent", scan.pk),
        ("operations_inventoryadjustment", adjustment.pk),
    ):
        change_url = reverse(f"admin:{name}_change", args=[pk])
        assert client.get(change_url).status_code == 200
        assert client.post(change_url, {}).status_code == 403
        assert client.post(reverse(f"admin:{name}_delete", args=[pk]), {"post": "yes"}).status_code == 403
    assert client.get(reverse("admin:boxes_qrscanevent_add")).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_makerspace_purge_only_through_the_slug_confirmed_action(purge_store, purge_clock):
    user = _superadmin("ctl-lock-purge")
    space = make_space("ctl-lock-purge")
    StockTransfer.objects.create(makerspace=space, created_by=user, reason="Purge graph history")
    archived = lifecycle.archive(space, user)
    survivor = Makerspace.objects.create(name="Purge survivor", slug="purge-survivor")
    history = AuditLog.objects.create(actor=user, action="purge.survivor_history", makerspace=survivor)
    doomed_id = archived.pk
    bucket = purge_storage.bucket_name("private")
    key = f"evidence/{doomed_id}/admin-purge.jpg"
    versions = {
        purge_store.put(bucket, locator, payload, marker=marker)
        for locator in (key, f"staging/{key}")
        for payload, marker in ((b"old", False), (b"new", False), (b"", True))
    }
    survivor_version = purge_store.put(bucket, f"evidence/{survivor.pk}/keep.jpg")
    client = _client(user)

    delete_url = reverse("admin:makerspaces_makerspace_delete", args=[archived.pk])
    assert client.post(delete_url, {"post": "yes"}).status_code == 403

    response = client.post(
        reverse("admin:makerspaces_makerspace_changelist"),
        {
            "action": "purge_makerspaces",
            ACTION_CHECKBOX_NAME: [str(archived.pk)],
            "confirm_purge": "1",
            f"slug_{archived.pk}": archived.slug,
        },
    )

    # Legacy changelist POST only renders the dedicated CSRF confirmation form.
    assert response.status_code == 200
    confirmed_url = reverse("admin:makerspaces_makerspace_purge_confirmed")
    assert confirmed_url.encode() in response.content
    assert b'csrfmiddlewaretoken' in response.content
    assert Makerspace.objects.filter(pk=doomed_id).exists()
    assert not PurgeReceipt.objects.filter(source_makerspace_id=doomed_id).exists()
    assert set(purge_store.objects) == versions | {survivor_version}
    data = {"makerspace_id": str(doomed_id), f"slug_{doomed_id}": archived.slug}
    first = client.post(confirmed_url, data)
    assert first.status_code == 200 and b"Retry after" in first.content
    archived.refresh_from_db()
    assert archived.purge_started_at is not None
    assert set(purge_store.objects) == versions | {survivor_version}
    assert Makerspace.objects.filter(pk=doomed_id).exists()
    assert StockTransfer.objects.filter(makerspace_id=doomed_id).exists()
    assert AuditLog.objects.filter(makerspace_id=doomed_id).exists()
    purge_clock.now = parse_datetime(load_intent(archived)["not_before"])
    second = client.post(confirmed_url, data)
    assert second.status_code == 200 and b"Tenant graph removed" in second.content
    assert not Makerspace.objects.filter(pk=doomed_id).exists()
    receipt = PurgeReceipt.objects.get(source_makerspace_id=doomed_id)
    assert receipt.last_verified_at == purge_clock.now
    assert receipt.graph_purged_at == purge_clock.now
    assert {("private", key), ("private", f"staging/{key}")} <= set(map(tuple, receipt.exact_keys))
    removed = {
        (call["Bucket"], row["Key"], row["VersionId"])
        for call in purge_store.deletes for row in call["Delete"]["Objects"]
    }
    assert removed == versions
    assert set(purge_store.objects) == {survivor_version}
    assert Makerspace.objects.filter(pk=survivor.pk).exists()
    assert AuditLog.objects.filter(pk=history.pk, makerspace=survivor).exists()
    assert not StockTransfer.objects.filter(makerspace_id=doomed_id).exists()
    assert not AuditLog.objects.filter(makerspace_id=doomed_id).exists()


def _pending_request(space):
    requester = make_user(f"{space.slug}-requester", access_status=User.AccessStatus.ACTIVE)
    product = make_product(space, total_quantity=3, available_quantity=3)
    request = HardwareRequest.objects.create(
        makerspace=space, requester=requester, requester_username=requester.username,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequestItem.objects.create(request=request, product=product, requested_quantity=1)
    return request


def test_closed_source_gate_refuses_custom_admin_writes_with_a_message():
    user = _superadmin("ctl-gate-actor")
    space = make_space("ctl-gate-space")
    hardware_request = _pending_request(space)
    product = make_product(space, name="Gate PLA", total_quantity=4, available_quantity=4)
    stocktake = StocktakeSession.objects.create(makerspace=space, started_by=user)
    client = _client(user)
    import_url = reverse("admin:inventory_inventoryproduct_bulk_import")
    upload = SimpleUploadedFile(
        "items.csv", b"name,total_quantity,available_quantity\nCalipers,2,2\n", content_type="text/csv"
    )
    assert client.post(import_url, {"makerspace": space.pk, "file": upload}).status_code == 200
    close_gate(space, user)

    review = client.post(
        reverse("admin:hardware_requests_hardwarerequest_review", args=[hardware_request.pk]),
        {"accept": "1"},
    )
    assert review.status_code == 302 and "frozen" in _messages(review)
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL

    transfer = client.post(
        reverse("admin:operations_stocktransfer_add"),
        {"source_makerspace": space.pk, "product": product.pk, "quantity": "1", "reason": "Gate"},
    )
    assert transfer.status_code == 200 and "frozen" in str(transfer.context["form"].errors)
    assert not StockTransfer.objects.exists()

    count = client.post(
        reverse("admin:operations_stocktakesession_count", args=[stocktake.pk]),
        {"product": product.pk, "counted_quantity": "3", "condition": StocktakeLine.Condition.AVAILABLE},
    )
    assert count.status_code == 200 and "frozen" in str(count.context["form"].errors)
    assert not StocktakeLine.objects.exists()

    imported = client.post(import_url, {"apply": "1"})
    assert imported.status_code == 200 and "frozen" in str(imported.context["form"].errors)
    assert not InventoryProduct.objects.filter(name="Calipers").exists()


def test_closed_source_gate_refuses_a_user_page_staff_grant():
    user = _superadmin("ctl-gate-inline-actor")
    space = make_space("ctl-gate-inline")
    ensure_default_roles(space)
    target = make_user("ctl-gate-inline-target", access_status=User.AccessStatus.ACTIVE)
    client = _client(user)
    url = reverse("admin:accounts_user_change", args=[target.pk])
    page = client.get(url)
    prefix = page.context["inline_admin_formsets"][0].formset.prefix
    data = page_data(page)
    data.update({
        f"{prefix}-TOTAL_FORMS": "1",
        f"{prefix}-0-makerspace": space.pk,
        f"{prefix}-0-assigned_role": space.roles.get(legacy_role="space_manager").pk,
    })
    close_gate(space, user)

    response = client.post(url, data)

    assert response.status_code == 200
    assert "frozen" in str(response.context["inline_admin_formsets"][0].formset.errors)
    assert not MakerspaceMembership.objects.filter(user=target).exists()


def test_makerspace_staff_inline_lists_active_staff_with_one_roles_query():
    space = make_space("ctl-inline-perf")
    ensure_default_roles(space)
    manager = space.roles.get(legacy_role="machine_manager")
    member = space.roles.get(slug="member")
    staff = [
        MakerspaceMembership.objects.create(
            user=make_user(f"ctl-inline-staff-{index}"), makerspace=space, assigned_role=manager
        )
        for index in range(4)
    ]
    MakerspaceMembership.objects.create(user=make_user("ctl-inline-member"), makerspace=space, assigned_role=member)
    MakerspaceMembership.objects.create(
        user=make_user("ctl-inline-revoked"), makerspace=space, assigned_role=manager, status="revoked"
    )
    client = _client(_superadmin("ctl-inline-actor"))

    with CaptureQueriesContext(connection) as queries:
        page = client.get(reverse("admin:makerspaces_makerspace_change", args=[space.pk]))

    inline = page.context["inline_admin_formsets"][0]
    assert sorted(form.instance.pk for form in inline.formset.forms) == sorted(row.pk for row in staff)
    assert "status" in inline.readonly_fields
    role_selects = [
        query["sql"] for query in queries.captured_queries
        if 'FROM "makerspaces_makerspacerole"' in query["sql"] and "granted_actions" in query["sql"]
    ]
    assert len(role_selects) <= 2, role_selects


def test_revoke_action_does_not_count_already_revoked_rows():
    space = make_space("ctl-revoke-count")
    ensure_default_roles(space)
    role = space.roles.get(legacy_role="machine_manager")
    active = MakerspaceMembership.objects.create(user=make_user("ctl-revoke-a"), makerspace=space, assigned_role=role)
    revoked = MakerspaceMembership.objects.create(
        user=make_user("ctl-revoke-b"), makerspace=space, assigned_role=role, status="revoked"
    )

    response = _client(_superadmin("ctl-revoke-actor")).post(
        reverse("admin:makerspaces_makerspacemembership_changelist"),
        {"action": "revoke_memberships", ACTION_CHECKBOX_NAME: [str(active.pk), str(revoked.pk)], "index": "0"},
        follow=True,
    )

    text = _messages(response)
    assert "Revoked 1 membership(s)." in text
    assert "Skipped 1 already-revoked membership(s)." in text
