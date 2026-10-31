"""Request-bound validation for the native warranty admin's add form."""

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from rest_framework.exceptions import PermissionDenied as PolicyPermissionDenied
from rest_framework.exceptions import ValidationError as PolicyValidationError

from apps.accounts.models import User
from apps.admin_api.permissions import active_user
from apps.inventory.models import InventoryAsset
from apps.machines.models import Machine
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import is_servable
from apps.tenant_migration.gate_runtime import assert_write_allowed
from apps.warranty.access import enforce
from apps.warranty.models import Warranty


def warranty_identity(obj):
    return obj.pk, obj.makerspace_id, obj.asset_id, obj.machine_id


def admitted_add_tenant(request):
    """Use the same visible makerspaces as the admin FK field; bad input stays a form error."""
    try:
        pk = Makerspace._meta.pk.to_python(request.POST.get("makerspace"))
    except (ValidationError, TypeError, ValueError):
        return None
    return (
        Makerspace.objects.filter(pk=pk, superadmin_access_enabled=True)
        .values_list("pk", flat=True).first()
    )


def lock_makerspace(tenant, host_kinds):
    # All module locks precede concrete host locks, and none upgrades the tenant lock.
    try:
        makerspace = Makerspace.objects.select_for_update(no_key=True).get(pk=tenant)
    except Makerspace.DoesNotExist as exc:
        raise Http404 from exc
    assert_write_allowed(tenant)
    for kind in host_kinds:
        require_module(makerspace, "machines" if kind == "machine" else "staff_admin")
    return makerspace


def lock_host(kind, pk, tenant):
    model = InventoryAsset if kind == "asset" else Machine
    return model.objects.select_for_update().filter(pk=pk, makerspace_id=tenant).first()


def check_admission(request, makerspace):
    """Recheck the original tenant and a fresh actor after every row-lock wait."""
    actor = User.objects.filter(pk=request.user.pk).first()
    if not active_user(actor) or not actor.is_superuser:
        raise PermissionDenied
    request.user = actor
    if not makerspace.superadmin_access_enabled:
        raise Http404
    assert_write_allowed(request._warranty_tenant)
    if not is_servable(makerspace):
        raise PermissionDenied("This makerspace is not available.")


class WarrantyAdminForm(forms.ModelForm):
    class Meta:
        model = Warranty
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        request = self.admin_request
        if not self.is_bound or self.instance.pk:
            return cleaned
        makerspace = cleaned.get("makerspace")
        if makerspace is None:
            return cleaned
        if makerspace.pk != request._warranty_tenant:
            raise ValidationError({"makerspace": "Select a valid makerspace."})
        hosts = {kind: cleaned[kind] for kind in ("asset", "machine") if cleaned.get(kind)}
        try:
            makerspace = lock_makerspace(makerspace.pk, hosts)
            for kind, selected in hosts.items():
                host = lock_host(kind, selected.pk, makerspace.pk)
                if host is None:
                    raise ValidationError({kind: "Host must belong to the same makerspace."})
                host.makerspace = makerspace
                cleaned[kind] = host
            cleaned["makerspace"] = makerspace
            check_admission(request, makerspace)
            for kind in hosts:
                enforce(request.user, Warranty(makerspace=makerspace, **{kind: cleaned[kind]}))
        except PolicyPermissionDenied as exc:
            raise PermissionDenied(str(exc.detail)) from exc
        except PolicyValidationError as exc:
            raise ValidationError(str(exc.detail)) from exc
        # Parent _post_clean still constructs the instance and runs full_clean,
        # uniqueness and constraints, now using the locked host rather than its FK lookup.
        return cleaned
