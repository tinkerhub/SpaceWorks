from apps.object_storage_admin import StorageDocumentDeleteAdminMixin
from django.contrib import admin, messages
from rest_framework.exceptions import APIException
from unfold.admin import ModelAdmin

from apps.makerspaces.admin_staff_membership import StaffMembershipForm, audit_staff_membership
from apps.makerspaces.membership_services import revoke_membership

from apps.makerspaces.models import (
    MakerspaceMembership,
    MakerspaceWaiver,
    MemberProfile,
    MemberProject,
    MembershipRequest,
)
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(MakerspaceMembership)
class MakerspaceMembershipAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Staff memberships: grant by picking a role, remove with the revoke action.

    `role` is only the legacy mirror and `status` has side effects on revocation, so both
    are derived here rather than typed -- see `admin_staff_membership`.
    """

    form = StaffMembershipForm
    actions = ["revoke_memberships"]
    list_display = ("user", "makerspace", "assigned_role", "status", "created_at")
    list_filter = ("makerspace", "status")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user", "makerspace")
    readonly_fields = (
        "role", "status", "revoked_at", "revoked_by", "revocation_reason",
        "can_refer", "can_verify", "verified_at", "verified_by", "verified_actor_snapshot",
        "activated_actor_snapshot", "revoked_actor_snapshot",
        "waiver_accepted_at", "waiver_version_accepted", "accepted_waiver",
        "witnessed_at", "witnessed_waiver_version", "witnessed_waiver",
        "witnessed_by", "witnessed_actor_snapshot", "created_at",
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change or form.changed_data:
            audit_staff_membership(request.user, obj, created=not change)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Revoke selected memberships")
    def revoke_memberships(self, request, queryset):
        revoked = skipped = 0
        for membership in queryset:
            if membership.status == "revoked":
                # The service would no-op; counting it would overstate what was done.
                skipped += 1
                continue
            try:
                revoke_membership(request.user, membership, reason="Revoked from /control/")
            except APIException as exc:
                self.message_user(request, f"{membership}: {exc.detail}", level=messages.ERROR)
            else:
                revoked += 1
        if revoked:
            self.message_user(request, f"Revoked {revoked} membership(s).", level=messages.SUCCESS)
        if skipped:
            self.message_user(
                request, f"Skipped {skipped} already-revoked membership(s).", level=messages.WARNING
            )


@admin.register(MakerspaceWaiver)
class MakerspaceWaiverAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("makerspace", "version", "is_active", "created_at", "superseded_at")
    readonly_fields = ("makerspace", "body", "version", "is_active", "created_by", "created_at", "superseded_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)


@admin.register(MembershipRequest)
class MembershipRequestAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("makerspace", "kind", "state", "user", "invite_email", "created_at")
    readonly_fields = tuple(field.name for field in MembershipRequest._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)


@admin.register(MemberProfile)
class MemberProfileAdmin(StorageDocumentDeleteAdminMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    storage_makerspace_path = "membership__makerspace_id"

    def storage_deleted_keys(self, obj):
        return (obj.avatar_key, *obj.projects.values_list("image_key", flat=True))

    """Read-only. A profile is the member's own writing, editable only by them.

    A superadmin needs to be able to SEE one — to answer a report about its content —
    but editing someone's self-description from the platform console would put words in
    their mouth. Removing it is the member's action or a `membership` purge.
    """

    list_display = ("membership", "is_visible", "github_username", "updated_at")
    list_filter = ("is_visible",)
    readonly_fields = tuple(field.name for field in MemberProfile._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)


@admin.register(MemberProject)
class MemberProjectAdmin(StorageDocumentDeleteAdminMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    storage_makerspace_path = "profile__membership__makerspace_id"

    def storage_deleted_keys(self, obj):
        return (obj.image_key,)

    list_display = ("title", "profile", "position", "updated_at")
    readonly_fields = tuple(field.name for field in MemberProject._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)
