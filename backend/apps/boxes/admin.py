import segno
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe
from rest_framework.exceptions import APIException
from unfold.admin import ModelAdmin

from apps.boxes.admin_forms import BoxAdminForm
from apps.boxes.admin_lifecycle import BoxLifecycleMixin
from apps.boxes.admin_qr_lifecycle import QrLifecycleMixin, QrRebindAdminForm
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.boxes.exceptions import Conflict
from apps.boxes.qr_render import render_qr_label_svg
from apps.boxes.rebind import rebind_qr_target
from apps.boxes.serializers import QrRebindTargetSerializer
from apps.boxes.services import create_box_with_qr, revoke_qr_code
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_audit import AdminAuditMixin
from apps.encryption.admin_search import ScopedPiiAdminSearchMixin


@admin.register(Box)
class BoxAdmin(BoxLifecycleMixin, AdminAuditMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    form = BoxAdminForm
    list_display = ("label", "makerspace", "parent", "code", "is_active", "updated_at")
    list_filter = ("makerspace", "is_active")
    search_fields = ("label", "code", "location")
    autocomplete_fields = ("makerspace", "parent")
    readonly_fields = ("code", "qr_preview", "created_at", "updated_at")

    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)

        class RequestBoundForm(form_class):
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, actor=request.user, **form_kwargs)

        return RequestBoundForm

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        create_box_with_qr(request.user, obj, native=True)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        # Its products, assets and QR stay in the original space; moving the box would
        # split them across tenants.
        return fields if obj is None else (*fields, "makerspace")

    def qr_preview(self, obj):
        if not obj or not obj.pk:
            return "(save first to generate the QR)"
        return mark_safe(segno.make(obj.code).svg_inline(scale=4))

    qr_preview.short_description = "QR tag"


@admin.register(QrCode)
class QrCodeAdmin(QrLifecycleMixin, AdminAuditMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["revoke_selected", "rebind_selected"]
    list_display = ("payload", "makerspace", "target_type", "target_id", "status", "updated_at")
    list_filter = ("makerspace", "target_type", "status")
    search_fields = ("payload",)
    readonly_fields = ("payload", "qr_preview", "created_at", "updated_at", "revoked_at")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is None:
            return fields
        # Revoking checks outstanding loans and rebinding validates the target; only the
        # actions do that, so an existing code's status and target are not hand-editable.
        return (*fields, "status", "target_type", "target_id", "makerspace")

    def has_add_permission(self, request):
        # Codes are minted by the services that own their target; a hand-made one could
        # point at a missing target or another space's.
        return False

    def qr_preview(self, obj):
        if not obj or not obj.pk:
            return "(no QR)"
        return mark_safe(render_qr_label_svg(obj.payload))

    qr_preview.short_description = "QR preview"

    @admin.action(description="Revoke selected QR codes")
    def revoke_selected(self, request, queryset):
        succeeded, skipped = 0, 0
        for qr in queryset:
            try:
                revoke_qr_code(request.user, qr)
            except APIException as exc:
                skipped += 1
                self.message_user(
                    request,
                    f"{qr.pk}: {_api_exception_message(exc)}",
                    level=messages.WARNING,
                )
            else:
                succeeded += 1
        self.message_user(
            request,
            f"Revoked {succeeded} QR code(s); skipped {skipped}.",
            level=messages.SUCCESS if succeeded else messages.WARNING,
        )

    @admin.action(description="Rebind selected QR code")
    def rebind_selected(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one QR code to rebind.", level=messages.ERROR)
            return None

        qr = queryset.first()
        if "apply" not in request.POST:
            form = QrRebindAdminForm()
            return self._rebind_response(request, queryset, form)

        form = QrRebindAdminForm(request.POST)
        if not form.is_valid():
            self.message_user(request, form.errors, level=messages.ERROR)
            return None

        serializer = QrRebindTargetSerializer(data=form.rebind_payload())
        if not serializer.is_valid():
            self.message_user(request, serializer.errors, level=messages.ERROR)
            return None

        try:
            if hasattr(request, "_qr_rebind_admission") and request._qr_rebind_admission is None:
                raise Conflict("Rebind selection changed before admission; retry the operation.")
            with transaction.atomic():
                result = rebind_qr_target(
                    request.user, qr.pk, serializer.validated_data,
                    admission=getattr(request, "_qr_rebind_admission", None),
                )
        except APIException as exc:
            self.message_user(request, _api_exception_message(exc), level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Rebound QR {result.qr.payload}.",
                level=messages.SUCCESS,
            )
        return None

    def _rebind_response(self, request, queryset, form):
        context = {
            **self.admin_site.each_context(request),
            "title": "Rebind QR code",
            "queryset": queryset,
            "opts": self.model._meta,
            "action_name": "rebind_selected",
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "form": form,
        }
        return TemplateResponse(request, "admin/boxes/rebind_qr.html", context)


@admin.register(QrScanEvent)
class QrScanEventAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("qr_code", "makerspace", "context", "actor", "created_at")
    list_filter = ("makerspace", "context")
    search_fields = ("qr_code__payload",)
    readonly_fields = ("qr_code", "makerspace", "request", "actor", "context", "created_at")
    fields = readonly_fields

    # Scan history is immutable evidence (Hard Rules): view only.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BoxScan)
class BoxScanAdmin(ScopedPiiAdminSearchMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("box", "box_qr", "makerspace", "context", "scanned_by", "created_at")
    list_filter = ("makerspace", "context")
    search_fields = (
        "box__label",
        "box__code",
        "actor__username",
        "actor__email",
    )
    pii_search_model = "hardware_requests.HardwareRequest"
    pii_search_relation = "request__"
    pii_search_fields = ("requester_name", "requester_contact_email")
    readonly_fields = ("makerspace", "box", "request", "actor", "context", "created_at")
    fields = readonly_fields
    ordering = ("-created_at",)

    @admin.display(description="QR", ordering="box__code")
    def box_qr(self, obj):
        return obj.box.code if obj.box_id else "-"

    @admin.display(description="Scanned by", ordering="actor")
    def scanned_by(self, obj):
        return obj.actor

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _api_exception_message(exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return "; ".join(f"{key}: {value}" for key, value in detail.items())
    return str(detail or exc)
