"""Conservative authorization-input drift guard for portable tenant imports.

The mechanical part scans attribute access, ORM lookup names, ``getattr`` field names,
and ``values_list``/``only`` field strings in the explicitly registered RBAC,
native-admin, purge and recovery modules. It intersects those names with a reviewed set of
exported authorization models. The explicit declarations also cover
authority/disclosure inputs identified by the migration threat model.

This cannot see authorization assembled dynamically, raw SQL, fields consulted only in
other modules, semantic changes to a declared field, or a new authorization module.  It
also deliberately over-approximates where the AST cannot infer an expression's model.
Code review remains necessary; this guard makes the mechanically visible subset fail
closed instead of claiming whole-program authorization analysis.
"""

import ast
from pathlib import Path

import apps as project_apps
from django.apps import apps

from apps.data_export.models import EXPORTED_MODEL_FIELDS

from .target_projection import TARGET_FIELD_PROJECTION


class AuthorityRegistryError(AssertionError):
    pass


APPS_DIR = Path(project_apps.__file__).resolve().parent
AUTHORIZATION_SOURCES = (
    APPS_DIR / "makerspaces" / "models_module_purge_receipt.py",
    APPS_DIR / "makerspaces" / "module_purge.py",
    APPS_DIR / "makerspaces" / "module_purge_receipts.py",
    APPS_DIR / "makerspaces" / "module_purge_receipt_authority.py",
    APPS_DIR / "makerspaces" / "module_purge_namespaces.py",
    APPS_DIR / "makerspaces" / "module_purge_graph.py",
    APPS_DIR / "makerspaces" / "module_purge_sites.py",
    APPS_DIR / "makerspaces" / "module_purge_accounting.py",
    APPS_DIR / "makerspaces" / "module_purge_references.py",
    APPS_DIR / "makerspaces" / "module_purge_state.py",
    APPS_DIR / "makerspaces" / "module_purge_handoff.py",
    APPS_DIR / "makerspaces" / "purge_cleanup.py",
    APPS_DIR / "makerspaces" / "module_install.py",
    APPS_DIR / "makerspaces" / "admin_capabilities.py",
    APPS_DIR / "makerspaces" / "admin_module_purge_receipts.py",
    APPS_DIR / "backup" / "rollback_cleanup.py",
    APPS_DIR / "backup" / "rollback_cleanup_outcomes.py",
    APPS_DIR / "backup" / "rollback_cleanup_progress.py",
    APPS_DIR / "makerspaces" / "purge_intent.py",
    APPS_DIR / "makerspaces" / "purge_locks.py",
    APPS_DIR / "makerspaces" / "purge_receipts.py",
    APPS_DIR / "makerspaces" / "purge_receipt_authority.py",
    APPS_DIR / "makerspaces" / "purge_receipt_recovery.py",
    APPS_DIR / "tenant_migration" / "import_boundary.py",
    APPS_DIR / "accounts" / "rbac.py",
    APPS_DIR / "accounts" / "rbac_actions.py",
    APPS_DIR / "accounts" / "rbac_memberships.py",
    APPS_DIR / "accounts" / "rbac_organizations.py",
    APPS_DIR / "accounts" / "rbac_superadmin.py",
    APPS_DIR / "accounts" / "admin_user_control.py",
    APPS_DIR / "makerspaces" / "servability.py",
    APPS_DIR / "machines" / "access.py",
    APPS_DIR / "boxes" / "admin_forms.py",
    APPS_DIR / "boxes" / "admin_lifecycle.py",
    APPS_DIR / "boxes" / "qr_admission.py",
    APPS_DIR / "boxes" / "admin_qr_lifecycle.py",
    APPS_DIR / "warranty" / "admin_forms.py",
    APPS_DIR / "procurement" / "admin_forms.py",
    APPS_DIR / "backup" / "full_capture.py",
    APPS_DIR / "backup" / "full_population.py",
    APPS_DIR / "backup" / "full_restore_identity.py",
    APPS_DIR / "backup" / "task_admission.py",
    APPS_DIR / "backup" / "inplace_marker.py",
    APPS_DIR / "backup" / "inplace_recovery_facts.py",
    APPS_DIR / "backup" / "inplace_readiness.py",
    APPS_DIR / "backup" / "restore_prospective.py",
    APPS_DIR / "backup" / "restore_object_apply.py",
    APPS_DIR / "backup" / "restore_object_proof.py",
    APPS_DIR / "backup" / "restore_journal_proof.py",
    APPS_DIR / "backup" / "restore_manifest_facts.py",
    APPS_DIR / "backup" / "backup_control_proof.py",
    APPS_DIR / "backup" / "host_restore_transport.py",
    APPS_DIR / "backup" / "host_restore_admission.py",
    APPS_DIR / "backup" / "host_restore_configuration.py",
    APPS_DIR / "backup" / "host_restore_files.py",
    APPS_DIR / "backup" / "host_restore_prepare.py",
    APPS_DIR / "backup" / "host_restore_lifecycle.py",
    APPS_DIR / "backup" / "host_restore_resume.py",
)
SCANNED_MODEL_LABELS = frozenset({
    "makerspaces.Makerspace",
    "makerspaces.MakerspaceMembership",
    "makerspaces.MakerspaceRole",
    "machines.Machine",
    "machines.MachineOperator",
    "machines.MachineType",
})


EXPLICIT_AUTHORITY_FIELDS = {
    ("makerspaces.Makerspace", "created_by"): "Conservative cross-model discovery from native QR's editable creator metadata; preserved provenance confers no makerspace authority.",
    ("machines.Machine", "created_by"): "Conservative cross-model discovery from native QR's editable creator metadata; preserved provenance confers no machine authority.",
    ("makerspaces.Makerspace", "public_inventory_enabled"): "Public disclosure switch read by module_install.apply_profile to turn inventory OFF for the minimal profile; preserved source content, not a staff or deletion grant. Target authority projection is unchanged.",
    ("makerspaces.Makerspace", "public_code"): "Raw public code plus created_at binds module cleanup to its original tenant incarnation; preserved identity is not a portable deletion grant.",
    ("makerspaces.Makerspace", "slug"): "Purge confirms the current tenant slug; preserved identity is not an imported grant.",
    ("makerspaces.Makerspace", "name"): "Audit-only purge snapshot; conservative name discovery, ordinary display content confers no authority.",
    ("makerspaces.MakerspaceRole", "name"): "Conservative cross-model name discovery; display text confers no actions and source role rows are dropped.",
    ("machines.Machine", "name"): "Conservative cross-model name discovery from the purge audit snapshot; preserved display content, not authority.",
    ("machines.MachineType", "name"): "Conservative cross-model name discovery from the purge audit snapshot; preserved display content, not authority.",
    ("machines.MachineType", "slug"): "Conservative cross-model slug discovery from makerspace purge confirmation; this occurrence confers no machine grant.",
    ("makerspaces.Makerspace", "lifecycle_state"): "Target-owned lifecycle state, omitted at export.",
    ("makerspaces.Makerspace", "purge_started_at"): "Omitted source-local irreversible purge authority; reconstruct NULL.",
    ("makerspaces.MakerspaceMembership", "makerspace"): "Tenant boundary for membership authority.",
    ("makerspaces.MakerspaceMembership", "user"): "Identity receiving the membership grant.",
    ("makerspaces.MakerspaceMembership", "role"): "Legacy fallback authority is reduced to Member/CUSTOM.",
    ("makerspaces.MakerspaceMembership", "assigned_role"): "Remapped only to the target Member role.",
    ("makerspaces.MakerspaceMembership", "status"): "Preserved only as inert pending-membership evidence until target proof.",
    ("makerspaces.MakerspaceRole", "makerspace"): "Target-seeded role ownership boundary.",
    ("makerspaces.MakerspaceRole", "slug"): "Identifies the target-seeded Member role.",
    ("makerspaces.MakerspaceRole", "granted_actions"): "Archived role rows are dropped; target grants are kept.",
    ("makerspaces.MakerspaceRole", "legacy_role"): "Archived role rows are dropped; target identity is kept.",
    ("makerspaces.MakerspaceRole", "is_default"): "Required when resolving the protected target Member role.",
    ("makerspaces.MakerspaceRole", "is_protected"): "Required when resolving the protected target Member role.",
    ("machines.Machine", "makerspace"): "Machine authorization is bounded by this tenant relation.",
    ("machines.Machine", "machine_type"): "Type-level authority follows this remapped relation.",
    ("machines.Machine", "status"): "AST over-approximation: operational state remains archive evidence.",
    ("machines.Machine", "is_active"): "AST over-approximation: lifecycle state remains archive evidence.",
    ("machines.MachineType", "makerspace"): "Distinguishes target globals from tenant custom types.",
    ("machines.MachineType", "is_builtin"): "Discriminator for global resolution versus projected custom insertion.",
    ("machines.MachineOperator", "machine"): "Owner decision 22 preserves this live authority relation.",
    ("machines.MachineOperator", "user"): "Owner decision 22 preserves the identity receiving authority.",
    ("machines.MachineOperator", "access_level"): "Owner decision 22 preserves the operate/manage/full grant.",
    ("machines.MachineOperator", "assigned_by"): "Owner decision 22 preserves assignment provenance with FK closure.",
    ("machines.MachineOperator", "assigned_at"): "Owner decision 22 preserves assignment-time provenance.",
    ("machines.MembershipMachineTypeScope", "membership"): "Dropped personal authority scope.",
    ("machines.MembershipMachineTypeScope", "machine_type"): "Dropped personal authority scope.",
    ("machines.RoleMachineScope", "role"): "Dropped role authority scope.",
    ("machines.RoleMachineScope", "machine"): "Dropped role authority scope.",
    ("machines.RoleMachineTypeScope", "role"): "Dropped role authority scope.",
    ("machines.RoleMachineTypeScope", "machine_type"): "Dropped role authority scope.",
    ("makerspaces.MembershipRequest", "assigned_role"): "Remapped to target Member, never a source role.",
    ("integrations.NotificationRecipient", "makerspace"): "Dropped disclosure-rule tenant boundary.",
    ("integrations.NotificationRecipient", "feature"): "Dropped disclosure-rule discriminator.",
    ("integrations.NotificationRecipient", "event"): "Dropped disclosure-rule discriminator.",
    ("integrations.NotificationRecipient", "kind"): "Every recipient kind is dropped.",
    ("integrations.NotificationRecipient", "role"): "Dropped role-directed disclosure rule.",
    ("integrations.NotificationRecipient", "user"): "Dropped named-user disclosure rule.",
    ("integrations.NotificationDestination", "channel"): "Selects credential and delivery semantics.",
    ("integrations.NotificationDestination", "telegram_chat_id"): "Target-bot disclosure destination.",
}

DECLARED_AUTHORITY_FIELDS = {
    **{edge: policy.reason for edge, policy in TARGET_FIELD_PROJECTION.items()},
    **EXPLICIT_AUTHORITY_FIELDS,
}


def _normalise_field_name(name, model_fields):
    root = name.split("__", 1)[0]
    if root.endswith("_id") and root[:-3] in model_fields:
        return root[:-3]
    return root


def discover_authorization_field_names(paths=AUTHORIZATION_SOURCES):
    names = set()
    for path in paths:
        tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                names.update(node.arg.split("__"))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "getattr" and len(node.args) > 1:
                    value = node.args[1]
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        names.add(value.value)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"values_list", "only", "defer"}:
                    for value in node.args:
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            names.update(value.value.split("__"))
    return frozenset(names)


def discover_exported_authority_fields(paths=AUTHORIZATION_SOURCES):
    names = discover_authorization_field_names(paths)
    discovered = set()
    for label in SCANNED_MODEL_LABELS:
        exported = set(EXPORTED_MODEL_FIELDS[label].split())
        for name in names:
            normalized = _normalise_field_name(name, exported)
            if normalized in exported and normalized not in {"id", "created_at", "updated_at"}:
                discovered.add((label, normalized))
    return frozenset(discovered)


def validate_authority_registry(
    declarations=DECLARED_AUTHORITY_FIELDS,
    *,
    paths=AUTHORIZATION_SOURCES,
    required_fields=None,
):
    required = (
        set(TARGET_FIELD_PROJECTION) | set(EXPLICIT_AUTHORITY_FIELDS)
        if required_fields is None
        else set(required_fields)
    )
    missing_required = required - set(declarations)
    if missing_required:
        raise AuthorityRegistryError(
            f"required authority declarations are missing: {sorted(missing_required)}"
        )
    discovered = discover_exported_authority_fields(paths)
    missing = discovered - set(declarations)
    if missing:
        raise AuthorityRegistryError(
            f"exported authorization inputs are undeclared: {sorted(missing)}"
        )
    for label, field_name in declarations:
        model = apps.get_model(label)
        try:
            model._meta.get_field(field_name)
        except Exception as exc:
            raise AuthorityRegistryError(
                f"declared authority field no longer exists: {label}.{field_name}"
            ) from exc
