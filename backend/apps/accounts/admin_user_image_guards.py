"""Visible clear-first refusals for global User admin deletion and its cascades."""
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse

from apps.makerspaces.models import MemberProfile, MemberProject
from apps.makerspaces.profile_delete_guards import (
    CLEAR_IMAGES_FIRST,
    ProfileImageDeleteProtected,
)


class UserImageDeleteAdminMixin:
    def get_deleted_objects(self, objs, request):
        # Keep Django's existing document-FK PROTECT results intact.
        objs = list(objs)
        deleted, counts, perms, protected = super().get_deleted_objects(objs, request)
        user_ids = [obj.pk for obj in objs]
        if (MemberProfile.objects.filter(membership__user_id__in=user_ids)
                .exclude(avatar_key="").exists()
                or MemberProject.objects.filter(profile__membership__user_id__in=user_ids)
                .exclude(image_key="").exists()):
            protected = [*protected, CLEAR_IMAGES_FIRST]
        return deleted, counts, perms, protected

    def _image_delete_refused(self, request):
        self.message_user(request, CLEAR_IMAGES_FIRST, level=messages.ERROR)
        return HttpResponseRedirect(reverse(
            f"{self.admin_site.name}:{self.opts.app_label}_{self.opts.model_name}_changelist",
        ))

    def delete_view(self, request, object_id, extra_context=None):
        try:
            return super().delete_view(request, object_id, extra_context)
        except ProfileImageDeleteProtected:
            # The inherited view has already unwound its deletion transaction.
            return self._image_delete_refused(request)

    def delete_queryset(self, request, queryset):
        # Admin's delete-selected action has no surrounding transaction. Ensure
        # the caught refusal rolls back the whole batch, including delete signals.
        with transaction.atomic():
            return super().delete_queryset(request, queryset)

    def changelist_view(self, request, extra_context=None):
        try:
            return super().changelist_view(request, extra_context)
        except ProfileImageDeleteProtected:
            return self._image_delete_refused(request)
