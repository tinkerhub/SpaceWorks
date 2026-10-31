"""Genuine QUIESCED gates refuse valid real HTTP mutations before any writes."""
import pytest
from django.urls import reverse

from apps.boxes.models import QrCode
from tests.qr_source_safety.http_helpers import (
    CROSS_WRITERS, WRITERS, closure_lab, prepared, success,
)
from tests.qr_source_safety.state_helpers import assert_gate, state
from tests.qr_target_safety_helpers import qr_for, target
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", WRITERS)
def test_actual_http_open_positive_control(closure_lab, kind):
    case = prepared(closure_lab, kind)
    response = case.call()
    assert response.status_code == success(kind), getattr(response, "data", response.content)


@pytest.mark.parametrize("kind", WRITERS)
def test_genuine_quiesced_actual_owner_refuses_all_writers(closure_lab, kind):
    case = prepared(closure_lab, kind)
    close_gate(closure_lab.home, closure_lab.root)
    before = state()
    assert_gate(case.call())
    # Includes LogEntry: source-held dispatch must refuse before attempt history.
    assert state() == before


@pytest.mark.parametrize("kind", CROSS_WRITERS)
@pytest.mark.parametrize("frozen", ["source", "destination"])
def test_cross_maker_each_independent_gate_refuses_valid_transfer(closure_lab, kind, frozen):
    case = prepared(closure_lab, kind)
    close_gate(closure_lab.home if frozen == "source" else closure_lab.other, closure_lab.root)
    before = state()
    assert_gate(case.call())
    assert state() == before


@pytest.mark.parametrize("kind", ["native-cross-product", "native-cross-asset"])
def test_native_cross_transfer_open_positive_control(closure_lab, kind):
    case = prepared(closure_lab, kind)
    assert case.call().status_code == 302
    case.qr.refresh_from_db()
    assert case.qr.makerspace_id == closure_lab.other.pk
    assert case.qr.status == QrCode.Status.ACTIVE


@pytest.mark.parametrize("kind", ["box", "product", "asset"])
def test_print_get_stays_available_and_read_only_while_quiesced(closure_lab, kind):
    obj = target(closure_lab.home, kind)
    qr = qr_for(closure_lab.home, obj, kind)
    url = reverse("qr-print", args=[qr.pk])
    original = closure_lab.api.get(url)
    assert original.status_code == 200
    close_gate(closure_lab.home, closure_lab.root)
    before = state()
    response = closure_lab.api.get(url)
    assert response.status_code == 200
    assert response.data == original.data
    assert set(response.data) == {"payload", "svg", "target"}
    assert state() == before


@pytest.mark.parametrize("route", ["container-detail", "container-contents", "container-history"])
def test_existing_get_container_lookup_remains_read_only_when_quiesced(closure_lab, route):
    lab = closure_lab
    box = target(lab.home, "box")
    qr_for(lab.home, box, "box", payload=box.code)
    url = reverse(route, args=[box.pk])
    original = lab.api.get(url)
    assert original.status_code == 200
    close_gate(lab.home, lab.root)
    before = state()
    response = lab.api.get(url)
    assert response.status_code == 200 and response.data == original.data
    assert state() == before
