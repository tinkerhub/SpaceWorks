"""Keep purge validation, non-atomic/CSRF fences, print-item N and reads unchanged."""
import ast
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.test import Client, RequestFactory
from django.urls import resolve, reverse

from apps.operations.models import QrPrintBatch
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from apps.tenant_migration.gate_http_ownership import (
    SERVICE_OWNED_HTTP_BOUNDARIES, api_owns_http_boundary, service_owns_http_boundary,
)
from tests.qr_source_safety.state_helpers import state
from tests.qr_target_safety_helpers import qr_for, target

from .assertions import no_gate_or_dml, statements
from .auth_setup import freeze, native_session
from .cases import prepared

pytestmark = pytest.mark.django_db(transaction=True)

PURGES = (
    "admin:makerspaces_modulepurgereceipt_retry_cleanup",
    "admin:makerspaces_purgereceipt_retry_cleanup",
    "admin:makerspaces_makerspace_purge_confirmed",
)


def purge_url(route):
    return reverse(route, args=[] if route == PURGES[2] else [uuid4()])


def test_original_purge_ast_validator_still_accepts_its_separate_three_routes():
    from apps.tenant_migration.source_gate_owned_http_guards import validate_service_owned_http_boundaries

    apps_dir = Path(__file__).resolve().parents[2] / "apps"
    assert set(SERVICE_OWNED_HTTP_BOUNDARIES) == set(PURGES)
    validate_service_owned_http_boundaries(apps_dir, AssertionError)
    tree = ast.parse((apps_dir / "tenant_migration/gate_http_ownership.py").read_text())
    validator = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "service_owns_http_boundary")
    # Preserve both checks on the real callback, separate from DRF ownership.
    rendered = ast.unparse(validator)
    assert "'_non_atomic_requests'" in rendered and "'default'" in rendered
    assert "'csrf_exempt'" in rendered
    assert "API_OWNED_HTTP_BOUNDARIES" not in rendered


@pytest.mark.parametrize("route", PURGES)
def test_actual_purge_callback_is_non_atomic_csrf_protected_and_separately_owned(route):
    url = purge_url(route)
    match = resolve(url)
    request = RequestFactory().post(url)
    assert match.view_name == route
    assert "default" in match.func._non_atomic_requests
    assert getattr(match.func, "csrf_exempt", False) is False
    with statements() as sql:
        assert service_owns_http_boundary(request, match) is True
        assert api_owns_http_boundary(request, match) is False
        assert service_owns_http_boundary(SimpleNamespace(method="GET"), match) is False
    no_gate_or_dml(sql)


@pytest.mark.parametrize("route", PURGES)
@pytest.mark.parametrize("attribute,value", [("_non_atomic_requests", set()), ("csrf_exempt", True)])
def test_actual_purge_callback_still_refuses_loss_of_non_atomic_or_csrf_fence(
    monkeypatch, route, attribute, value,
):
    url = purge_url(route)
    match = resolve(url)
    with monkeypatch.context() as single:
        single.setattr(match.func, attribute, value, raising=False)
        with statements() as sql:
            with pytest.raises(SourceMigrationGateUnavailable):
                service_owns_http_boundary(RequestFactory().post(url), match)
        no_gate_or_dml(sql)


@pytest.mark.parametrize("route", PURGES)
def test_real_admin_csrf_control_still_refuses_post_without_token(closure_lab, route):
    client = Client(HTTP_HOST="testserver", enforce_csrf_checks=True)
    # Authenticate setup before the measured request. A valid staff session cannot
    # bypass CSRF even though its dedicated purge URL owns the service boundary.
    assert client.login(username=closure_lab.root.username, password="Stage3-native-test-password")
    before = state()
    with statements() as sql:
        response = client.post(purge_url(route), {})
    assert response.status_code == 403
    no_gate_or_dml(sql)
    assert state() == before


def test_actual_print_item_post_keeps_default_source_n_protection(closure_lab):
    lab = closure_lab
    qr = qr_for(lab.home, target(lab.home, "product"), "product", created_by=lab.actor)
    batch = QrPrintBatch.objects.create(makerspace=lab.home, title="Ordinary N", created_by=lab.actor)
    url = reverse("qr-print-batch-items", args=[batch.pk])
    assert api_owns_http_boundary(RequestFactory().post(url), resolve(url)) is False
    freeze(lab)
    before = state()
    with statements() as sql:
        response = lab.api.post(url, {"qr_code_id": qr.pk}, format="json")
    assert response.status_code == 423
    assert response.json()["code"] == "tenant_migration_quiesced"
    assert any('FROM "tenant_migration_sourcemigrationgate"' in row["sql"] for row in sql)
    assert not [row for row in sql if row["sql"].startswith(("INSERT ", "UPDATE ", "DELETE "))]
    assert state() == before


def test_actual_qr_print_get_remains_a_read_without_source_gate_query(closure_lab):
    lab = closure_lab
    qr = qr_for(lab.home, target(lab.home, "product"), "product", created_by=lab.actor)
    url = reverse("qr-print", args=[qr.pk])
    expected = lab.api.get(url)
    assert expected.status_code == 200
    freeze(lab)
    before = state()
    with statements() as sql:
        response = lab.api.get(url)
    assert response.status_code == 200 and response.json() == expected.json()
    no_gate_or_dml(sql)
    assert state() == before


def test_qr_containers_post_keeps_default_protection_despite_shared_view_class(closure_lab):
    lab = closure_lab
    url = reverse("qr-containers")
    freeze(lab)
    before = state()
    with statements() as sql:
        response = lab.api.post(url, {"makerspace_id": lab.home.pk, "label": "Alias"}, format="json")
    assert response.status_code == 423
    assert response.json()["code"] == "tenant_migration_quiesced"
    assert any('FROM "tenant_migration_sourcemigrationgate"' in row["sql"] for row in sql)
    assert not [row for row in sql if row["sql"].startswith(("INSERT ", "UPDATE ", "DELETE "))]
    assert state() == before


@pytest.mark.parametrize("route", ["qr-tools", "qr-revoke", "asset-qr"])
@pytest.mark.parametrize("method", ["put", "delete"])
def test_other_unsafe_methods_keep_ordinary_frozen_tenant_protection(closure_lab, route, method):
    session = native_session(closure_lab)
    case = prepared(closure_lab, route, session.client)
    freeze(closure_lab)
    before = state()
    with statements() as sql:
        response = getattr(session.client, method)(case.url, case.data, format="json")
    assert response.status_code == 423
    assert response.json()["code"] == "tenant_migration_quiesced"
    assert any('FROM "tenant_migration_sourcemigrationgate"' in row["sql"] for row in sql)
    assert not [row for row in sql if row["sql"].startswith(("INSERT ", "UPDATE ", "DELETE "))]
    assert state() == before
