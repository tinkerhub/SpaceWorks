"""/control/ edits that used to bypass their services now go through them or are read-only."""

from types import SimpleNamespace

import pytest
from django import forms
from django.contrib import admin
from django.test import RequestFactory, override_settings

from apps.accounts.admin_social import OidcProviderForm
from apps.accounts.models import User
from apps.accounts.models_oidc import OidcProvider
from apps.accounts.models_social import SocialIdentity
from apps.apiclients.admin_forms import ApiClientAdminForm, save_makerspace_settings
from apps.apiclients.models import ApiKeyRequest
from apps.boxes.models import Box, QrCode
from apps.hardware_requests.models import PublicProblemReport
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.machines.models import Machine, MachineType
from apps.makerspaces.admin_capabilities import MakerspaceAdminForm
from apps.makerspaces.models import Makerspace
from apps.operations.admin import QrPrintBatchItemInline
from apps.operations.models import InventoryAdjustment, QrPrintBatch, StocktakeSession
from apps.procurement.models import ToBuyItem
from apps.procurement.services import stamp_status_change
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


def _request():
    request = RequestFactory().get("/control/")
    request.user = make_user("ctl-guard-admin", role=User.Role.SUPERADMIN, is_superuser=True, is_staff=True)
    return request


@pytest.mark.parametrize(("model", "fields"), [
    (User, {"access_status", "restriction_reason"}),
    (PublicProblemReport, {"resolved_at", "resolved_by"}),
    (ApiKeyRequest, {"status"}),
    (QrPrintBatch, {"status", "printed_at"}),
])
def test_service_owned_fields_are_read_only(model, fields):
    model_admin = admin.site._registry[model]
    assert fields <= set(model_admin.get_readonly_fields(_request(), None))


def test_existing_rows_lock_their_lifecycle_and_tenancy_fields():
    request = _request()
    space = make_space("ctl-guard-rows")
    stocktake = StocktakeSession(makerspace=space)
    assert {"status", "approved_at", "makerspace"} <= set(admin.site._registry[StocktakeSession].get_readonly_fields(request, stocktake))
    assert {"status", "product"} <= set(admin.site._registry[InventoryAsset].get_readonly_fields(request, InventoryAsset(makerspace=space)))
    assert {"status", "target_id"} <= set(admin.site._registry[QrCode].get_readonly_fields(request, QrCode(makerspace=space)))
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    assert "slug" in admin.site._registry[MachineType].get_readonly_fields(request, printer_type)
    machine = Machine(makerspace=space, machine_type=printer_type)
    assert {"makerspace", "machine_type"} <= set(admin.site._registry[Machine].get_readonly_fields(request, machine))
    assert "slug" in admin.site._registry[OidcProvider].get_readonly_fields(request, OidcProvider(slug="x"))
    assert not admin.site._registry[InventoryAsset].has_add_permission(request)
    assert not admin.site._registry[InventoryAdjustment].has_add_permission(request)


def test_disabling_an_oidc_provider_refuses_to_strand_password_less_users():
    provider = OidcProvider.objects.create(
        slug="ctl-idp", display_name="IdP", issuer="https://idp.example", jwks_url="https://idp.example/jwks",
        client_id="client",
    )
    user = make_user("ctl-oidc-only")
    user.set_unusable_password()
    user.save(update_fields=["password"])
    SocialIdentity.objects.create(user=user, provider=provider.provider_key, provider_sub="sub-1")
    data = {field.name: getattr(provider, field.name) for field in OidcProvider._meta.fields if field.editable}
    data["is_enabled"] = False
    form = OidcProviderForm(data=data, instance=provider)
    assert not form.is_valid()
    assert "lock out 1 account" in str(form.errors)


def test_adding_an_api_client_keeps_the_makerspace_mail_settings():
    space = make_space("ctl-guard-smtp")
    Makerspace.objects.filter(pk=space.pk).update(smtp_host="smtp.example", smtp_from_email="desk@example.test", smtp_port=2525)
    space.refresh_from_db()
    form = SimpleNamespace(changed_data=["label"], cleaned_data={"smtp_host": "", "smtp_port": None})
    save_makerspace_settings(space, form)
    space.refresh_from_db()
    assert (space.smtp_host, space.smtp_from_email, space.smtp_port) == ("smtp.example", "desk@example.test", 2525)
    save_makerspace_settings(space, SimpleNamespace(changed_data=["smtp_host"], cleaned_data={"smtp_host": "mail.example"}))
    space.refresh_from_db()
    assert space.smtp_host == "mail.example"


def test_changing_the_domain_in_control_resets_verification():
    space = make_space("ctl-guard-domain")
    Makerspace.objects.filter(pk=space.pk).update(
        frontend_domain="old.example", frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    space.refresh_from_db()
    space.frontend_domain = "new.example"
    form = SimpleNamespace(changed_data=["frontend_domain"], cleaned_data={}, initial={"frontend_domain": "old.example"})
    with boundary_tenant_write(space.pk):
        admin.site._registry[Makerspace].save_model(_request(), space, form, True)
    space.refresh_from_db()
    assert space.frontend_domain_changed_at is not None
    # Self-host verifies a superadmin's domain at once; managed hosting sends it back to pending.
    assert space.frontend_domain_status in {Makerspace.DomainStatus.PENDING, Makerspace.DomainStatus.VERIFIED}
    assert space.frontend_domain_status != Makerspace.DomainStatus.VERIFIED or space.domain_verified_at is not None


def test_re_pasting_the_same_domain_keeps_it_verified():
    space = make_space("ctl-guard-same")
    Makerspace.objects.filter(pk=space.pk).update(
        frontend_domain="alpha.example", frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    space.refresh_from_db()
    # The raw "https://Alpha.example" differs from the initial value but normalises to it.
    form = SimpleNamespace(changed_data=["frontend_domain"], cleaned_data={}, initial={"frontend_domain": "alpha.example"})
    with boundary_tenant_write(space.pk):
        admin.site._registry[Makerspace].save_model(_request(), space, form, True)
    space.refresh_from_db()
    assert (space.frontend_domain_status, space.frontend_domain_changed_at) == (Makerspace.DomainStatus.VERIFIED, None)


def test_a_new_makerspace_has_no_membership_inline():
    # It has no roles until saved; a row there would skip the same-space role check.
    model_admin = admin.site._registry[Makerspace]
    request = _request()
    assert model_admin.get_inline_instances(request, None) == []
    assert model_admin.get_inline_instances(request, make_space("ctl-guard-inline"))


def test_procurement_status_change_is_stamped_from_control():
    space = make_space("ctl-guard-buy")
    actor = make_user("ctl-guard-buyer")
    item = ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Solder", created_by=actor)
    previous = item.status
    item.status = ToBuyItem.Status.ORDERED
    item.save()
    stamp_status_change(item, actor, previous)
    item.refresh_from_db()
    assert item.ordered_at is not None and item.purchaser_id == actor.pk


def test_api_key_note_is_typed_while_pending_and_frozen_once_resolved():
    model_admin = admin.site._registry[ApiKeyRequest]
    request = _request()
    pending = ApiKeyRequest(status=ApiKeyRequest.Status.PENDING)
    resolved = ApiKeyRequest(status=ApiKeyRequest.Status.REJECTED)
    # The note goes out in the requester's notification, and nothing else can write it.
    assert "resolution_note" not in model_admin.get_readonly_fields(request, pending)
    assert "resolution_note" in model_admin.get_readonly_fields(request, resolved)


@override_settings(ALLOW_PRIVATE_SMTP_HOSTS=False)
def test_a_lone_smtp_port_is_checked_against_the_makerspace_host():
    space = make_space("ctl-guard-port")
    Makerspace.objects.filter(pk=space.pk).update(smtp_host="smtp.example", smtp_port=587)
    # Only the changed port is written next to the stored host, so it must pass the allowlist.
    form = ApiClientAdminForm(data={"makerspace": space.pk, "smtp_port": 6379})
    assert not form.is_valid()
    assert "one of 25, 465, 587, or 2525" in str(form.errors.get("smtp_port"))


def test_control_stores_a_bare_custom_domain():
    form = MakerspaceAdminForm(instance=make_space("ctl-guard-bare"))
    form.cleaned_data = {"frontend_domain": "https://Lab.Example/admin"}
    assert form.clean_frontend_domain() == "lab.example"
    form.cleaned_data = {"frontend_domain": "not a host!"}
    with pytest.raises(forms.ValidationError):
        form.clean_frontend_domain()


@pytest.mark.parametrize(("model", "add", "delete"), [
    (StocktakeSession, False, False),
    (QrCode, False, None),
    (InventoryAsset, False, False),
    (PublicProblemReport, False, False),
])
def test_rows_owned_by_a_service_are_not_hand_added_or_deleted(model, add, delete):
    model_admin = admin.site._registry[model]
    request = _request()
    assert model_admin.has_add_permission(request) is add
    if delete is not None:
        assert model_admin.has_delete_permission(request) is delete


def test_print_batch_items_are_read_only():
    inline = QrPrintBatchItemInline(QrPrintBatch, admin.site)
    request = _request()
    assert not inline.has_add_permission(request, None)
    assert not inline.can_delete
    projection = ("qr_code_display", "label_text", "target_type", "target_id", "sort_order")
    assert inline.get_fields(request) == projection
    assert inline.get_readonly_fields(request) == projection
    assert "qr_code" not in inline.get_fields(request)
    assert "qr_code" not in inline.get_readonly_fields(request)


def test_tenancy_is_fixed_once_a_row_exists():
    request = _request()
    space = make_space("ctl-guard-tenancy")
    custom_type = MachineType(makerspace=space, slug="loom", is_builtin=False)
    rows = [
        (MachineType, custom_type, {"makerspace"}),
        (Box, Box(makerspace=space), {"makerspace"}),
        (InventoryProduct, InventoryProduct(makerspace=space), {"makerspace"}),
        (ToBuyItem, ToBuyItem(makerspace=space), {"makerspace", "kind"}),
        (QrPrintBatch, QrPrintBatch(makerspace=space), {"makerspace"}),
    ]
    for model, obj, fields in rows:
        model_admin = admin.site._registry[model]
        assert fields <= set(model_admin.get_readonly_fields(request, obj)), model
        # Creation still picks the space.
        assert "makerspace" not in model_admin.get_readonly_fields(request, None), model
