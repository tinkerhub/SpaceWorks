"""Fresh real SQL state through TenantGateTask, including tenant-gate exceptions."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext

from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.task_admission import DeploymentRecoveryTaskBlocked
from apps.tenant_migration.task_gate import TenantGateTask
from tests.backup.recovery_test_support import archive_row


pytestmark = pytest.mark.django_db(transaction=True)
NAMES = ["apps.integrations.tasks.deliver_email_task",
    "apps.backup.tasks.scheduled_deployment_backup_task",
    "apps.evidence.tasks.sweep_evidence_retention_task"]


def probe_task(name, effects):
    from config.celery import app

    class Probe(TenantGateTask):
        def run(self, *args, **kwargs):
            effects.append((args, kwargs))
            return "effect"
    Probe.bind(app)  # Normal registered tasks have Celery's request stack.
    task = Probe()
    task.name = name
    return task


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("mode", ["quiesced", "quarantined", "target_import", "unknown", None])
def test_non_normal_missing_and_unknown_refuse_before_resolver_or_effect(name, mode):
    if mode is None:
        DeploymentRecoveryState.objects.filter(pk=1).delete()
    else:
        DeploymentRecoveryState.objects.filter(pk=1).update(mode=mode)
    effects = []
    task = probe_task(name, effects)
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(DeploymentRecoveryTaskBlocked):
            task(7001)  # An old integer ID must not even resolve on replacement data.
    statements = [row["sql"].lower() for row in queries]
    assert any("backup_deploymentrecoverystate" in sql for sql in statements)
    assert not any("integrations_emaillog" in sql for sql in statements)
    assert not any("insert into" in sql for sql in statements)
    assert effects == []
    if mode is None:
        assert not DeploymentRecoveryState.objects.filter(pk=1).exists()


@pytest.mark.parametrize("name", NAMES)
def test_each_invocation_reads_existing_primary_state_afresh(name):
    effects = []
    task = probe_task(name, effects)
    DeploymentRecoveryState.objects.filter(pk=1).update(mode="normal")
    with CaptureQueriesContext(connection) as queries:
        # Missing job row produces no tenant ID, but deployment fence still queries.
        assert task(7001) == "effect"
    assert any("backup_deploymentrecoverystate" in row["sql"].lower() for row in queries)
    DeploymentRecoveryState.objects.filter(pk=1).update(mode="quarantined")
    with pytest.raises(DeploymentRecoveryTaskBlocked):
        task(7001)
    assert len(effects) == 1
    DeploymentRecoveryState.objects.filter(pk=1).update(mode="normal")
    assert task(7001) == "effect"
    assert len(effects) == 2


def test_database_read_failure_does_not_escape_into_task_or_reveal_driver_details():
    effects = []
    def unavailable(execute, sql, params, many, context):
        if "backup_deploymentrecoverystate" in sql:
            raise DatabaseError("private-driver-secret")
        return execute(sql, params, many, context)
    with connection.execute_wrapper(unavailable):
        with pytest.raises(DeploymentRecoveryTaskBlocked, match="unreadable") as error:
            probe_task(NAMES[0], effects)(7001)
    assert "private-driver-secret" not in str(error.value)
    assert effects == []


@pytest.mark.parametrize("mode", ["quiesced", "quarantined", "target_import"])
def test_actual_fail_command_retains_global_fence_and_active_operation(mode):
    archive = archive_row()
    restore = RestoreOperation.objects.create(archive=archive, kind="disaster", stage="db_restoring")
    DeploymentRecoveryState.objects.filter(pk=1).update(mode=mode, active_restore=restore)
    before = DeploymentRecoveryState.objects.values().get(pk=1)
    call_command("backup_control", "fail", str(restore.pk), "--message", "synthetic SQL failure", stdout=StringIO())
    restore.refresh_from_db()
    assert restore.stage == "failed" and restore.error_detail == "synthetic SQL failure"
    assert DeploymentRecoveryState.objects.values().get(pk=1) == before
    with pytest.raises(DeploymentRecoveryTaskBlocked):
        probe_task(NAMES[1], [])()
