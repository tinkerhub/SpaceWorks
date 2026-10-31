import pytest

from apps.tenant_migration.authority_guards import (
    DECLARED_AUTHORITY_FIELDS,
    AuthorityRegistryError,
    discover_exported_authority_fields,
    validate_authority_registry,
)


def test_complete_authority_registry_is_valid():
    validate_authority_registry()


def test_mechanically_discovered_authority_inputs_are_explicit():
    assert discover_exported_authority_fields() <= set(DECLARED_AUTHORITY_FIELDS)


def test_declared_relational_and_discriminator_authority_inputs():
    required = {
        ("makerspaces.MakerspaceMembership", "role"),
        ("makerspaces.MakerspaceMembership", "assigned_role"),
        ("makerspaces.MakerspaceMembership", "status"),
        ("makerspaces.MakerspaceMembership", "can_verify"),
        ("makerspaces.MakerspaceMembership", "can_refer"),
        ("makerspaces.MakerspaceRole", "granted_actions"),
        ("makerspaces.MakerspaceRole", "slug"),
        ("makerspaces.MakerspaceRole", "is_default"),
        ("makerspaces.MakerspaceRole", "is_protected"),
        ("machines.MachineType", "managing_action"),
        ("machines.MachineOperator", "access_level"),
        ("machines.MachineOperator", "assigned_by"),
        ("machines.MachineOperator", "assigned_at"),
        ("machines.RoleMachineScope", "role"),
        ("machines.RoleMachineTypeScope", "role"),
        ("integrations.NotificationRecipient", "kind"),
        ("integrations.NotificationRecipient", "role"),
        ("integrations.NotificationRecipient", "user"),
        ("makerspaces.MembershipRequest", "assigned_role"),
        ("makerspaces.MembershipRequest", "auto_activate_on_claim"),
    }
    assert required <= set(DECLARED_AUTHORITY_FIELDS)


def test_authority_guard_fails_when_a_discovered_declaration_is_removed():
    changed = dict(DECLARED_AUTHORITY_FIELDS)
    changed.pop(("machines.MachineType", "managing_action"))
    with pytest.raises(AuthorityRegistryError, match="authorization inputs are undeclared"):
        validate_authority_registry(changed, required_fields=())


def test_authority_guard_fails_when_an_explicit_declaration_is_removed():
    changed = dict(DECLARED_AUTHORITY_FIELDS)
    changed.pop(("makerspaces.MakerspaceMembership", "can_verify"))
    with pytest.raises(AuthorityRegistryError, match="required authority declarations"):
        validate_authority_registry(changed)


# Exact conservative discoveries introduced by the pinned purge authority files.
PURGE_DISCOVERIES = (
    ("makerspaces.Makerspace", "slug"),
    ("makerspaces.Makerspace", "name"),
    ("makerspaces.MakerspaceRole", "name"),
    ("machines.Machine", "name"),
    ("machines.MachineType", "name"),
    ("machines.MachineType", "slug"),
)


@pytest.mark.parametrize("edge", PURGE_DISCOVERIES + (
    ("makerspaces.Makerspace", "created_by"),
    ("machines.Machine", "created_by"),
))
def test_each_purge_authority_discovery_remains_required_when_removed(edge):
    assert edge in discover_exported_authority_fields()
    changed = dict(DECLARED_AUTHORITY_FIELDS)
    changed.pop(edge)
    # Disable the explicit-required layer to prove the mechanical scanner still
    # sees this exact edge; neither name nor slug may be globally filtered out.
    with pytest.raises(AuthorityRegistryError, match="authorization inputs are undeclared"):
        validate_authority_registry(changed, required_fields=())


def test_purge_display_overapproximation_does_not_reset_content_or_grant_authority():
    from apps.tenant_migration.target_projection import (
        ROW_POLICIES, TARGET_FIELD_PROJECTION, RowDisposition,
    )

    for edge in PURGE_DISCOVERIES:
        assert edge not in TARGET_FIELD_PROJECTION
    # A discovered role display name cannot import a source role's grants.
    assert ROW_POLICIES["makerspaces.MakerspaceRole"].disposition is RowDisposition.KEEP_TARGET
    assert TARGET_FIELD_PROJECTION[("machines.MachineType", "managing_action")].resolved_value(
        "machines.MachineType", "managing_action",
    ) == ""


@pytest.mark.django_db(transaction=True)
def test_actual_purge_confirmation_binds_current_makerspace_slug_before_intent():
    from django.core.exceptions import ValidationError
    from apps.audit.models import AuditLog
    from apps.makerspaces.purge_intent import commit_intent
    from tests.makerspaces.purge_test_support import actor, archived_space

    user, space = actor(), archived_space()
    with pytest.raises(ValidationError, match="slug changed"):
        commit_intent(space.pk, user, expected_slug=space.slug + "-different")
    space.refresh_from_db()
    assert space.purge_started_at is None
    assert not AuditLog.objects.filter(action="makerspace.purge_started").exists()
