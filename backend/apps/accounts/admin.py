from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db import transaction
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserCreationForm
from rest_framework.exceptions import APIException

from apps.accounts.admin_membership_inline import (
    MakerspaceMembershipInline,
    StaffMembershipAdminMixin,
)
from apps.accounts.admin_user_control import (
    ControlUserChangeForm,
    UserControlAdminMixin,
    api_exception_message as _api_exception_message,
)
from apps.accounts.admin_user_image_guards import UserImageDeleteAdminMixin
from apps.accounts.models import NativeAppRegistration, User
from apps.accounts.principal_guards import refuse_anonymous_requester_access_mutation
from apps.admin_api.services_user_access import reset_user_password
from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.models import MakerspaceMembership
from config.admin_access import SuperuserOnlyModelAdmin


class RestrictAccessForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            choice
            for choice in User.AccessStatus.choices
            if choice[0] != User.AccessStatus.ACTIVE
        ],
        required=True,
    )
    reason = forms.CharField(required=True, widget=forms.Textarea)


@admin.register(User)
class UserAdmin(
    UserImageDeleteAdminMixin, UserControlAdminMixin, StaffMembershipAdminMixin, SuperuserOnlyModelAdmin,
    DjangoUserAdmin, ModelAdmin,
):
    actions = ["restrict_access", "restore_access", "reset_password_selected"]
    form = ControlUserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    fieldsets = tuple(
        (name, {**options, "fields": tuple(
            field for field in options["fields"] if field not in ("groups", "user_permissions")
        )})
        for name, options in DjangoUserAdmin.fieldsets
    ) + (
        (
            "Space Works Access",
            {
                "fields": (
                    "phone",
                    "external_checkin_user_id",
                    "role",
                    "access_status",
                    "restriction_reason",
                ),
            },
        ),
    )
    list_display = ("username", "email", "role", "access_status", "is_staff")
    list_filter = tuple(field for field in DjangoUserAdmin.list_filter if field != "groups") + (
        "role",
        "access_status",
        "makerspace_memberships__makerspace",
    )
    inlines = (MakerspaceMembershipInline,)
    filter_horizontal = ()
    # Restricting/restoring audits, guards walk-in records and re-checks the staff quota;
    # the Restrict/Restore actions do that, a raw field edit would not.
    readonly_fields = ("access_status", "restriction_reason")

    @admin.action(description="Reset selected user passwords")
    def reset_password_selected(self, request, queryset):
        succeeded, skipped = 0, 0
        for user in queryset:
            try:
                result = reset_user_password(request.user, user.pk)
            except APIException as exc:
                skipped += 1
                self.message_user(
                    request,
                    f"{user.username}: {_api_exception_message(exc)}",
                    level=messages.WARNING,
                )
            else:
                succeeded += 1
                self.message_user(
                    request,
                    f"{result.user.username}: {result.temporary_password}",
                    level=messages.SUCCESS,
                )
        self.message_user(
            request,
            f"Reset {succeeded} password(s); skipped {skipped}.",
            level=messages.SUCCESS if succeeded else messages.WARNING,
        )

    @admin.action(description="Restrict selected users")
    def restrict_access(self, request, queryset):
        if "apply" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Restrict selected users",
                "queryset": queryset,
                "opts": self.model._meta,
                "action_name": "restrict_access",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
                "status_choices": RestrictAccessForm.base_fields["status"].choices,
            }
            return TemplateResponse(
                request,
                "admin/accounts/restrict_access_action.html",
                context,
            )

        form = RestrictAccessForm(request.POST)
        if not form.is_valid():
            self.message_user(request, form.errors, level=messages.ERROR)
            return None

        success_count = 0
        status = form.cleaned_data["status"]
        reason = form.cleaned_data["reason"]
        for user in queryset:
            try:
                refuse_anonymous_requester_access_mutation(user)
            except APIException as exc:
                self.message_user(
                    request,
                    f"{user.username}: {_api_exception_message(exc)}",
                    level=messages.ERROR,
                )
            else:
                user.access_status = status
                user.restriction_reason = reason
                user.save(update_fields=["access_status", "restriction_reason"])
                audit.record(
                    request.user,
                    "user.access_restricted",
                    target=user,
                    meta={
                        "status": user.access_status,
                        "reason": user.restriction_reason,
                    },
                )
                success_count += 1

        self.message_user(
            request,
            f"Restricted {success_count} user(s).",
            level=messages.SUCCESS,
        )
        return None

    @admin.action(description="Restore selected users")
    def restore_access(self, request, queryset):
        success_count = 0
        for user in queryset:
            try:
                with transaction.atomic():
                    locked = User.objects.select_for_update().get(pk=user.pk)
                    refuse_anonymous_requester_access_mutation(locked)
                    if locked.access_status != User.AccessStatus.ACTIVE and locked.is_active:
                        memberships = MakerspaceMembership.objects.select_related(
                            "makerspace"
                        ).filter(user=locked).order_by("makerspace_id")
                        for membership in memberships:
                            limits.check_quota(
                                membership.makerspace, "staff", adding=1
                            )
                    locked.access_status = User.AccessStatus.ACTIVE
                    locked.restriction_reason = ""
                    locked.save(update_fields=["access_status", "restriction_reason"])
                    audit.record(request.user, "user.access_restored", target=locked)
            except APIException as exc:
                self.message_user(
                    request,
                    f"{user.username}: {_api_exception_message(exc)}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"Restored access for {success_count} user(s).",
                level=messages.SUCCESS,
            )


@admin.register(NativeAppRegistration)
class NativeAppRegistrationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "app_id", "platform", "environment", "makerspace", "status", "updated_at",
    )
    list_filter = ("status", "platform", "environment", "makerspace")
    search_fields = ("app_id", "verifier_config_key", "makerspace__name")
    autocomplete_fields = ("makerspace", "approved_by")
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        """Route a revocation through the service so live grants are settled too.

        Saving `status = revoked` on the row alone would leave existing grants and refresh
        tokens intact, so re-approving later would resurrect them.
        """
        becoming_revoked = (
            obj.status == NativeAppRegistration.Status.REVOKED
            and (not change or "status" in (form.changed_data or []))
        )
        super().save_model(request, obj, form, change)
        if becoming_revoked:
            from apps.accounts.services_native_apps import revoke_registration

            revoke_registration(obj, actor=request.user)


from apps.accounts import admin_claim, admin_social  # noqa: E402,F401
from apps.accounts import admin_password_reset, admin_unregistered  # noqa: E402,F401
