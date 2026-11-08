"""Exercise the upgrade against stored models, including its data-preserving reverse."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.audit import services as audit
from apps.audit.models import AuditLog


@pytest.mark.django_db(transaction=True)
def test_local_printing_roles_are_converted_without_widening_other_authority():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    old_targets = [node for node in leaves if node[0] != "machines"] + [
        ("machines", "0025_membership_machine_type_scope")
    ]
    audit.record(None, "test.before_printing_consolidation", meta={"version": 25})
    audit_before = list(AuditLog.objects.order_by("pk").values())

    try:
        executor.migrate(old_targets)
        apps = executor.loader.project_state(old_targets).apps
        Space = apps.get_model("makerspaces", "Makerspace")
        Role = apps.get_model("makerspaces", "MakerspaceRole")
        Member = apps.get_model("makerspaces", "MakerspaceMembership")
        User = apps.get_model("accounts", "User")
        Type = apps.get_model("machines", "MachineType")
        Machine = apps.get_model("machines", "Machine")
        Types = apps.get_model("machines", "RoleMachineTypeScope")
        Machines = apps.get_model("machines", "RoleMachineScope")
        Personal = apps.get_model("machines", "MembershipMachineTypeScope")
        Org = apps.get_model("organizations", "Organization")
        OrgMember = apps.get_model("organizations", "OrganizationMembership")
        OrgSpace = apps.get_model("organizations", "OrganizationMakerspace")

        # Historical models avoid today's signals/seeds. Conversion must also run
        # on dormant roles whose makerspace currently has no machine modules.
        space = Space.objects.create(name="Dormant printing", slug="dormant", enabled_modules=[])
        other = Space.objects.create(name="Other printing", slug="other-printing")
        printer, _ = Type.objects.update_or_create(
            makerspace=None, slug="3d_printer",
            defaults={"name": "3D Printer", "is_builtin": True, "managing_action": ""},
        )
        # The built-in ID is eligible even with a blank hook; its local namesake is not.
        namesake = Type.objects.create(makerspace=space, slug="3d_printer", name="Local namesake")
        local = Type.objects.create(
            makerspace=space, slug="resin", name="Resin", managing_action="manage_printing",
        )
        foreign = Type.objects.create(
            makerspace=other, slug="resin", name="Other resin", managing_action="manage_printing",
        )
        global_custom = Type.objects.create(
            slug="global-print-test", name="Global printing", is_builtin=True,
            managing_action="manage_printing",
        )
        laser = Type.objects.create(makerspace=space, slug="laser", name="Laser")
        machine = Machine.objects.create(makerspace=space, machine_type=laser, name="One laser")

        def role(slug, actions, **kwargs):
            return Role.objects.create(
                makerspace=space, name=slug, slug=slug, granted_actions=actions, **kwargs,
            )

        def member(name, makerspace=space, assigned=None, legacy="custom"):
            user = User.objects.create(username=name)
            return Member.objects.create(
                makerspace=makerspace, user=user, role=legacy, assigned_role=assigned,
            )

        printing = role("printing-only", ["manage_printing"])
        mixed = role("inventory-printing", ["edit_inventory", "manage_printing", "view_audit"])
        scoped = role(
            "renamed-protected", ["manage_machines", "manage_printing"],
            is_protected=True, is_default=True, legacy_role="machine_manager",
        )
        boss = role("renamed-space-manager", ["manage_makerspace", "manage_printing"])
        untouched = role("inventory-only", ["view_inventory"])
        corrupt = [
            role(f"corrupt-{i}", actions)
            for i, actions in enumerate(["manage_printing", {"manage_printing": True}])
        ]
        Types.objects.create(role=scoped, machine_type=laser)
        # Existing eligible links must survive without a duplicate on upgrade.
        Types.objects.create(role=scoped, machine_type=printer)
        Machines.objects.create(role=scoped, machine=machine)
        assigned = member("already-assigned", assigned=scoped)
        Personal.objects.create(membership=assigned, machine_type=namesake)

        # An edited default or a colliding custom name must never be reused.
        collision = role("printing-machines-legacy", ["manage_machines", "edit_inventory"])
        Types.objects.create(role=collision, machine_type=laser)
        legacy = [member(f"legacy-{i}", legacy="print_manager") for i in range(2)]
        other_legacy = member("other-legacy", makerspace=other, legacy="print_manager")
        organization = Org.objects.create(name="Printing org", slug="printing-org")
        OrgSpace.objects.create(organization=organization, makerspace=space, relationship="manager")
        org_member = OrgMember.objects.create(
            organization=organization, user_id=assigned.user_id,
            granted_actions=["manage_printing", "view_inventory"],
        )
        # Keep full role identity, protection flags and timestamps frozen.
        role_before = {row["id"]: row for row in Role.objects.values()}
        org_before = list(OrgMember.objects.values())
        org_links_before = list(OrgSpace.objects.values())
        personal_before = list(Personal.objects.values())
        machines_before = list(Machines.objects.values())
        assigned_before = Member.objects.values().get(pk=assigned.pk)

        executor = MigrationExecutor(connection)
        executor.migrate(leaves)
        new_apps = executor.loader.project_state(leaves).apps
        NewRole = new_apps.get_model("makerspaces", "MakerspaceRole")
        NewMember = new_apps.get_model("makerspaces", "MakerspaceMembership")
        NewTypes = new_apps.get_model("machines", "RoleMachineTypeScope")

        eligible = {printer.pk, global_custom.pk, local.pk}

        def type_ids(role_id):
            return set(NewTypes.objects.filter(role_id=role_id).values_list("machine_type_id", flat=True))

        expected_actions = {
            printing.pk: ["manage_machines"],
            mixed.pk: ["edit_inventory", "view_audit", "manage_machines"],
            scoped.pk: ["manage_machines"],
            boss.pk: ["manage_makerspace", "manage_machines"],
        }
        for pk, before in role_before.items():
            after = NewRole.objects.values().get(pk=pk)
            assert after == {**before, "granted_actions": expected_actions.get(pk, before["granted_actions"])}
        assert type_ids(printing.pk) == eligible
        assert type_ids(mixed.pk) == eligible
        assert type_ids(scoped.pk) == eligible | {laser.pk}
        assert type_ids(boss.pk) == set()  # Space Managers remain scope-exempt.
        assert type_ids(untouched.pk) == set()
        assert type_ids(collision.pk) == {laser.pk}
        for row in corrupt:
            assert type_ids(row.pk) == set()
        assert NewMember.objects.values().get(pk=assigned.pk) == assigned_before

        converted = [NewMember.objects.get(pk=row.pk) for row in legacy]
        bounded_id = converted[0].assigned_role_id
        assert bounded_id not in role_before
        assert {row.assigned_role_id for row in converted} == {bounded_id}
        assert {row.role for row in converted} == {"custom"}
        bounded = NewRole.objects.get(pk=bounded_id)
        assert bounded.granted_actions == ["manage_machines"]
        assert bounded.makerspace_id == space.pk
        assert not bounded.is_default and not bounded.is_protected
        assert bounded.slug != collision.slug
        assert type_ids(bounded.pk) == eligible
        other_converted = NewMember.objects.get(pk=other_legacy.pk)
        assert other_converted.role == "custom"
        assert other_converted.assigned_role_id not in {*role_before, bounded_id}
        other_role = NewRole.objects.get(pk=other_converted.assigned_role_id)
        assert other_role.makerspace_id == other.pk
        assert other_role.granted_actions == ["manage_machines"]
        assert type_ids(other_role.pk) == {printer.pk, global_custom.pk, foreign.pk}
        assert list(Personal.objects.values()) == personal_before
        assert list(Machines.objects.values()) == machines_before
        assert list(OrgMember.objects.values()) == org_before
        assert list(OrgSpace.objects.values()) == org_links_before
        assert OrgMember.objects.get(pk=org_member.pk).granted_actions == ["manage_printing", "view_inventory"]
        assert list(AuditLog.objects.order_by("pk").values()) == audit_before

        def snapshot():
            return (
                list(NewRole.objects.order_by("pk").values()),
                list(NewMember.objects.order_by("pk").values()),
                list(NewTypes.objects.order_by("pk").values()),
            )

        converted_state = snapshot()
        # Actually unapply RunPython: its no-op reverse must permit graph rewinds
        # while retaining converted data. Reapplying must not add roles or links.
        MigrationExecutor(connection).migrate(old_targets)
        assert snapshot() == converted_state
        MigrationExecutor(connection).migrate(leaves)
        assert snapshot() == converted_state
        assert list(AuditLog.objects.order_by("pk").values()) == audit_before
    finally:
        # Other apps can depend on machines: always restore the complete leaf graph.
        MigrationExecutor(connection).migrate(leaves)
