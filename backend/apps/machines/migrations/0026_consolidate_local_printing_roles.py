"""Replace local printing bypass grants with bounded machine authority.

Only historical models are used. Existing audit rows remain append-only and unchanged;
this versioned data migration records the upgrade, without fabricating a staff actor or
importing runtime audit/authorization services. Organization grants are untouched.

Schema rollback retains this data conversion: after unioning scope we cannot tell
which links predated this upgrade, nor reconstruct edited grants safely. A no-op
reverse permits older schema migrations and historical migration tests to run without
guessing or deleting permissions. Exact data rollback requires a pre-upgrade backup.
"""

from django.db import migrations
from django.db.models import Q


PRINTING = "manage_printing"
MACHINES = "manage_machines"
MAKERSPACE = "manage_makerspace"


def _eligible_types(MachineType):
    """Freeze IDs, never a bare slug: a local '3d_printer' is a different type."""
    global_ids, local_ids = [], {}
    eligible = MachineType.filter(
        Q(managing_action=PRINTING)
        | Q(makerspace__isnull=True, is_builtin=True, slug="3d_printer")
    )
    for type_id, makerspace_id in eligible.values_list("pk", "makerspace_id"):
        if makerspace_id is None:
            global_ids.append(type_id)
        else:
            local_ids.setdefault(makerspace_id, []).append(type_id)
    return global_ids, local_ids


def _add_type_links(TypeScope, role, type_ids):
    TypeScope.bulk_create(
        [TypeScope.model(role_id=role.pk, machine_type_id=pk) for pk in type_ids],
        batch_size=500,
        ignore_conflicts=True,
    )


def _legacy_role(Role, makerspace_id):
    """Create one precisely bounded role; never reuse an administrator-edited role.

    The caller caches only rows created by this invocation, so neither a matching name
    nor an edited default Machine Manager can confer broader scope on legacy staff.
    """
    roles = Role.filter(makerspace_id=makerspace_id)
    root_name, root_slug = "Printing machines (legacy)", "printing-machines-legacy"
    name, slug, suffix = root_name, root_slug, 2
    while roles.filter(Q(name__iexact=name) | Q(slug__iexact=slug)).exists():
        name, slug = f"{root_name} {suffix}", f"{root_slug}-{suffix}"
        suffix += 1
    return Role.create(
        makerspace_id=makerspace_id,
        name=name,
        slug=slug,
        granted_actions=[MACHINES],
        is_default=False,
        is_protected=False,
    )


def forwards(apps, schema_editor):
    db = schema_editor.connection.alias
    Role = apps.get_model("makerspaces", "MakerspaceRole").objects.using(db)
    Membership = apps.get_model("makerspaces", "MakerspaceMembership").objects.using(db)
    MachineType = apps.get_model("machines", "MachineType").objects.using(db)
    TypeScope = apps.get_model("machines", "RoleMachineTypeScope").objects.using(db)
    global_ids, local_ids = _eligible_types(MachineType)

    for role in Role.select_for_update().order_by("pk").iterator():
        actions = role.granted_actions
        # Non-lists already confer no authority. Leave them inert; do not interpret a
        # corrupt object/string as a valid grant. Preserve other list entries as stored.
        if not isinstance(actions, list) or PRINTING not in actions:
            continue
        converted = [action for action in actions if action != PRINTING]
        if MACHINES not in converted:
            converted.append(MACHINES)
        Role.filter(pk=role.pk).update(granted_actions=converted)
        if MAKERSPACE not in converted:
            _add_type_links(
                TypeScope, role, global_ids + local_ids.get(role.makerspace_id, [])
            )

    created_roles = {}
    legacy_memberships = Membership.select_for_update().filter(
        assigned_role__isnull=True, role="print_manager"
    ).order_by("makerspace_id", "pk")
    for membership in legacy_memberships.iterator():
        role = created_roles.get(membership.makerspace_id)
        if role is None:
            role = _legacy_role(Role, membership.makerspace_id)
            _add_type_links(
                TypeScope, role, global_ids + local_ids.get(membership.makerspace_id, [])
            )
            created_roles[membership.makerspace_id] = role
        Membership.filter(pk=membership.pk).update(assigned_role_id=role.pk, role="custom")


class Migration(migrations.Migration):
    dependencies = [
        ("machines", "0025_membership_machine_type_scope"),
        ("makerspaces", "0076_module_purge_receipt"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
