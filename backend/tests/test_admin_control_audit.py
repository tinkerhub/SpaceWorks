"""/control/ edits leave an audit trail, never a secret, and cannot lock superadmins out."""

import pytest
from django.contrib import admin
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.accounts.models import User
from apps.apiclients.models import ApiClient
from apps.audit.models import AuditLog
from apps.inventory.models import Category
from apps.payments.models import MakerspacePaymentSettings
from tests.admin_form_helpers import form_data, page_data
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


def _superadmin(username):
    return make_user(
        username, role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        is_staff=True, is_superuser=True,
    )


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _post_user_page(client, user, **changes):
    url = reverse("admin:accounts_user_change", args=[user.pk])
    data = page_data(client.get(url))
    for key, value in changes.items():
        if value is False:
            data.pop(key, None)
        else:
            data[key] = "on" if value is True else value
    return client.post(url, data)


def test_user_privilege_and_email_changes_are_audited_with_the_email_fingerprinted():
    actor = _superadmin("ctl-audit-actor")
    target = make_user("ctl-audit-target")

    response = _post_user_page(
        _client(actor), target, is_staff=True, email="after@example.test"
    )

    assert response.status_code == 302, response.context["adminform"].form.errors
    entry = AuditLog.objects.get(action="user.updated", target_id=str(target.pk))
    assert entry.actor_id == actor.pk
    assert entry.meta["changes"]["is_staff"] == {"old": False, "new": True}
    assert set(entry.meta["changed_fields"]) >= {"email", "is_staff"}
    email = entry.meta["changes"]["email"]
    assert email["old_email"].startswith("hmac-sha256:")
    assert email["new_email"].startswith("hmac-sha256:")
    assert "example.test" not in str(entry.meta) and "@e.com" not in str(entry.meta)


def test_a_superuser_cannot_demote_or_deactivate_themselves():
    actor = _superadmin("ctl-audit-self")
    client = _client(actor)

    for field in ("is_superuser", "is_active"):
        response = _post_user_page(client, actor, **{field: False})
        assert response.status_code == 200
        assert "your own" in str(response.context["adminform"].form.non_field_errors())

    actor.refresh_from_db()
    assert actor.is_superuser and actor.is_active
    assert not AuditLog.objects.filter(action="user.updated").exists()


def test_demoting_another_superuser_is_allowed_while_one_remains():
    actor = _superadmin("ctl-audit-demoter")
    other = _superadmin("ctl-audit-demoted")

    response = _post_user_page(_client(actor), other, is_superuser=False)

    assert response.status_code == 302
    other.refresh_from_db()
    assert not other.is_superuser
    entry = AuditLog.objects.get(action="user.updated", target_id=str(other.pk))
    assert entry.meta["changes"]["is_superuser"] == {"old": True, "new": False}


def test_the_last_active_superuser_cannot_be_demoted():
    only = _superadmin("ctl-audit-only")
    request = RequestFactory().post("/")
    request.user = only
    form_class = admin.site._registry[User].get_form(request, only, change=True)
    # Acted on by someone else: the self-demotion rule must not be what refuses it.
    form_class = type(form_class.__name__, (form_class,), {"acting_user": None})
    data = form_data(form_class(instance=only))
    data.pop("is_superuser")

    form = form_class(data, instance=only)

    assert not form.is_valid()
    assert "last active superuser" in str(form.non_field_errors())


def test_admin_password_change_is_audited_without_the_password():
    actor = _superadmin("ctl-audit-pw-actor")
    target = make_user("ctl-audit-pw-target")
    password = "Zx9!a-long-unique-passphrase"

    response = _client(actor).post(
        reverse("admin:auth_user_password_change", args=[target.pk]),
        {"usable_password": "true", "password1": password, "password2": password},
    )

    assert response.status_code == 302
    entry = AuditLog.objects.get(action="user.password_changed", target_id=str(target.pk))
    assert entry.actor_id == actor.pk
    assert entry.meta["via"] == "control" and entry.meta["usable"] is True
    assert password not in str(entry.meta)


def test_payment_settings_audit_names_key_changes_and_currency_but_no_values():
    space = make_space("ctl-audit-pay")
    settings = MakerspacePaymentSettings.objects.create(makerspace=space, default_currency="usd")
    client = _client(_superadmin("ctl-audit-pay-actor"))
    url = reverse("admin:payments_makerspacepaymentsettings_change", args=[settings.pk])
    page = client.get(url)
    assert "makerspace" not in page.context["adminform"].form.fields

    response = client.post(
        url, {"default_currency": "eur", "stripe_secret_key": "sk_test_never_logged"}
    )

    assert response.status_code == 302, response.context["adminform"].form.errors
    entry = AuditLog.objects.get(action="control.object_updated", target_id=str(settings.pk))
    assert entry.makerspace_id == space.pk
    assert sorted(entry.meta["changed_fields"]) == ["default_currency", "stripe_secret_key"]
    assert entry.meta["detail"]["default_currency"] == {"old": "usd", "new": "eur"}
    assert "sk_test_never_logged" not in str(entry.meta)
    settings.refresh_from_db()
    assert settings.makerspace_id == space.pk
    delete_url = reverse("admin:payments_makerspacepaymentsettings_delete", args=[settings.pk])
    assert client.get(delete_url).status_code == 403


def test_api_client_credential_writes_record_field_names_only():
    space = make_space("ctl-audit-client")
    client_row, _secret = ApiClient.issue(
        label="Kiosk", makerspace=space, allowed_origins=["https://kiosk.example.test"],
        scopes=["legacy:v1"],
    )
    client = _client(_superadmin("ctl-audit-client-actor"))
    url = reverse("admin:apiclients_apiclient_change", args=[client_row.pk])
    data = page_data(client.get(url))
    data["smtp_password"] = "smtp-never-logged"
    data.pop("is_active")

    response = client.post(url, data)

    assert response.status_code == 302, response.context["adminform"].form.errors
    entry = AuditLog.objects.get(action="control.object_updated", target_id=str(client_row.pk))
    assert {"smtp_password", "is_active"} <= set(entry.meta["changed_fields"])
    assert "smtp-never-logged" not in str(entry.meta)


def test_category_create_change_and_delete_are_audited_and_tenancy_is_fixed():
    space, other = make_space("ctl-audit-cat"), make_space("ctl-audit-cat-other")
    client = _client(_superadmin("ctl-audit-cat-actor"))

    client.post(
        reverse("admin:inventory_category_add"),
        {"name": "Gizmos", "slug": "ctl-gizmos", "makerspace": space.pk, "display_order": 0},
    )
    category = Category.objects.get(makerspace=space, slug="ctl-gizmos")
    created = AuditLog.objects.get(action="control.object_created", target_id=str(category.pk))
    assert created.makerspace_id == space.pk
    assert created.meta["model"] == "inventory.category"

    change_url = reverse("admin:inventory_category_change", args=[category.pk])
    data = page_data(client.get(change_url))
    data.update({"name": "Gizmo kits", "makerspace": other.pk})
    assert client.post(change_url, data).status_code == 302
    category.refresh_from_db()
    assert (category.name, category.makerspace_id) == ("Gizmo kits", space.pk)
    updated = AuditLog.objects.get(action="control.object_updated", target_id=str(category.pk))
    assert updated.meta["changed_fields"] == ["name"]

    delete_url = reverse("admin:inventory_category_delete", args=[category.pk])
    assert client.post(delete_url, {"post": "yes"}).status_code == 302
    assert AuditLog.objects.filter(
        action="control.object_deleted", target_id=str(created.target_id)
    ).exists()
