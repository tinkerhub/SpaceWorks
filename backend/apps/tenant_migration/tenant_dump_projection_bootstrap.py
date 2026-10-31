"""Pre-load migration baseline and explicit target seed outputs; never a post-load census."""

from dataclasses import dataclass
from django.apps import apps
from django.db import connections
from django.utils import timezone
from apps.backup.raw_projection import no_decrypt_guard
from apps.makerspaces.roles import DEFAULT_ROLE_DEFINITIONS, MEMBER_ROLE_DEFINITION

from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_model_catalog import AUTO_CREATED_TABLE_RULES, THIRD_PARTY_MODEL_RULES
from .tenant_dump_types import ModelDisposition
from .tenant_dump_raw import projected_raw_digest
from .tenant_dump_projection_expectations import projected_labels

GENERATED_LABELS = ("makerspaces.MakerspaceRole", "machines.RoleMachineTypeScope",
                    "encryption.PiiMakerspaceWriteFence")


@dataclass(frozen=True)
class BootstrapBaseline:
    rows: dict
    migration_rows: tuple
    baseline_sha256: str


def read_model_rows(using, labels):
    result = {}
    with no_decrypt_guard():
        for label in sorted(labels):
            model = apps.get_model(label)
            result[label] = tuple(model._base_manager.using(using).order_by("pk").values(
                *(field.attname for field in model._meta.concrete_fields)
            ))
    return result


def _migration_rows(using):
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT id, app, name, applied FROM django_migrations ORDER BY id")
        return tuple(cursor.fetchall())


def capture_bootstrap_baseline(using):
    """Freeze only the trusted, freshly migrated DB before inserting any source row."""
    labels = {label for label, rule in {**AUTO_CREATED_TABLE_RULES, **THIRD_PARTY_MODEL_RULES}.items()
              if rule.disposition is ModelDisposition.BOOTSTRAP}
    rows = read_model_rows(using, labels | {"machines.MachineType", "encryption.PiiGlobalWriteFence"})
    all_projected = read_model_rows(using, set(projected_labels()) | set(GENERATED_LABELS))
    if any(records for label, records in all_projected.items() if label != "machines.MachineType"):
        raise TenantDumpVerificationError("The pre-load database contains non-bootstrap tenant rows.")
    if any(row["makerspace_id"] is not None or not row["is_builtin"]
           for row in rows["machines.MachineType"]):
        raise TenantDumpVerificationError("The target MachineType baseline is not global builtin state.")
    fence = rows["encryption.PiiGlobalWriteFence"]
    if fence != ({"id": 1, "state": "open", "operation_id": None, "operation_kind": None,
                  "actor_id": None, "closed_at": None, "opened_at": None},):
        raise TenantDumpVerificationError("The target global fence is not the pristine migration seed.")
    return BootstrapBaseline(rows, _migration_rows(using), projected_raw_digest(rows))


def _insert_generated(using, label, values):
    """SQL RETURNING allocates only the PK; all expected content is chosen before insert."""
    model = apps.get_model(label)
    connection = connections[using]
    quote = connection.ops.quote_name
    fields = [field for field in model._meta.concrete_fields if not field.primary_key]
    if {field.attname for field in fields} != set(values):
        raise TenantDumpVerificationError("A target seed's reviewed columns drifted.")
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {quote(model._meta.db_table)} ("
            + ", ".join(quote(field.column) for field in fields)
            + ") VALUES (" + ", ".join(["%s"] * len(fields)) + ") RETURNING "
            + quote(model._meta.pk.column),
            [field.get_db_prep_save(values[field.attname], connection) for field in fields],
        )
        pk = cursor.fetchone()[0]
    return {model._meta.pk.attname: pk, **values}


def seed_projection_roles(using, makerspace_id, baseline):
    now, roles, scopes, ids = timezone.now(), [], [], {}
    for legacy, name, actions, *slug_parts in (*DEFAULT_ROLE_DEFINITIONS, MEMBER_ROLE_DEFINITION):
        slug = slug_parts[0] if slug_parts else legacy
        row = _insert_generated(using, "makerspaces.MakerspaceRole", dict(
            makerspace_id=makerspace_id, name=name, slug=slug, granted_actions=sorted(actions),
            legacy_role=legacy, is_default=True, is_protected=True, created_at=now, updated_at=now,
        ))
        ids[slug] = row["id"]
        roles.append(row)
    if "member" not in ids or "machine_manager" not in ids:
        raise TenantDumpVerificationError("The target protected role definitions are incomplete.")
    for machine_type in baseline.rows["machines.MachineType"]:
        scopes.append(_insert_generated(using, "machines.RoleMachineTypeScope", dict(
            role_id=ids["machine_manager"], machine_type_id=machine_type["id"], created_at=now,
        )))
    return ids, {"makerspaces.MakerspaceRole": tuple(roles), "machines.RoleMachineTypeScope": tuple(scopes)}


def close_projection_fence(using, makerspace_id, operation_id):
    row = _insert_generated(using, "encryption.PiiMakerspaceWriteFence", dict(
        makerspace_id=makerspace_id, state="closed", operation_id=operation_id,
        operation_kind="tenant_import", actor_id=None, closed_at=timezone.now(), opened_at=None,
    ))
    with connections[using].cursor() as cursor:
        cursor.execute("SET LOCAL app.pii_fence_operation = %s", [str(operation_id)])
    return row


def open_projection_fence(using, row):
    expected = dict(row, state="open", operation_id=None, operation_kind=None,
                    actor_id=None, closed_at=None, opened_at=timezone.now())
    model = apps.get_model("encryption.PiiMakerspaceWriteFence")
    quote = connections[using].ops.quote_name
    with connections[using].cursor() as cursor:
        cursor.execute(f"UPDATE {quote(model._meta.db_table)} SET state = 'open', "
                       "operation_id = NULL, operation_kind = NULL, actor_id = NULL, "
                       "closed_at = NULL, opened_at = %s WHERE id = %s AND state = 'closed' "
                       "AND operation_id = %s AND operation_kind = 'tenant_import'",
                       [expected["opened_at"], row["id"], row["operation_id"]])
        if cursor.rowcount != 1:
            raise TenantDumpVerificationError("The target tenant fence could not be reopened.")
    return (expected,)


def verify_bootstrap_rows(using, baseline, generated):
    # Separate the immutable migration commitment from explicit generated outputs.
    # Neither expected digest is derived from post-load database contents.
    actual = read_model_rows(using, set(baseline.rows) | set(generated))
    actual["machines.MachineType"] = tuple(row for row in actual["machines.MachineType"]
                                           if row["makerspace_id"] is None)
    baseline_actual = {label: actual[label] for label in baseline.rows}
    generated_actual = {label: actual[label] for label in generated}
    if (projected_raw_digest(baseline.rows) != baseline.baseline_sha256
            or projected_raw_digest(baseline_actual) != baseline.baseline_sha256
            or projected_raw_digest(generated_actual) != projected_raw_digest(generated)
            or any(len(actual[label]) != len(records)
                   for label, records in {**baseline.rows, **generated}.items())
            or _migration_rows(using) != baseline.migration_rows):
        raise TenantDumpVerificationError("Target-owned bootstrap identities or content changed.")


def bootstrap_sha256(baseline, generated):
    from .tenant_dump_semantic_expectations import value_sha256
    return value_sha256({"baseline_sha256": baseline.baseline_sha256,
                         "generated_sha256": projected_raw_digest(generated),
                         "migration_rows": baseline.migration_rows})
