"""Actual recovered-principal service -> fresh SQL proof -> root host acknowledgement."""

import pytest
from django.db import connection
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.backup.inplace_recovery_facts import query_recovery_proof
from apps.backup.host_marker import MarkerState, read_marker
from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.recovery import RESIDUAL_RISK, acknowledge_quarantine, enter_quarantine, set_recovery_principal
from tests.backup.recovery_test_support import CONFIG, RESTORE_ID, TOPOLOGY, archive_row, marker_rig


pytestmark = pytest.mark.django_db(transaction=True)


def test_actual_database_ack_does_not_release_host_until_fresh_root_bound_proof(tmp_path):
    with marker_rig(tmp_path) as rig:
        principal = User.objects.create_superuser(username="recovered-principal", password="unused")
        other = User.objects.create_superuser(username="other-principal", password="unused")
        archive = archive_row()
        restore = RestoreOperation.objects.create(id=RESTORE_ID, archive=archive, kind="disaster", stage="validating", decision="proceed")
        rig.begin()
        rig.phases()
        enter_quarantine(restore, "Stage3 actual principal acknowledgement proof")
        rig.complete(query_recovery_proof(connection, RESTORE_ID))
        assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER
        set_recovery_principal(principal, "local-proof-password-with-enough-entropy")
        with pytest.raises(PermissionDenied):
            acknowledge_quarantine(other, RESIDUAL_RISK)
        with pytest.raises(ValidationError):
            acknowledge_quarantine(principal, "yes")
        acknowledge_quarantine(principal, RESIDUAL_RISK)
        assert DeploymentRecoveryState.objects.get(pk=1).mode == "normal"
        assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER
        fresh = query_recovery_proof(connection, RESTORE_ID)
        assert fresh["acknowledged_by"] == fresh["recovery_principal"] == principal.pk
        rig.controller.acknowledge(rig.operation, rig.identity, fresh,
            configuration_sha256=CONFIG, topology_sha256=TOPOLOGY)
        assert read_marker(rig.marker).state == MarkerState.ACKNOWLEDGED_NORMAL
