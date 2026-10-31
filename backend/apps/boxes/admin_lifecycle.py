"""Source/Maker serialization around native Box writes and actual collectors."""

from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.options import TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied as PolicyPermissionDenied

from apps.boxes.services import box_write_makerspace
from apps.makerspaces.models import Makerspace
from config.admin_source_gate import admin_tenant_write


class BoxLifecycleMixin:
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        if object_id is not None:
            to_field = request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))
            if to_field and not self.to_field_allowed(request, to_field):
                raise DisallowedModelAdminToField(to_field)
            obj = self.get_object(request, unquote(object_id), to_field)
            makerspace_id = obj.makerspace_id if obj is not None else None
        else:
            try:
                makerspace_id = Makerspace._meta.pk.to_python(request.POST.get("makerspace"))
            except (ValidationError, TypeError, ValueError):
                makerspace_id = None
        # Span Django's atomic changeform, including form admission, service save
        # and commit. Nested admission reuses this source boundary under row locks.
        with admin_tenant_write([makerspace_id]):
            return super().changeform_view(request, object_id, form_url, extra_context)

    def delete_model(self, request, obj):
        with admin_tenant_write([obj.makerspace_id]), transaction.atomic():
            self._admit_box_delete(request, obj.makerspace_id)
            fresh = get_object_or_404(
                self.get_queryset(request), pk=obj.pk, makerspace_id=obj.makerspace_id,
            )
            return super().delete_model(request, fresh)

    def delete_queryset(self, request, queryset):
        selected = list(queryset.values_list("pk", "makerspace_id"))
        makerspace_ids = sorted({makerspace_id for _, makerspace_id in selected})
        # Admit ALL sources before taking ANY Maker lock. This outer atomic is
        # needed because the shared audit mixin's atomic starts after our locks.
        with admin_tenant_write(makerspace_ids), transaction.atomic():
            for makerspace_id in makerspace_ids:
                self._admit_box_delete(request, makerspace_id)
            surviving = self.get_queryset(request).filter(pk__in=[pk for pk, _ in selected])
            return super().delete_queryset(request, surviving)

    def _admit_box_delete(self, request, makerspace_id):
        try:
            box_write_makerspace(request.user, makerspace_id, native=True)
        except PolicyPermissionDenied as exc:
            raise PermissionDenied(str(exc.detail)) from exc
