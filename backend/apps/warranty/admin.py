from apps.object_storage_admin import StorageDocumentDeleteAdminMixin
from django.contrib import admin
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.options import TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework.exceptions import PermissionDenied as PolicyPermissionDenied
from rest_framework.exceptions import ValidationError as PolicyValidationError
from unfold.admin import ModelAdmin

from apps.separability.tombstones import app_is_tombstoned
from apps.warranty.admin_forms import (
    WarrantyAdminForm,
    admitted_add_tenant,
    check_admission,
    lock_host,
    lock_makerspace,
    warranty_identity,
)
from apps.warranty.access import enforce
from apps.warranty.models import Warranty, WarrantyDocument
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_audit import AdminAuditMixin
from config.admin_source_gate import admin_tenant_write


class WarrantyAdmin(StorageDocumentDeleteAdminMixin, AdminAuditMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    form = WarrantyAdminForm
    storage_makerspace_path = "makerspace_id"
    list_display = (
        "id",
        "makerspace",
        "host",
        "asset",
        "machine",
        "purchased_on",
        "warranty_expires_on",
        "vendor_name",
    )
    list_filter = ("makerspace",)
    search_fields = (
        "vendor_name",
        "vendor_contact",
        "asset__asset_tag",
        "machine__name",
        "makerspace__name",
        "makerspace__slug",
    )
    raw_id_fields = ("makerspace", "asset", "machine")
    readonly_fields = ("created_at", "updated_at")

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        if object_id is not None and "_saveasnew" in request.POST:
            raise PermissionDenied("Save as new is not allowed for a warranty change.")
        expected = None
        if object_id is not None:
            to_field = request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))
            if to_field and not self.to_field_allowed(request, to_field):
                raise DisallowedModelAdminToField(to_field)
            # This visible snapshot deliberately precedes Django's atomic block.
            obj = super().get_object(request, unquote(object_id), to_field)
            if obj is None:
                raise Http404
            expected = warranty_identity(obj)
            tenant = expected[1]
        else:
            tenant = admitted_add_tenant(request)
        request._warranty_expected = expected
        request._warranty_tenant = tenant
        try:
            with admin_tenant_write([tenant]):
                return super().changeform_view(request, object_id, form_url, extra_context)
        finally:
            del request._warranty_expected
            del request._warranty_tenant

    def _assert_source_gate(self, request, *, object_id=None, queryset=None):
        if hasattr(request, "_warranty_tenant"):
            # Never rediscover tenant B after a canonical transfer from tenant A.
            if request._warranty_tenant is not None:
                from apps.tenant_migration.gate_runtime import assert_write_allowed

                assert_write_allowed(request._warranty_tenant)
            return
        return super()._assert_source_gate(request, object_id=object_id, queryset=queryset)

    def _changeform_view(self, request, object_id, form_url, extra_context):
        if request.method != "POST":
            return super()._changeform_view(request, object_id, form_url, extra_context)
        # Django calls this inside atomic; delete's pre-atomic get_object is untouched.
        request._warranty_changeform_post = True
        try:
            return super()._changeform_view(request, object_id, form_url, extra_context)
        finally:
            del request._warranty_changeform_post

    def get_object(self, request, object_id, from_field=None):
        if not getattr(request, "_warranty_changeform_post", False):
            return super().get_object(request, object_id, from_field)
        expected = request._warranty_expected
        if expected is None:
            return super().get_object(request, object_id, from_field)
        pk, tenant, asset_id, machine_id = expected
        kind, host_id = ("asset", asset_id) if asset_id else ("machine", machine_id)
        try:
            # Source boundary -> Makerspace NO KEY UPDATE -> concrete host -> Warranty.
            makerspace = lock_makerspace(tenant, [kind])
            host = lock_host(kind, host_id, tenant)
            if host is None:
                raise Http404
            obj = (
                self.get_queryset(request).select_related(None).select_for_update()
                .filter(pk=pk).first()
            )
            if obj is None or warranty_identity(obj) != expected:
                raise Http404
            obj.makerspace = makerspace
            host.makerspace = makerspace
            setattr(obj, kind, host)
            check_admission(request, makerspace)
            enforce(request.user, obj)
        except (PolicyPermissionDenied, PolicyValidationError) as exc:
            raise PermissionDenied(str(exc.detail)) from exc
        return obj

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)

        class RequestWarrantyForm(form):
            admin_request = request

        return RequestWarrantyForm

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields if obj is None else (*fields, "makerspace", "asset", "machine")

    @admin.display(description="Host")
    def host(self, obj):
        if obj.machine_id:
            return obj.machine
        if obj.asset_id:
            return obj.asset
        return None


class WarrantyDocumentAdmin(StorageDocumentDeleteAdminMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    storage_makerspace_path = "warranty__makerspace_id"
    list_display = ("id", "warranty", "original_filename", "content_type", "size_bytes", "created_at")
    list_filter = ("content_type",)
    search_fields = ("original_filename", "object_key", "warranty__vendor_name")
    readonly_fields = (
        "warranty",
        "object_key",
        "original_filename",
        "content_type",
        "size_bytes",
        "uploaded_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Registered rather than decorated: the admin screens are runtime surfaces a tombstone
# removes, while the rows stay reachable through the ORM and the purge path. The
# setting is consulted instead of the manifest because admin autodiscovery runs before
# this app's ready(). See separability.tombstones.app_is_tombstoned.
if not app_is_tombstoned("warranty"):
    admin.site.register(Warranty, WarrantyAdmin)
    admin.site.register(WarrantyDocument, WarrantyDocumentAdmin)
