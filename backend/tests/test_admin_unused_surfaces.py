from types import SimpleNamespace

import pytest
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import User
from apps.machines.models import PrintingCutoverRepair, PrintingCutoverState
from config.unfold import UNFOLD


def test_unused_models_are_unregistered_and_security_models_remain_registered():
    unused = {Group, AccessLog, AccessFailureLog, PrintingCutoverState, PrintingCutoverRepair}
    retained = {AccessAttempt, OutstandingToken, BlacklistedToken, User}

    assert unused.isdisjoint(admin.site._registry)
    assert retained <= set(admin.site._registry)


def test_sidebar_has_no_groups_link():
    links = [
        str(item["link"])
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
    ]

    assert "admin:auth_group_changelist" not in links
    assert f"{reverse('admin:index')}auth/group/" not in links


@pytest.mark.django_db
def test_existing_user_change_form_keeps_account_fields_without_django_permissions(client):
    superuser = User.objects.create_superuser(
        username="cleanup-superadmin",
        email="cleanup-superadmin@example.test",
        password="test-password",
        role=User.Role.SUPERADMIN,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    user = User.objects.create_user(username="cleanup-member", email="member@example.test")
    client.force_login(superuser)

    response = client.get(reverse("admin:accounts_user_change", args=[user.pk]))

    assert response.status_code == 200
    html = response.content.decode()
    for field in ("groups", "user_permissions"):
        assert f'name="{field}"' not in html
    for field in ("is_active", "is_staff", "is_superuser", "first_name", "last_name"):
        assert f'name="{field}"' in html
    assert "Personal info" in html
    assert "Important dates" in html
    assert "Space Works Access" in html


def test_user_admin_has_no_group_filter_or_horizontal_permission_widgets():
    user_admin = admin.site._registry[User]

    assert "groups" not in user_admin.list_filter
    assert user_admin.filter_horizontal == ()


def test_subdomain_requests_sidebar_permission_requires_managed_deployment(monkeypatch):
    item = next(
        item
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
        if str(item["link"]) == reverse("admin:makerspaces_subdomainrequest_changelist")
    )
    request = SimpleNamespace(user=SimpleNamespace(
        is_authenticated=True,
        is_active=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    ))

    monkeypatch.delenv("PLATFORM_DOMAIN_SUFFIX", raising=False)
    assert item["permission"](request) is False

    monkeypatch.setenv("PLATFORM_DOMAIN_SUFFIX", "example.test")
    assert item["permission"](request) is True
