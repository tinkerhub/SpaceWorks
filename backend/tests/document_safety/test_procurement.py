"""Status provenance is transactional; native ModelAdmin uses a request actor."""
import pytest
from django.contrib import admin
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.machines.models import MachineType
from apps.procurement.models import ToBuyItem
from tests.document_safety.helpers import (
    fail_after_audit, lab, machine, member, space,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("status", ["ordered", "received"])
def test_direct_creation_stamps_authenticated_actor_and_only_correct_clock(status, monkeypatch, settings):
    case = lab(monkeypatch, settings)
    before = timezone.now()
    response = case.client.post(
        reverse("procurement:to-buy-list", kwargs={"makerspace_id": case.home.pk}),
        {"name": "Direct purchase", "status": status, "purchaser": 999999,
         "created_by": 999999, "ordered_at": "2000-01-01T00:00:00Z"}, format="json",
    )
    assert response.status_code == 201, response.data
    row = ToBuyItem.objects.get(pk=response.data["id"])
    assert row.created_by_id == row.purchaser_id == case.actor.pk
    stamp = row.ordered_at if status == "ordered" else row.received_at
    assert before <= stamp <= timezone.now()
    assert (row.received_at if status == "ordered" else row.ordered_at) is None
    event = AuditLog.objects.get(action="procurement.item_added", target_id=str(row.pk))
    assert event.actor_id == case.actor.pk and event.makerspace_id == case.home.pk


@pytest.mark.parametrize("status", ["ordered", "received"])
def test_create_audit_failure_rolls_back_item_actor_and_timestamps(status, monkeypatch, settings):
    case = lab(monkeypatch, settings)
    before = list(ToBuyItem.objects.order_by("pk").values()), AuditLog.objects.count()
    _, inserted = fail_after_audit(monkeypatch, "procurement.item_added")
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        case.client.post(
            reverse("procurement:to-buy-list", kwargs={"makerspace_id": case.home.pk}),
            {"name": "Must roll back", "status": status}, format="json",
        )
    assert inserted
    assert (list(ToBuyItem.objects.order_by("pk").values()), AuditLog.objects.count()) == before


def test_patch_audit_failure_preserves_previous_provenance(monkeypatch, settings):
    case = lab(monkeypatch, settings)
    before = ToBuyItem.objects.values().get(pk=case.target.pk), AuditLog.objects.count()
    _, inserted = fail_after_audit(monkeypatch, "procurement.item_updated")
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        case.client.patch(reverse("procurement:to-buy-detail", kwargs={"pk": case.target.pk}),
                          {"status": "received", "vendor_name": "rollback"}, format="json")
    assert inserted
    assert (ToBuyItem.objects.values().get(pk=case.target.pk), AuditLog.objects.count()) == before


def native_form(actor, row=None):
    request = RequestFactory().get("/control/")
    request.user = actor
    return admin.site._registry[ToBuyItem].get_form(request, row)


def form_data(row, **changes):
    data = {"name": row.name, "quantity": row.quantity, "status": row.status,
            "machine_type": row.machine_type_id or "", "vendor_name": row.vendor_name}
    data.update(changes)
    return data


@pytest.mark.parametrize("choice", ["foreign", "provenance-retag", "provenance-clear",
                                   "global", "unprovenanced-retag"])
def test_actual_admin_change_form_validates_ownership_and_durable_provenance(
    choice, monkeypatch, settings,
):
    case = lab(monkeypatch, settings)
    host = machine(case.home)
    row = case.target
    row.kind, row.machine_type = "printing", host.machine_type
    if choice.startswith("provenance"):
        row.resulting_machine = host
    row.save()
    if choice == "foreign":
        selected = MachineType.objects.create(makerspace=case.other, name="Foreign", slug="foreign")
    elif choice == "global":
        selected = MachineType.objects.create(makerspace=None, name="Global", slug="doc-global", is_builtin=True)
    elif choice == "provenance-clear":
        selected = None
    else:
        selected = MachineType.objects.create(makerspace=case.home, name="Other", slug="other")
    form_class = native_form(case.actor, row)
    form = form_class(data=form_data(row, machine_type=selected.pk if selected else ""), instance=row)
    assert form.actor is case.actor
    allowed = choice in {"global", "unprovenanced-retag"}
    assert form.is_valid() is allowed, form.errors
    if allowed:
        form.save()
        row.refresh_from_db()
        assert row.machine_type_id == selected.pk
    else:
        assert "machine_type" in str(form.errors)
        row.refresh_from_db()
        assert row.machine_type_id == host.machine_type_id


@pytest.mark.parametrize("foreign", [False, True])
def test_actual_admin_add_form_accepts_global_type_and_rejects_foreign(foreign, monkeypatch, settings):
    case = lab(monkeypatch, settings)
    kind = MachineType.objects.create(
        makerspace=case.other if foreign else None, name="Type", slug="document-add",
        is_builtin=not foreign,
    )
    form = native_form(case.actor)(data={
        "makerspace": case.home.pk, "kind": "printing", "name": "Purchase", "quantity": 1,
        "status": "ordered", "machine_type": kind.pk,
    })
    assert form.is_valid() is not foreign, form.errors
    if not foreign:
        assert form.save(commit=False).machine_type_id == kind.pk


def test_request_bound_admin_forms_do_not_share_actor_state(monkeypatch, settings):
    case = lab(monkeypatch, settings)
    host = machine(case.home)
    case.target.kind, case.target.machine_type = "printing", host.machine_type
    case.target.save()
    second = member(case.home, "machine_manager")  # No type grants: fail closed.
    first_class = native_form(case.actor, case.target)
    second_class = native_form(second, case.target)
    # Instantiate the first factory AFTER a second request used the singleton admin.
    a = first_class(data=form_data(case.target), instance=case.target)
    b = second_class(data=form_data(case.target), instance=case.target)
    assert a.actor is case.actor and b.actor is second
    assert a.is_valid(), a.errors
    assert not b.is_valid() and "machine_type" in str(b.errors)
    assert "actor" not in vars(admin.site._registry[ToBuyItem])
    assert not hasattr(admin.site._registry[ToBuyItem].form, "actor")


@pytest.mark.parametrize("retag", [False, True])
def test_native_admin_post_preserves_readonly_tenant_kind_and_refuses_provenance_retag(
    retag, monkeypatch, settings,
):
    case = lab(monkeypatch, settings)
    root = User.objects.create_superuser(
        username="document-admin", email="document-admin@example.test", password="admin-password",
        role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
    )
    host = machine(case.home)
    case.target.kind = "printing"
    case.target.machine_type = host.machine_type
    case.target.resulting_machine = host
    case.target.save()
    alternate = MachineType.objects.create(makerspace=case.home, name="Wrong", slug="wrong")
    client = Client(HTTP_HOST="testserver")
    client.force_login(root)
    response = client.post(
        reverse("admin:procurement_tobuyitem_change", args=[case.target.pk]),
        form_data(case.target, makerspace=case.other.pk, kind="hardware", vendor_name="Usable",
                  machine_type=alternate.pk if retag else host.machine_type_id, _save="Save"),
    )
    assert response.status_code == (200 if retag else 302)
    if retag:
        assert response.context["adminform"].form.errors
    case.target.refresh_from_db()
    assert (case.target.makerspace_id, case.target.kind) == (case.home.pk, "printing")
    assert case.target.machine_type_id == host.machine_type_id
    assert case.target.vendor_name == ("" if retag else "Usable")
