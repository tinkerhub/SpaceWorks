"""The chooser consumes authorized rows, never an inventory of all tenants.

Exercise the real list view's per-row full/slim serializers and the existing
RBAC/origin filters. These are read-only, non-storage API tests.
"""

import json

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.serializers_makerspace_aux import MakerspaceSwitcherSerializer
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_space
from tests.test_superadmin_access_toggle import make_superadmin

pytestmark = pytest.mark.django_db

ROLES = [
    pytest.param(MakerspaceMembership.Role.INVENTORY_MANAGER, id="full-view-inventory"),
    pytest.param(MakerspaceMembership.Role.MACHINE_MANAGER, id="slim-manage-machines"),
]
SECRET_FIELDS = {
    "telegram_bot_token", "smtp_password", "slack_webhook_url",
    "mattermost_webhook_url", "discord_webhook_url",
}


@pytest.mark.parametrize("membership_role", ROLES)
@pytest.mark.parametrize("enabled", [True, False], ids=["override-on", "override-off"])
def test_staff_list_full_and_slim_rows_report_actual_override_flag(membership_role, enabled):
    space = make_space("chooser-flag")
    space.superadmin_access_enabled = enabled
    space.save(update_fields=["superadmin_access_enabled"])
    actor = make_member("chooser-flag-member", space, membership_role=membership_role)

    response = authenticated_client(actor).get(reverse("admin-makerspaces"))

    assert response.status_code == 200
    assert len(response.data) == 1
    row = response.data[0]
    assert row["id"] == space.id
    assert row["slug"] == space.slug
    assert row["superadmin_access_enabled"] is enabled
    assert "enabled_modules" in row
    assert SECRET_FIELDS.isdisjoint(row)
    if membership_role == MakerspaceMembership.Role.INVENTORY_MANAGER:
        assert rbac.can(actor, rbac.Action.VIEW_INVENTORY, space.pk)
        assert "public_api_key" in row  # The real full serializer branch.
    else:
        assert rbac.can(actor, rbac.Action.MANAGE_MACHINES, space.pk)
        assert not rbac.can(actor, rbac.Action.VIEW_INVENTORY, space.pk)
        assert "public_api_key" not in row  # The real slim serializer branch.
        assert "smtp_username" not in row
        assert "cors_allowed_origins" not in row


@pytest.mark.parametrize("enabled", [True, False], ids=["on-cannot-write-off", "off-cannot-write-on"])
def test_switcher_serializer_validation_drops_override_flag_input(enabled):
    space = make_space("chooser-readonly")
    space.superadmin_access_enabled = enabled
    space.save(update_fields=["superadmin_access_enabled"])
    serializer = MakerspaceSwitcherSerializer(
        space, data={"superadmin_access_enabled": not enabled}, partial=True,
    )

    assert serializer.fields["superadmin_access_enabled"].read_only is True
    assert serializer.is_valid(), serializer.errors
    assert "superadmin_access_enabled" not in serializer.validated_data
    serializer.save()
    space.refresh_from_db()
    assert space.superadmin_access_enabled is enabled
    assert serializer.data["superadmin_access_enabled"] is enabled


def test_global_staff_list_omits_hidden_space_without_membership_but_keeps_visible_space():
    visible = make_space("chooser-visible")
    hidden = make_space("chooser-hidden")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    actor = make_superadmin("chooser-global")

    response = authenticated_client(actor).get(reverse("admin-makerspaces"))

    assert response.status_code == 200
    assert {row["id"] for row in response.data} == {visible.id}
    assert response.data[0]["superadmin_access_enabled"] is True
    assert not rbac.can(actor, rbac.Action.MANAGE_MACHINES, hidden.pk)


def test_hidden_global_explicit_machine_membership_is_returned_slim_with_false_flag_and_limited_authority():
    hidden = make_space("chooser-hidden-member")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    actor = make_member(
        "chooser-global-machine", hidden,
        membership_role=MakerspaceMembership.Role.MACHINE_MANAGER,
        role=User.Role.SUPERADMIN,
    )

    response = authenticated_client(actor).get(reverse("admin-makerspaces"))

    assert response.status_code == 200
    assert len(response.data) == 1
    row = response.data[0]
    assert row["id"] == hidden.id
    assert row["superadmin_access_enabled"] is False
    assert "public_api_key" not in row
    assert "smtp_username" not in row
    assert rbac.can(actor, rbac.Action.MANAGE_MACHINES, hidden.pk)
    assert not rbac.can(actor, rbac.Action.VIEW_INVENTORY, hidden.pk)
    assert not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, hidden.pk)


@pytest.mark.parametrize("membership_role", ROLES)
def test_archived_space_is_absent_even_with_explicit_staff_membership(membership_role):
    active = make_space("chooser-active")
    archived = make_space("chooser-archived")
    actor = make_member("chooser-archive-staff", active, membership_role=membership_role)
    MakerspaceMembership.objects.create(user=actor, makerspace=archived, role=membership_role)
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])

    response = authenticated_client(actor).get(reverse("admin-makerspaces"))

    assert response.status_code == 200
    assert {row["id"] for row in response.data} == {active.id}


@pytest.mark.parametrize("membership_role", ROLES)
def test_configured_central_origin_lists_both_memberships_while_dedicated_origin_hard_filters_to_own_tenant(settings, membership_role):
    central = "https://staff.example.test"
    settings.PLATFORM_STAFF_ORIGINS = [central]
    home = make_space("chooser-origin-home")
    other = make_space("chooser-origin-other")
    home.frontend_domain = "chooser-home.example.test"
    home.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    home.save(update_fields=["frontend_domain", "frontend_domain_status"])
    actor = make_member("chooser-origin-staff", home, membership_role=membership_role)
    MakerspaceMembership.objects.create(user=actor, makerspace=other, role=membership_role)
    client = authenticated_client(actor)

    central_response = client.get(reverse("admin-makerspaces"), HTTP_ORIGIN=central)
    dedicated_response = client.get(
        reverse("admin-makerspaces"), HTTP_ORIGIN=f"https://{home.frontend_domain}",
    )

    assert central_response.status_code == 200
    assert {row["id"] for row in central_response.data} == {home.id, other.id}
    assert dedicated_response.status_code == 200
    assert {row["id"] for row in dedicated_response.data} == {home.id}
    assert dedicated_response.data[0]["superadmin_access_enabled"] is True
    assert rbac.can(actor, rbac.Action.MANAGE_MACHINES if membership_role == MakerspaceMembership.Role.MACHINE_MANAGER else rbac.Action.VIEW_INVENTORY, other.pk)


@pytest.mark.parametrize("membership_role", ROLES)
def test_current_full_and_slim_lists_never_include_encrypted_credentials_or_plaintext(settings, membership_role):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    space = make_space("chooser-secrets")
    actor = make_member("chooser-secret-staff", space, membership_role=membership_role)
    setters = {
        "telegram_bot_token": space.set_telegram_bot_token,
        "smtp_password": space.set_smtp_password,
        "slack_webhook_url": space.set_slack_webhook_url,
        "mattermost_webhook_url": space.set_mattermost_webhook_url,
        "discord_webhook_url": space.set_discord_webhook_url,
    }
    secrets = [f"chooser-credential-{field}" for field in setters]
    for setter, raw in zip(setters.values(), secrets):
        setter(raw)
    space.save(update_fields=list(setters))
    ciphertexts = [getattr(space, field) for field in setters]
    assert all(ciphertext and ciphertext not in secrets for ciphertext in ciphertexts)

    response = authenticated_client(actor).get(reverse("admin-makerspaces"))

    assert response.status_code == 200
    assert {row["id"] for row in response.data} == {space.id}
    assert SECRET_FIELDS.isdisjoint(response.data[0])
    serialized = json.dumps(response.data)
    assert all(secret not in serialized for secret in secrets + ciphertexts)


def test_mixed_membership_list_uses_full_and_slim_serializers_per_row():
    full = make_space("chooser-mixed-full")
    slim = make_space("chooser-mixed-slim")
    actor = make_member(
        "chooser-mixed-staff", full,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    MakerspaceMembership.objects.create(
        user=actor, makerspace=slim, role=MakerspaceMembership.Role.MACHINE_MANAGER,
    )

    response = authenticated_client(actor).get(reverse("admin-makerspaces"))

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.data}
    assert set(rows) == {full.id, slim.id}
    assert "public_api_key" in rows[full.id]
    assert "public_api_key" not in rows[slim.id]
    assert rows[full.id]["superadmin_access_enabled"] is True
    assert rows[slim.id]["superadmin_access_enabled"] is True
    assert all(SECRET_FIELDS.isdisjoint(row) for row in rows.values())
