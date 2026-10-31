"""Resolved URL callbacks and consumed bindings, exercised through the real guard."""
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_http_ownership import (
    API_OWNED_HTTP_BOUNDARIES, api_owns_http_boundary,
)
from tests.qr_source_safety.state_helpers import state

from .assertions import no_gate_or_dml, statements, unavailable
from .cases import BINDINGS, PATHS, ROUTES, declaration, imported, matched, prepared
from .drift import binding_drift, class_drift, replace_barrel, replace_callback

pytestmark = pytest.mark.django_db(transaction=True)


def test_registry_has_exactly_the_eight_approved_declarations():
    assert API_OWNED_HTTP_BOUNDARIES == {route: declaration(route) for route in ROUTES}


@pytest.mark.parametrize("route", ROUTES)
def test_actual_resolved_post_class_barrel_and_consumed_bindings_are_accepted(route):
    match = matched(route)
    canonical, alias, bindings = declaration(route)
    view = imported(canonical)
    assert match.view_name == route
    assert match.func.cls is match.func.view_class is imported(alias) is view
    for expression, owner in bindings:
        parts = expression.split(".")
        consumed = view.post.__globals__[parts[0]]
        if len(parts) == 2:
            from apps.operations import services

            assert consumed is services
            consumed = getattr(consumed, parts[1])
        assert consumed is imported(owner) and callable(consumed)
    with statements() as captured:
        assert api_owns_http_boundary(RequestFactory().post(PATHS[ROUTES.index(route)]), match)
    no_gate_or_dml(captured)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "TRACE", "PUT", "PATCH", "DELETE"])
def test_every_other_method_declines_delegation(route, method):
    request = RequestFactory().generic(method, PATHS[ROUTES.index(route)])
    with statements() as captured:
        assert api_owns_http_boundary(request, matched(route)) is False
    no_gate_or_dml(captured)


@pytest.mark.parametrize("name,path", [
    ("qr-containers", "/api/v1/admin/qr/containers"),
    ("qr-print", "/api/v1/admin/qr/17/print"),
    ("qr-print-batch-items", "/api/v1/admin/qr-print-batches/17/items"),
])
@pytest.mark.parametrize("method", ["POST", "GET"])
def test_resolved_alias_print_and_print_item_are_not_delegated(name, path, method):
    from django.urls import resolve

    match = resolve(path)
    assert match.view_name == name
    with statements() as captured:
        assert api_owns_http_boundary(RequestFactory().generic(method, path), match) is False
    no_gate_or_dml(captured)


def test_unknown_name_cannot_borrow_a_known_callback_to_delegate():
    match = matched("qr-tools")
    unknown = SimpleNamespace(view_name="not-an-approved-route", func=match.func)
    with statements() as captured:
        assert api_owns_http_boundary(SimpleNamespace(method="POST"), unknown) is False
        assert api_owns_http_boundary(SimpleNamespace(method="POST"), None) is False
    no_gate_or_dml(captured)


def assert_http_drift(lab, route, patch, mutate):
    case = prepared(lab, route)
    before = state()
    with patch.context() as single:
        mutate(single)
        with statements() as captured:
            with pytest.raises(SourceMigrationGateUnavailable) as error:
                api_owns_http_boundary(SimpleNamespace(method="POST"), matched(route))
            assert error.value.code == "tenant_migration_gate_unavailable"
            response = case.call()
        unavailable(response)
        no_gate_or_dml(captured)
    assert state() == before


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("kind", ["canonical-class", "url-alias", "post-function", "post-globals", "import-failure"])
def test_declared_class_alias_post_and_import_drift_fail_closed(closure_lab, monkeypatch, route, kind):
    assert_http_drift(closure_lab, route, monkeypatch,
                      lambda single: class_drift(single, route, kind))


@pytest.mark.parametrize("route", ["qr-tools", "asset-generate"])
@pytest.mark.parametrize("kind", ["borrowed-metadata", "callback-globals", "defaults", "kwdefaults",
                                  "initkwargs", "view-initkwargs", "missing-wrapper", "closure",
                                  "wrong-callback-class"])
def test_borrowed_callback_metadata_and_hidden_capture_drift_fail_closed(
    closure_lab, monkeypatch, route, kind,
):
    assert_http_drift(closure_lab, route, monkeypatch,
                      lambda single: replace_callback(single, route, kind))


@pytest.mark.parametrize("route,expression,owner", BINDINGS)
@pytest.mark.parametrize("kind", ["missing-service", "noncallable-service", "canonical-service",
                                  "consumed-alias", "missing-consumed-alias"])
def test_every_consumed_owner_binding_must_remain_canonical(
    closure_lab, monkeypatch, route, expression, owner, kind,
):
    assert_http_drift(closure_lab, route, monkeypatch,
                      lambda single: binding_drift(single, route, expression, owner, kind))


def test_generation_rejects_barrel_object_substitution_even_with_same_service(closure_lab, monkeypatch):
    assert_http_drift(closure_lab, "asset-generate", monkeypatch, replace_barrel)
