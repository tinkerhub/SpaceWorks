"""/control/ User page: audit privilege, identity and password changes; refuse a lockout.

A superadmin editing `is_superuser`/`is_active` here used to leave no audit entry, and
nothing stopped them demoting themselves or the last superadmin -- after which only a
shell could reopen /control/.
"""

from django import forms
from django.contrib import messages
from django.contrib.admin.utils import unquote
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.hashers import is_password_usable
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext
from rest_framework.exceptions import APIException
from unfold.forms import UserChangeForm

from apps.accounts.claim_transition_gate import (
    ClaimTransitionScopeChanged,
    claim_transition_gate,
)
from apps.accounts.models import User
from apps.accounts.principal_guards import refuse_anonymous_requester_credential
from apps.accounts.transition_services import (
    WalkInTransitionError,
    transition_walk_in_to_account,
)
from apps.audit import services as audit
from apps.backup.not_restored import TenantNotRestored
from apps.tenant_migration.gate_errors import (
    SourceMigrationGateClosed,
    SourceMigrationGateUnavailable,
)

AUDITED_FLAGS = ("is_superuser", "is_staff", "is_active", "role")


class ControlUserChangeForm(UserChangeForm):
    acting_user = None  # set per request by UserControlAdminMixin.get_form

    def clean(self):
        cleaned = super().clean()
        user = self.instance
        losing = cleaned.get("is_superuser") is False or cleaned.get("is_active") is False
        if user.pk is None or not losing:
            return cleaned
        stored = User.objects.filter(pk=user.pk).values("is_superuser", "is_active").first()
        if not (stored and stored["is_superuser"] and stored["is_active"]):
            return cleaned
        if self.acting_user is not None and self.acting_user.pk == user.pk:
            raise forms.ValidationError(
                "You cannot remove your own superuser status or deactivate your own account."
            )
        # Lock EVERY active superuser, the target included: two superadmins demoting each
        # other then lock the same rows, so the second waits and re-reads instead of each
        # locking a disjoint set and both seeing "one other left".
        active = list(
            User.objects.select_for_update()
            .filter(
                is_superuser=True, is_active=True, access_status=User.AccessStatus.ACTIVE
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        if not [pk for pk in active if pk != user.pk]:
            raise forms.ValidationError(
                "This is the last active superuser. Make someone else a superuser first, "
                "or nobody could sign in to /control/ again."
            )
        return cleaned


class UserControlAdminMixin:
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        return type(form.__name__, (form,), {"acting_user": request.user})

    def save_model(self, request, obj, form, change):
        before = (
            User.objects.filter(pk=obj.pk).values(*AUDITED_FLAGS, "email").first()
            if change else None
        )
        super().save_model(request, obj, form, change)
        if before is None:
            audit.record(
                request.user,
                "user.created",
                target=obj,
                meta={
                    "via": "control",
                    "is_superuser": obj.is_superuser,
                    "is_staff": obj.is_staff,
                    "is_active": obj.is_active,
                    "role": obj.role,
                },
            )
            return
        changes = {
            field: {"old": before[field], "new": getattr(obj, field)}
            for field in AUDITED_FLAGS
            if before[field] != getattr(obj, field)
        }
        if before["email"] != obj.email:
            # `*_email` keys are HMAC-fingerprinted by audit.record; no address is stored.
            changes["email"] = {"old_email": before["email"], "new_email": obj.email}
        changed_fields = sorted(form.changed_data)
        if changes or changed_fields:
            audit.record(
                request.user,
                "user.updated",
                target=obj,
                meta={"via": "control", "changed_fields": changed_fields, "changes": changes},
            )

    def user_change_password(self, request, id, form_url=""):
        user = self.get_object(request, unquote(id)) if request.method == "POST" else None
        response = self._user_change_password(request, id, form_url)
        if user is not None:
            stored = User.objects.filter(pk=user.pk).values_list("password", flat=True).first()
            if stored is not None and stored != user.password:
                audit.record(
                    request.user,
                    "user.password_changed",
                    target=user,
                    meta={"via": "control", "usable": is_password_usable(stored)},
                )
        return response

    def _user_change_password(self, request, id, form_url=""):
        """Make the inherited password form an explicit account transition."""
        user = self.get_object(request, unquote(id))
        if request.method == "POST" and user is not None:
            try:
                refuse_anonymous_requester_credential(user)
            except APIException as exc:
                self.message_user(request, api_exception_message(exc), level=messages.ERROR)
                return HttpResponseRedirect(_change_url(self, user))
        if (
            request.method != "POST"
            or user is None
            or not user.is_walk_in
            or not self.has_change_permission(request, user)
        ):
            return super().user_change_password(request, id, form_url)

        form = self.change_password_form(user, request.POST)
        if not form.is_valid() or not form.cleaned_data["set_usable_password"]:
            return super().user_change_password(request, id, form_url)

        password = form.cleaned_data["password1"]

        def write_password(locked_user):
            locked_user.set_password(password)
            locked_user.save(update_fields=["password"])

        try:
            with claim_transition_gate(user.pk):
                # Source admission can wait; request.user may now have lost authority.
                actor = User.objects.filter(pk=request.user.pk).first()
                if (
                    actor is None
                    or not actor.is_active
                    or not actor.is_superuser
                    or not actor.is_staff
                    or actor.access_status != User.AccessStatus.ACTIVE
                    or actor.must_change_password
                    or actor.is_tenant_dump_stub
                ):
                    raise PermissionDenied("You no longer have permission to change this password.")
                user = transition_walk_in_to_account(
                    user,
                    actor=actor,
                    credential_writer=write_password,
                )
        except (
            SourceMigrationGateClosed,
            SourceMigrationGateUnavailable,
            TenantNotRestored,
            ClaimTransitionScopeChanged,
        ):
            self.message_user(
                request,
                "The account could not be updated right now. Please retry shortly.",
                level=messages.ERROR,
            )
            return HttpResponseRedirect(_change_url(self, user))
        except WalkInTransitionError:
            # A concurrent transition won the row lock. The record is now an ordinary
            # account, so the inherited form is again the correct writer.
            return super().user_change_password(request, id, form_url)

        form.user = user
        self.log_change(request, user, self.construct_change_message(request, form, None))
        messages.success(request, gettext("Password changed successfully."))
        update_session_auth_hash(request, user)
        return HttpResponseRedirect(_change_url(self, user))


def _change_url(model_admin, user):
    return reverse(
        f"{model_admin.admin_site.name}:{user._meta.app_label}_{user._meta.model_name}_change",
        args=(user.pk,),
    )


def api_exception_message(exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return "; ".join(f"{key}: {value}" for key, value in detail.items())
    return str(detail or exc)
