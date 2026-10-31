"""Request flags confer no lock ownership; the real trusted P context is required."""
import pytest
from django.test import RequestFactory

from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_locks import _unscoped_writer_owned, unscoped_writer_shared_boundary
from apps.tenant_migration.gate_runtime import assert_request_write_allowed
from apps.tenant_migration.middleware import SourceMigrationGateMiddleware
from tests.qr_source_safety.state_helpers import state

from .assertions import no_gate_or_dml, statements, unavailable
from .cases import PATHS, ROUTES, declaration, matched
from .drift import binding_drift

pytestmark = pytest.mark.django_db(transaction=True)


def request_for(route):
    request = RequestFactory().post(PATHS[ROUTES.index(route)])
    request.resolver_match = matched(route)
    return request


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("forged_flags", [False, True])
def test_direct_late_assertion_without_actual_p_context_is_typed_unavailable(route, forged_flags):
    request = request_for(route)
    if forged_flags:
        for name in ("_unscoped_writer_owned", "_source_gate_owned", "source_gate_owned",
                     "api_owns_http_boundary", "_source_gate_api_owned"):
            setattr(request, name, True)
    assert _unscoped_writer_owned.get() is False
    before = state()
    with statements() as captured:
        with pytest.raises(SourceMigrationGateUnavailable) as error:
            assert_request_write_allowed(request)
    assert error.value.code == "tenant_migration_gate_unavailable"
    no_gate_or_dml(captured)
    assert state() == before
    # This is the real exception translator, not a claim that bare DRF callbacks
    # install Django middleware. Full HTTP translation is covered by drift tests.
    translated = SourceMigrationGateMiddleware(lambda request: None).process_exception(
        request, error.value,
    )
    unavailable(translated)


@pytest.mark.parametrize("route", ROUTES)
def test_late_assertion_accepts_the_actual_p_boundary_without_tenant_gate_query(route):
    request = request_for(route)
    assert _unscoped_writer_owned.get() is False
    with unscoped_writer_shared_boundary():
        assert _unscoped_writer_owned.get() is True
        with statements() as captured:
            assert_request_write_allowed(request)
        no_gate_or_dml(captured)
    assert _unscoped_writer_owned.get() is False


@pytest.mark.parametrize("route", ROUTES)
def test_late_guard_revalidates_declaration_even_when_actual_p_is_held(monkeypatch, route):
    request = request_for(route)
    expression, owner = declaration(route)[2][0]
    before = state()
    with unscoped_writer_shared_boundary():
        with monkeypatch.context() as single:
            binding_drift(single, route, expression, owner, "consumed-alias")
            with statements() as captured:
                with pytest.raises(SourceMigrationGateUnavailable):
                    assert_request_write_allowed(request)
            no_gate_or_dml(captured)
    assert state() == before


@pytest.mark.parametrize("route", ROUTES)
def test_actual_http_late_drift_is_translated_to_503_before_native_last_used_write(
    closure_lab, settings, monkeypatch, route, record_property,
):
    from .auth_setup import native_session
    from .cases import prepared
    from .p_protocol import refused_dispatch
    from .refusal_setup import protocol_rows

    session = native_session(closure_lab)
    case = prepared(closure_lab, route, session.client)
    expression, owner = declaration(route)[2][0]
    before, auth_before = state(), protocol_rows()
    with monkeypatch.context() as single:
        # The first ownership check has succeeded and real P is held before the
        # controller changes this ONE consumed value. Auth's late check must catch it.
        response, sql = refused_dispatch(
            settings, case, record_property,
            before_auth=lambda: binding_drift(single, route, expression, owner, "consumed-alias"),
        )
        unavailable(response)
        no_gate_or_dml(sql)
    assert state() == before and protocol_rows() == auth_before
