"""Read-only readiness for the fixed management command while restore is blocked."""

from dataclasses import asdict
from pathlib import Path
import sys

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.backup.database_identity import query_live_database_identity
from apps.backup.full_format import FULL_FORMAT
from apps.backup.host_marker import MarkerState
from apps.backup.host_readiness import HostReadinessError, _verify_fences, _verify_relations
from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.process_roles import ProcessRole, admission_for


def assert_inplace_ready(marker, restore):
    """Do not grant backend admission or run migrations to obtain this proof."""
    if (Path(sys.argv[0]).name != "manage.py"
            or sys.argv[1:] != ["backup_control", "validate", str(restore.pk)]
            or marker.state != MarkerState.RESTORE_BLOCKED
            or not admission_for(marker.state, ProcessRole.MANAGEMENT).admitted
            or admission_for(marker.state, ProcessRole.BACKEND).admitted):
        raise HostReadinessError("Blocked restore readiness requires the fixed management command.")
    operation = marker.operation
    if (operation is None or operation.restore_id != str(restore.pk)
            or operation.artifact_sha256 != restore.archive.archive_sha256
            or restore.stage != RestoreOperation.Stage.VALIDATING):
        raise HostReadinessError("Blocked restore readiness operation does not match the selected archive.")
    if (restore.archive.manifest.get("format") == FULL_FORMAT
            and operation.capture_id != restore.archive.manifest.get("capture_id")):
        raise HostReadinessError("Blocked restore readiness source capture identity changed.")
    bound = marker.require_bound_database()
    if bound.server_identity is None:
        raise HostReadinessError("Blocked restore readiness lacks immutable target identity.")
    try:
        with transaction.atomic():
            state = DeploymentRecoveryState.objects.get(pk=1)
            if (state.mode != DeploymentRecoveryState.Mode.QUIESCED
                    or state.active_restore_id != restore.pk):
                raise HostReadinessError("Blocked restore readiness requires the same active quiesced operation.")
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM public.backup_deploymentdatabaseidentity")
                if cursor.fetchone()[0] != 1:
                    raise HostReadinessError("Blocked restore readiness identity singleton is not unique.")
            connection.ensure_connection()
            live = query_live_database_identity(connection.connection)
            expected = bound.server_identity
            if (live.endpoint.database != bound.name or live.oid != bound.oid
                    or asdict(live.endpoint) != expected["endpoint"]
                    or live.database_uuid != expected["database_uuid"]
                    or (live.system_identifier is not None
                        and expected["system_identifier"] is not None
                        and live.system_identifier != expected["system_identifier"])):
                raise HostReadinessError("Blocked restore readiness immutable target identity changed.")
            with connection.cursor() as cursor:
                reservations = _verify_relations(cursor, "Reservation", marker.reservations)
                fences = _verify_fences(cursor, marker.fences)
                not_restored = _verify_relations(cursor, "Not-restored", marker.not_restored)
            executor = MigrationExecutor(connection)
            if executor.migration_plan(executor.loader.graph.leaf_nodes()):
                raise HostReadinessError("Database migrations are not at the application leaves.")
    except HostReadinessError:
        raise
    except Exception as exc:
        raise HostReadinessError("Blocked restore readiness facts could not be verified.") from exc
    return {"marker_state": marker.state.value, "database_routing": marker.database_routing,
            "database_oid": live.oid, "migrations": "applied", "reservations": reservations,
            "fences": fences, "not_restored": not_restored}
