"""Retain native QR admission across dispatch, canonical audit, history and commit."""

from contextlib import contextmanager

from django import forms
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.options import TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied as PolicyPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.boxes.exceptions import Conflict
from apps.boxes.models import QrCode
from apps.boxes.qr_admission import current_qr_actor, qr_identity, qr_sources, qr_write
from apps.boxes.rebind import preflight_rebind
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


class QrRebindAdminForm(forms.Form):
    target_type = forms.ChoiceField(
        choices=[
            (QrCode.TargetType.PRODUCT, "Product"),
            (QrCode.TargetType.ASSET, "Asset"),
        ]
    )
    product_target = forms.ModelChoiceField(queryset=InventoryProduct.objects.none(), required=False)
    asset_target = forms.ModelChoiceField(queryset=InventoryAsset.objects.none(), required=False)
    destination_makerspace = forms.ModelChoiceField(queryset=Makerspace.objects.none(), required=False)
    destination_product = forms.ModelChoiceField(queryset=InventoryProduct.objects.none(), required=False)
    new_name = forms.CharField(required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        visible_spaces = servable_queryset(Makerspace.objects.filter(
            superadmin_access_enabled=True,
        )).order_by("name")
        visible_space_ids = visible_spaces.values("id")
        visible_products = InventoryProduct.objects.select_related("makerspace").filter(
            makerspace_id__in=visible_space_ids,
            is_archived=False,
        ).order_by("makerspace__name", "name")
        self.fields["destination_makerspace"].queryset = visible_spaces
        self.fields["product_target"].queryset = visible_products
        self.fields["destination_product"].queryset = visible_products
        self.fields["asset_target"].queryset = (
            InventoryAsset.objects.select_related("makerspace", "product")
            .filter(makerspace_id__in=visible_space_ids)
            .order_by("makerspace__name", "asset_tag")
        )

    def clean(self):
        cleaned = super().clean()
        target_type = cleaned.get("target_type")
        if target_type == QrCode.TargetType.PRODUCT and not cleaned.get("product_target"):
            raise forms.ValidationError("Select a product target.")
        if target_type == QrCode.TargetType.ASSET and not cleaned.get("asset_target"):
            raise forms.ValidationError("Select an asset target.")
        destination_product = cleaned.get("destination_product")
        destination_makerspace = cleaned.get("destination_makerspace")
        if (
            destination_product
            and destination_makerspace
            and destination_product.makerspace_id != destination_makerspace.id
        ):
            raise forms.ValidationError(
                "Destination product must belong to the destination makerspace."
            )
        return cleaned

    def rebind_payload(self):
        target_type = self.cleaned_data["target_type"]
        target = (
            self.cleaned_data["product_target"]
            if target_type == QrCode.TargetType.PRODUCT
            else self.cleaned_data["asset_target"]
        )
        payload = {
            "target_type": target_type,
            "target_id": target.id,
            "new_name": self.cleaned_data.get("new_name", ""),
        }
        if self.cleaned_data.get("destination_makerspace"):
            payload["destination_makerspace_id"] = self.cleaned_data[
                "destination_makerspace"
            ].id
        if self.cleaned_data.get("destination_product"):
            payload["destination_product_id"] = self.cleaned_data["destination_product"].id
        return payload


class QrLifecycleMixin:
    def _assert_source_gate(self, request, *, object_id=None, queryset=None):
        # QR-local wrappers below authorize the actual effective selection first.
        # The inherited raw POST-id guard cannot handle select_across or filtering.
        return None

    def _fresh_rows(self, request, snapshots, *, locked=False):
        admitted = Q(pk__in=[])
        for pk, identity in snapshots.items():
            admitted |= Q(pk=pk, makerspace_id=identity[0])
        queryset = self.get_queryset(request).filter(admitted).order_by("pk")
        if locked:
            queryset = queryset.select_for_update()
        rows = list(queryset)
        if {row.pk: qr_identity(row) for row in rows} != snapshots:
            # Native Django views do not render DRF APIException subclasses.
            # A vanished/moved native selection remains a scoped 404, not a 500.
            raise Http404("QR selection changed while waiting; retry the operation.")
        return rows

    @contextmanager
    def _qr_rows(self, request, rows, extra_tenants=()):
        snapshots = {row.pk: qr_identity(row) for row in rows}
        tenants = {identity[0] for identity in snapshots.values()} | set(extra_tenants)
        try:
            request.user = current_qr_actor(request.user, native=True, makerspace_ids=tenants)
            self._fresh_rows(request, snapshots)  # Unlocked ownership preflight.
            with qr_write(tenants):
                fresh = self._fresh_rows(request, snapshots, locked=True)
                request.user = current_qr_actor(request.user, native=True, makerspace_ids=tenants)
                yield fresh
                # Custom services can wait on asset/product rows after our QR lock.
                # A policy change during that wait must roll back their writes too.
                request.user = current_qr_actor(request.user, native=True, makerspace_ids=tenants)
        except PolicyPermissionDenied as exc:
            raise PermissionDenied(str(exc.detail)) from exc

    def _selected_object(self, request, object_id):
        to_field = request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))
        if to_field and not self.to_field_allowed(request, to_field):
            raise DisallowedModelAdminToField(to_field)
        obj = self.get_object(request, unquote(object_id), to_field)
        return [] if obj is None else [obj]

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST" or object_id is None:
            return super().changeform_view(request, object_id, form_url, extra_context)
        with self._qr_rows(request, self._selected_object(request, object_id)):
            return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        if not change:
            raise PermissionDenied()
        with self._qr_rows(request, [obj]) as rows:
            fresh = rows[0]
            # Only created_by is editable. Copy the fresh row before the full save,
            # so a direct/stale caller cannot resurrect a row or undo a rebind.
            created_by_id = obj.created_by_id
            for field in obj._meta.concrete_fields:
                setattr(obj, field.attname, getattr(fresh, field.attname))
            if "created_by" in form.changed_data:
                obj.created_by_id = created_by_id
            return super().save_model(request, obj, form, change)

    def delete_view(self, request, object_id, extra_context=None):
        if request.method != "POST":
            return super().delete_view(request, object_id, extra_context)
        with self._qr_rows(request, self._selected_object(request, object_id)):
            return super().delete_view(request, object_id, extra_context)

    def delete_model(self, request, obj):
        with self._qr_rows(request, [obj]) as rows:
            return super().delete_model(request, rows[0])

    def delete_queryset(self, request, queryset):
        selected = getattr(request, "_qr_delete_rows", None)
        with self._qr_rows(request, selected if selected is not None else list(queryset)) as rows:
            surviving = self.get_queryset(request).filter(pk__in=[row.pk for row in rows])
            return super().delete_queryset(request, surviving)

    def response_action(self, request, queryset):
        # Match Django's validated action form and its index/select_across rules;
        # queryset is already the ChangeList's search/filter/visibility result.
        try:
            index = int(request.POST.get("index", 0))
        except ValueError:
            index = 0
        data = request.POST.copy()
        data.pop(ACTION_CHECKBOX_NAME, None)
        data.pop("index", None)
        try:
            data.update({"action": data.getlist("action")[index]})
        except IndexError:
            pass
        form = self.action_form(data, auto_id=None)
        form.fields["action"].choices = self.get_action_choices(request)
        if not form.is_valid():
            return super().response_action(request, queryset)
        if not form.cleaned_data["select_across"]:
            queryset = queryset.filter(pk__in=request.POST.getlist(ACTION_CHECKBOX_NAME))
        rows = list(queryset)
        admission = None
        extra_tenants = set()
        if form.cleaned_data["action"] == "rebind_selected" and "apply" in request.POST and len(rows) == 1:
            rebind_form = QrRebindAdminForm(request.POST)
            if rebind_form.is_valid():
                payload = rebind_form.rebind_payload()
                try:
                    admission = preflight_rebind(request.user, rows[0].pk, payload)
                except (DRFValidationError, Conflict) as exc:
                    detail = exc.detail
                    if isinstance(detail, (list, tuple)):
                        detail = "; ".join(str(message) for message in detail)
                    rebind_form.add_error(None, str(detail))
                    return self._rebind_response(request, queryset, rebind_form)
                except PolicyPermissionDenied as exc:
                    raise PermissionDenied(str(exc.detail)) from exc
                extra_tenants = admission[3]
        if form.cleaned_data["action"] == "delete_selected":
            return self._delete_action_dispatch(request, rows)
        with self._qr_rows(request, rows, extra_tenants) as fresh:
            request._qr_rebind_admission = admission
            try:
                effective = self.get_queryset(request).filter(pk__in=[row.pk for row in fresh])
                return super().response_action(request, effective)
            finally:
                del request._qr_rebind_admission

    def _delete_action_dispatch(self, request, rows):
        tenants = {row.makerspace_id for row in rows}
        try:
            request.user = current_qr_actor(request.user, native=True, makerspace_ids=tenants)
            snapshots = {row.pk: qr_identity(row) for row in rows}
            self._fresh_rows(request, snapshots)
            with qr_sources(tenants):
                self._fresh_rows(request, snapshots)
                request.user = current_qr_actor(request.user, native=True, makerspace_ids=tenants)
                request._qr_delete_rows = rows
                try:
                    effective = self.get_queryset(request).filter(pk__in=[row.pk for row in rows])
                    return super().response_action(request, effective)
                finally:
                    del request._qr_delete_rows
        except PolicyPermissionDenied as exc:
            raise PermissionDenied(str(exc.detail)) from exc
        # Django bulk LogEntry attempts precede delete_queryset's atomic block;
        # that existing limitation remains. Canonical audit and Collector roll back.
