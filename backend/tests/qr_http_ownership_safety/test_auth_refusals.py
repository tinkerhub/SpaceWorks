"""Ownership delegation must retain all existing JWT and native-selection refusals."""
import pytest

from apps.accounts.models_devices import DeviceGrant
from apps.backup.models import DeploymentRecoveryState
from tests.qr_source_safety.state_helpers import state

from .assertions import dml, no_gate_or_dml, statements
from .auth_setup import freeze, native_session
from .cases import ROUTES, prepared
from .p_protocol import refused_dispatch
from .refusal_setup import REFUSALS, deny, protocol_rows

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("kind,status,detail", REFUSALS)
def test_real_native_jwt_and_selection_refusals_precede_qr_gate_and_domain_writes(
    closure_lab, route, kind, status, detail,
):
    lab = closure_lab
    session = native_session(lab)
    case = prepared(lab, route, session.client)
    deny(session, lab, kind)
    freeze(lab)
    before, auth_before = state(), protocol_rows()
    grant_before = DeviceGrant.objects.values().get(pk=session.grant.pk)
    with statements() as sql:
        response = case.call()
    assert response.status_code == status, response.content
    assert detail.lower() in response.json()["detail"].lower()
    if kind == "must-change-password":
        # Auth completed before IsActiveStaff refuses password rotation. Its global
        # last_used update is expected, and remains separate from QR domain state.
        updates = [row for row in sql if dml(row["sql"])]
        assert len(updates) == 1 and updates[0]["sql"].startswith('UPDATE "accounts_devicegrant"')
        grant_after = DeviceGrant.objects.values().get(pk=session.grant.pk)
        assert grant_after["last_used_at"] > grant_before["last_used_at"]
        assert grant_after == {**grant_before, "last_used_at": grant_after["last_used_at"]}
        assert protocol_rows() == {**auth_before, "accounts.devicegrant": [grant_after]}
        assert not [row for row in sql if '"tenant_migration_sourcemigrationgate"' in row["sql"]]
    else:
        no_gate_or_dml(sql)
        assert protocol_rows() == auth_before
    assert state() == before


@pytest.mark.parametrize("route", ROUTES)
def test_real_recovery_principal_check_still_refuses_if_quarantine_begins_before_auth(
    closure_lab, settings, route, record_property,
):
    lab = closure_lab
    session = native_session(lab)
    case = prepared(lab, route, session.client)
    before, auth_before = state(), protocol_rows()

    def quarantine_after_outer_recovery_gate():
        DeploymentRecoveryState.objects.filter(pk=1).update(
            mode=DeploymentRecoveryState.Mode.QUARANTINED, recovery_principal=lab.root,
        )

    response, sql = refused_dispatch(settings, case, record_property,
                                      before_auth=quarantine_after_outer_recovery_gate)
    assert response.status_code == 401
    assert "out-of-band recovery superadmin" in response.json()["detail"]
    no_gate_or_dml(sql)
    assert state() == before and protocol_rows() == auth_before


@pytest.mark.parametrize("route", ROUTES)
def test_already_quarantined_deployment_retains_its_earlier_http_503(closure_lab, route):
    lab = closure_lab
    session = native_session(lab)
    case = prepared(lab, route, session.client)
    DeploymentRecoveryState.objects.filter(pk=1).update(
        mode=DeploymentRecoveryState.Mode.QUARANTINED, recovery_principal=lab.root,
    )
    before, auth_before = state(), protocol_rows()
    with statements() as sql:
        response = case.call()
    assert response.status_code == 503
    assert response.json()["code"] == "deployment_quarantined"
    no_gate_or_dml(sql)
    assert state() == before and protocol_rows() == auth_before
