"""Read-only target catalog bindings and complete pre-cutover proof."""

import hashlib

from django.db import DatabaseError, connections

from apps.backup.recipient_selection import BackupBuildError


def target_catalog_binding(payload, *, using):
    enforcement = payload.get("enforcement", {})
    schema = payload.get("schema", enforcement.get("schema", "public"))
    table = payload.get("table", enforcement.get("table"))
    if not isinstance(schema, str) or not isinstance(table, str):
        raise BackupBuildError("A reservation target relation is invalid.")
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT c.oid, pg_catalog.to_regprocedure("
            "'public.backup_b1_enforce_reservations()')::oid "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s "
            "AND c.relkind IN ('r','p')", [schema, table],
        )
        row = cursor.fetchone()
    if row is None or row[1] is None:
        raise BackupBuildError("The canonical reservation target/function is missing.")
    return {"target_relation_oid": row[0], "enforcement_function_oid": row[1]}


def installed_trigger_oid(payload, *, using):
    binding = target_catalog_binding(payload, using=using)
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT public.backup_b1_live_guard(%s::oid, %s::oid)",
            [binding["target_relation_oid"], binding["enforcement_function_oid"]],
        )
        oid = cursor.fetchone()[0]
    if oid is None:
        raise BackupBuildError("The installed reservation trigger is absent or unsafe.")
    return oid


def prove_installation(
    operation, *, catalog_verified=False, require_timestamps=True, using
):
    try:
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT public.backup_b1_prove_installation(operation, %s, %s) "
                "FROM public.backup_b1restoreoperationstate operation "
                "WHERE operation.operation_id=%s",
                [catalog_verified, require_timestamps, operation.pk],
            )
            row = cursor.fetchone()
    except DatabaseError as exc:
        raise BackupBuildError("The complete pre-cutover installation proof failed.") from exc
    if row is None or row[0] is not True:
        raise BackupBuildError("The complete pre-cutover installation proof failed.")


def _relation_declaration(table, using):
    with connections[using].cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*), COALESCE(jsonb_agg(to_jsonb(snapshot) "
            f"ORDER BY to_jsonb(snapshot)::text)::text, '[]') "
            f"FROM public.{table} AS snapshot"
        )
        count, rows = cursor.fetchone()
    return {"schema": "public", "table": table, "expected_rows": count,
            "sha256": hashlib.sha256(rows.encode()).hexdigest()}


def _fence_declarations(using):
    result = []
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT namespace.nspname, relation.relname, trigger.tgname, "
            "pg_get_triggerdef(trigger.oid, true) FROM pg_trigger trigger "
            "JOIN pg_class relation ON relation.oid=trigger.tgrelid "
            "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "WHERE trigger.tgname='backup_b1_reservation_guard' "
            "AND trigger.tgenabled IN ('O','A') AND NOT trigger.tgisinternal "
            "ORDER BY namespace.nspname, relation.relname"
        )
        for schema, table, trigger, definition in cursor.fetchall():
            result.append({
                "schema": schema, "table": table, "trigger": trigger,
                "enabled": True,
                "definition_sha256": hashlib.sha256(definition.encode()).hexdigest(),
            })
    return result


