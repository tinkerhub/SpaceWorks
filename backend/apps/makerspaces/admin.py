from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin

from apps.makerspaces.admin_capabilities import MakerspaceAdminForm, MakerspaceCapabilityAdminMixin
from apps.makerspaces.admin_images import MakerspaceImageAdminMixin
from apps.makerspaces.admin_staff_membership import (
    MakerspaceMembershipInline,
    audit_staff_memberships,
)
from apps.makerspaces.admin_subdomains import SubdomainRequestAdmin
from apps.makerspaces.admin_archive_requests import MakerspaceArchiveRequestAdmin
from apps.makerspaces.admin_imports import (  # noqa: F401
    ImportedUserReconciliationAdmin,
    PendingImportedMembershipAdmin,
)
from apps.makerspaces.models import (
    Makerspace, MakerspaceArchiveRequest,
)
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_audit import AdminAuditMixin


class ArchivedFilter(admin.SimpleListFilter):
    title = "archived"
    parameter_name = "archived"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Yes"),
            ("no", "No"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(archived_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(archived_at__isnull=True)
        return queryset


@admin.register(Makerspace)
class MakerspaceAdmin(
    AdminAuditMixin, MakerspaceImageAdminMixin, MakerspaceCapabilityAdminMixin,
    SuperuserOnlyModelAdmin, ModelAdmin,
):
    form = MakerspaceAdminForm
    # Audited by the capability and image mixins with their own actions.
    audit_exclude_fields = ("capabilities", "logo_upload", "clear_logo", "cover_upload", "clear_cover")
    actions = ["archive_makerspaces", "unarchive_makerspaces", "purge_makerspaces"]
    list_display = (
        "name",
        "public_code",
        "item_code_prefix",
        "slug",
        "location",
        "public_inventory_enabled",
        "superadmin_access",
        "frontend_domain",
        "hidden_from_central_directory",
        "frontend_mode",
        "archived",
        "updated_at",
    )
    list_filter = ("public_inventory_enabled", "superadmin_access_enabled", ArchivedFilter)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "public_code", "slug", "location")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "public_code",
                    "item_code_prefix",
                    "slug",
                    "location",
                    "public_inventory_enabled",
                    "public_stats_enabled",
                    "public_stats_show_holder_names",
                    "frontend_domain",
                    "hidden_from_central_directory",
                    "default_loan_days",
                )
            },
        ),
        (
            "Capabilities",
            {"fields": ("capabilities",)},
        ),
        (
            "Public images",
            {
                "fields": (
                    "logo_preview",
                    "logo_upload",
                    "clear_logo",
                    "cover_preview",
                    "cover_upload",
                    "clear_cover",
                )
            },
        ),
    )
    readonly_fields = ("logo_preview", "cover_preview")
    inlines = (MakerspaceMembershipInline,)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        audit_staff_memberships(request, formset)

    def save_model(self, request, obj, form, change):
        """Initialise archive-custody state for makerspaces created via /control/.

        The control-plane admin saves the model directly, so it never reaches the
        admin-API serializer that seeds this row. Without it a new makerspace has no
        custody state, which makes readiness UNDERCOUNT below-floor spaces and the API
        return null until some later recipient mutation happens to create it.
        """
        # Compare the stored host: re-pasting `https://Alpha.com` for `alpha.com` is no change
        # and must not send a verified domain back to pending.
        if "frontend_domain" in form.changed_data and obj.frontend_domain != form.initial.get("frontend_domain"):
            # Reset verification as the API does, or an old VERIFIED status would make an
            # unproven new domain a trusted staff origin at once.
            from apps.admin_api.serializers_makerspace_mutations import MakerspaceMutationMixin

            MakerspaceMutationMixin._apply_frontend_domain_change(obj, obj.frontend_domain, True)
        super().save_model(request, obj, form, change)
        if not change:
            from apps.backup.custody import initialize_custody_state

            initialize_custody_state(obj.pk)

    def has_change_permission(self, request, obj=None):
        if obj is not None and not obj.superadmin_access_enabled:
            return False
        return super().has_change_permission(request, obj)

    def get_inline_instances(self, request, obj=None):
        # A new makerspace has no roles until it is saved, so staff it from its page after.
        if obj is None or not obj.superadmin_access_enabled:
            return []
        return super().get_inline_instances(request, obj)

    def has_delete_permission(self, request, obj=None):
        # A delete is a permanent purge. Django's generic "Are you sure?" page is not
        # enough confirmation for that, so the only way in is the `purge_makerspaces`
        # action below, which makes the superadmin type each makerspace's slug.
        return False

    @admin.display(boolean=True, description="Archived")
    def archived(self, obj):
        return obj.archived_at is not None

    @admin.display(description="Superadmin access")
    def superadmin_access(self, obj):
        return "Yes" if obj.superadmin_access_enabled else "No"

    @admin.display(description="Frontend mode")
    def frontend_mode(self, obj):
        return "single-tenant" if obj.frontend_domain else "central"

    @admin.action(description="Archive selected makerspaces")
    def archive_makerspaces(self, request, queryset):
        from apps.makerspaces import lifecycle

        makerspaces = list(queryset)
        if "confirm_archive" not in request.POST:
            pending_by_makerspace = {
                archive_request.makerspace_id: archive_request
                for archive_request in MakerspaceArchiveRequest.objects.filter(
                    makerspace__in=makerspaces,
                    status=MakerspaceArchiveRequest.Status.PENDING,
                ).select_related("requested_by")
            }
            context = {
                **self.admin_site.each_context(request),
                "title": "Archive selected makerspaces",
                "makerspaces": [
                    {
                        "object": makerspace,
                        "pending_archive_request": pending_by_makerspace.get(makerspace.pk),
                        **lifecycle.archive_impact(makerspace),
                    }
                    for makerspace in makerspaces
                ],
                "opts": self.model._meta,
                "action_name": "archive_makerspaces",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/makerspaces/archive_confirmation.html",
                context,
            )

        for makerspace in makerspaces:
            try:
                lifecycle.archive(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Archived makerspace {makerspace.name} ({makerspace.slug}).",
                    level=messages.SUCCESS,
                )

    @admin.action(description="Unarchive selected makerspaces")
    def unarchive_makerspaces(self, request, queryset):
        from apps.makerspaces import lifecycle

        for makerspace in list(queryset):
            try:
                lifecycle.unarchive(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Unarchived makerspace {makerspace.name} ({makerspace.slug}).",
                    level=messages.SUCCESS,
                )

    @admin.action(description="Purge selected archived makerspaces")
    def purge_makerspaces(self, request, queryset):
        makerspaces = list(queryset)
        if "confirm_purge" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Purge selected makerspaces",
                "queryset": makerspaces,
                "opts": self.model._meta,
                "action_name": "purge_makerspaces",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/makerspaces/purge_confirmation.html",
                context,
            )

        from apps.makerspaces import lifecycle

        for makerspace in makerspaces:
            if request.POST.get(f"slug_{makerspace.pk}", "") != makerspace.slug:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): slug confirmation did not match",
                    level=messages.ERROR,
                )
                continue

            name = makerspace.name
            slug = makerspace.slug
            try:
                lifecycle.purge(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{name} ({slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Purged makerspace {name} ({slug}).",
                    level=messages.SUCCESS,
                )
        return None


from apps.makerspaces.admin_memberships import (  # noqa: E402,F401
    MakerspaceMembershipAdmin,
    MakerspaceWaiverAdmin,
    MemberProfileAdmin,
    MemberProjectAdmin,
    MembershipRequestAdmin,
)
