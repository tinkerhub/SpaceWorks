"""Staff memberships edited from /control/: pick a real role, keep the mirror, audit it.

Both the User page and the Makerspace page carry a membership inline, so a superadmin can
make staff without leaving Django. They used to expose only the legacy `role` string, which
cannot name a custom role and defaulted every new row to Space Manager -- one stray "Add
another" was a silent full-admin grant -- and they wrote no audit entry. The same form and
audit hook now serve both inlines.
"""

from django import forms
from django.db.models import Q
from rest_framework.exceptions import ValidationError as DRFValidationError
from unfold.admin import TabularInline

from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.makerspaces.servability import is_servable
from config.admin_source_gate import source_gate_refusal


class RoleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.makerspace.name} · {obj.name}"


class StaffMembershipForm(forms.ModelForm):
    assigned_role = RoleChoiceField(
        queryset=MakerspaceRole.objects.select_related("makerspace").order_by(
            "makerspace__name", "name"
        ),
        label="Role",
        help_text="Pick a role from the same makerspace.",
    )

    # Set per inline (see MakerspaceMembershipInline.get_formset) to offer only one
    # makerspace's roles; the model's clean() still refuses a role from another space.
    role_makerspace = None
    # Pre-rendered role options shared by every row of one page, so a long staff list
    # does not run one roles query per row. The queryset above still validates.
    role_choices = None

    class Meta:
        model = MakerspaceMembership
        fields = ("user", "makerspace", "assigned_role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.fields is a per-form copy; narrowing base_fields would leak across requests.
        # Only roles that grant something are staff roles, as in Add staff: a community
        # membership has its own path (module, members quota). A row keeps its current
        # role on offer, or every listed community member would fail the page's save.
        roles = self.fields["assigned_role"].queryset.filter(makerspace__superadmin_access_enabled=True).filter(
            ~Q(granted_actions=[]) | Q(pk=self.instance.assigned_role_id)
        )
        if self.role_makerspace is not None:
            roles = roles.filter(makerspace=self.role_makerspace)
        self.fields["assigned_role"].queryset = roles
        if self.role_choices is not None:
            self.fields["assigned_role"].choices = self.role_choices
        if self.instance.pk is not None and self.instance.assigned_role_id is None:
            # Legacy rows predate roles (RBAC falls back to their `role`); an untouched one
            # must not block saving the page, and picking a role here is a grant.
            self.fields["assigned_role"].required = False
        if self.instance.pk is not None:
            # Retargeting a row would revoke the old user's or space's staff without
            # revoke_membership's side effects; grant a new row and revoke this one instead.
            for name in ("user", "makerspace"):
                if name in self.fields:
                    self.fields[name].disabled = True

    def clean(self):
        cleaned = super().clean()
        makerspace = cleaned.get("makerspace") or getattr(self.instance, "makerspace", None)
        if makerspace is not None and not makerspace.superadmin_access_enabled:
            # A hard-hidden makerspace has withdrawn superadmin authority; recovery there
            # goes through the audited break-glass path, not a raw row edit.
            raise forms.ValidationError(
                "This makerspace is hidden from superadmins. Use the break-glass Space Manager flow."
            )
        if makerspace is not None and self.has_changed():
            # The User page is not makerspace-scoped, so the changeform source-gate hook
            # cannot see which tenant an inline row writes to; refuse it here, per row.
            refusal = source_gate_refusal([makerspace.pk])
            if refusal:
                raise forms.ValidationError(refusal)
        role = cleaned.get("assigned_role")
        # Only a newly picked role is a grant; editing another field of a revoked row
        # must not quietly reactivate it.
        if role is not None and (self.instance.pk is None or "assigned_role" in self.changed_data):
            if self.instance.pk is None or self.instance.status != "active":
                self._check_new_staff(makerspace)
            # RBAC reads `assigned_role`; `role` is the legacy mirror older readers still
            # use, and the staff API keeps the two in step the same way.
            self.instance.role = role.legacy_role or MakerspaceMembership.Role.CUSTOM
            # Saving a role is (re-)granting it, as Add staff does: a revoked row would
            # otherwise keep looking staffed here while RBAC refuses it.
            self.instance.status = "active"
            self.instance.revoked_at = None
            self.instance.revoked_by = None
            self.instance.revocation_reason = ""
        return cleaned

    def _check_new_staff(self, makerspace):
        # The same gates Add staff applies (attach_staff_membership): no staff for an
        # archived space, and the staff quota. The admin view is atomic, so the quota's
        # makerspace row lock holds until the membership is saved.
        if makerspace is None:
            return
        if not is_servable(makerspace):
            raise forms.ValidationError("Makerspace is archived.")
        try:
            limits.check_quota(makerspace, "staff", adding=1)
        except DRFValidationError as exc:
            raise forms.ValidationError(exc.detail.get("limit", exc.detail)) from exc


class StaffMembershipInline(TabularInline):
    model = MakerspaceMembership
    form = StaffMembershipForm
    extra = 0
    # Removing staff is a revocation with side effects (open requests, presence, member
    # payments), so it goes through the "Revoke selected memberships" action instead.
    can_delete = False

    def get_queryset(self, request):
        # Hidden makerspaces' rows are not the superadmin's to see or edit, and listing
        # them would also fail every save of the page on the hidden-space check.
        return super().get_queryset(request).filter(makerspace__superadmin_access_enabled=True)


def audit_staff_membership(actor, membership, *, created):
    audit.record(
        actor,
        "staff.created" if created else "staff.membership_updated",
        makerspace=membership.makerspace,
        target=membership.user,
        meta={
            "role_id": membership.assigned_role_id,
            "role_slug": getattr(membership.assigned_role, "slug", None),
            "via": "control",
        },
    )


def audit_staff_memberships(request, formset):
    """Record what a membership inline just saved, as the staff API would."""
    if formset.model is not MakerspaceMembership:
        return
    for membership in formset.new_objects:
        audit_staff_membership(request.user, membership, created=True)
    for membership, _fields in formset.changed_objects:
        audit_staff_membership(request.user, membership, created=False)


class MakerspaceMembershipInline(StaffMembershipInline):
    """Staff a makerspace from its own page: pick the user and one of its roles."""

    fk_name = "makerspace"
    fields = ("user", "assigned_role", "status")
    readonly_fields = ("status",)
    autocomplete_fields = ("user",)

    def get_queryset(self, request):
        # Staff only: active rows whose role grants more than the protected Member role
        # (which grants nothing). A space's community members are not listed here.
        return (
            super().get_queryset(request)
            .filter(status="active")
            .filter(Q(assigned_role__isnull=True) | ~Q(assigned_role__granted_actions=[]))
            .select_related("assigned_role", "user")
        )

    def has_view_permission(self, request, obj=None):
        if obj is not None and not obj.superadmin_access_enabled:
            return False
        return super().has_view_permission(request, obj)

    def get_formset(self, request, obj=None, **kwargs):
        if obj is not None:
            # Only this makerspace's roles make sense here; the form still re-checks.
            kwargs["form"] = type(
                self.form.__name__,
                (self.form,),
                {"role_makerspace": obj, "role_choices": _role_choices(request, obj)},
            )
        return super().get_formset(request, obj, **kwargs)


def _role_choices(request, makerspace):
    """One roles query per page render, however many rows the inline shows."""
    cache = getattr(request, "_staff_role_choices", None)
    if cache is None:
        cache = request._staff_role_choices = {}
    if makerspace.pk not in cache:
        field = StaffMembershipForm.base_fields["assigned_role"]
        roles = field.queryset.filter(
            makerspace=makerspace, makerspace__superadmin_access_enabled=True
        ).exclude(granted_actions=[])
        cache[makerspace.pk] = [
            ("", field.empty_label),
            *((role.pk, field.label_from_instance(role)) for role in roles),
        ]
    return cache[makerspace.pk]
