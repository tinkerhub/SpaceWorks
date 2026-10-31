"""Module serialization, global QUIESCED policy and complete transactional rollback."""
import pytest
from rest_framework.exceptions import ValidationError

from apps.boxes.models import QrCode
from apps.makerspaces.module_install import uninstall_module
from apps.operations.models import QrPrintBatchItem
from apps.operations.services_qr_assets import add_qr_to_batch
from tests.box_parent_safety.pg_helpers import (
    assert_maker_mode, blocked_by, maker_lock, workers,
)
from tests.qr_print_race_safety.helpers import (
    add_http, assert_no_writes, events, evidence, item_write, lab, prepare,
    qr_lock, row, state,
)
from tests.qr_target_safety_helpers import fail_after_insert, qr_for, target
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_module_disable_commits_while_item_waits_then_returns_typed_400(
    lab, kind, record_property,
):
    case = prepare(lab, kind)
    with workers() as start:
        disable = start(
            lambda: uninstall_module(lab.home, "qr_print_batches", actor=lab.mover),
            pause=maker_lock,
        )
        disable.paused()
        assert_maker_mode(next(s for s in disable.statements if maker_lock(s)), "FOR UPDATE")
        api = start(lambda: add_http(lab, case))
        pending = blocked_by(api, disable.pid)
        evidence(record_property, pending, disable.pid)
        assert_maker_mode(pending, "FOR NO KEY UPDATE")
        assert not any(qr_lock(s) or item_write(s) for s in api.statements)
        assert disable.finish() == ["qr_print_batches"]
        disabled = state()
        response = api.finish()
    assert response.status_code == 400, response.data
    assert response.data["module"].code == "invalid"
    assert "qr_print_batches" in str(response.data["module"])
    assert state() == disabled
    assert_no_writes(api.statements)
    assert not any(qr_lock(s) for s in api.statements)
    assert not events().exists()


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("existing", [False, True], ids=["new-item", "existing-item"])
def test_genuine_quiesced_global_middleware_refuses_valid_http_before_item_writes(lab, kind, existing):
    case = prepare(lab, kind)
    # Prove host/JWT/roles/modules with an actual successful HTTP add. For the
    # new-item refusal use a separate, previously unprinted target afterwards.
    control = add_http(lab, case, label_text="Open control", sort_order=3)
    assert control.status_code == 201, control.data
    if not existing:
        case = prepare(lab, kind)
    close_gate(lab.home, lab.mover)
    before = state()
    with workers() as start:
        api = start(lambda: add_http(lab, case, label_text="Must not update", sort_order=9))
        response = api.finish()
    assert response.status_code == 423, response.content
    assert response.json()["code"] == "tenant_migration_quiesced"
    assert not any(maker_lock(s) or qr_lock(s) or item_write(s) for s in api.statements)
    assert_no_writes(api.statements)
    assert state() == before


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("existing", [False, True], ids=["new-item", "updated-item"])
def test_real_audit_insert_then_refusal_rolls_back_entire_item_and_audit_rows(
    lab, kind, existing, monkeypatch,
):
    case = prepare(lab, kind)
    if existing:
        response = add_http(lab, case, label_text="Original", sort_order=4)
        assert response.status_code == 201, response.data
    before, qr_before = state(), row(QrCode, case.qr.pk)
    action = "qr_print_batch_item.updated" if existing else "qr_print_batch_item.created"
    inserted = fail_after_insert(monkeypatch, action)
    with pytest.raises(RuntimeError, match="refusal after real audit INSERT"):
        add_http(lab, case, label_text="Refused revision", sort_order=11)
    assert len(inserted) == 1  # real record() and real INSERT executed before refusal
    assert state() == before  # includes all item/audit columns, MACs and timestamps
    assert row(QrCode, case.qr.pk) == qr_before


@pytest.mark.parametrize("kind", ["product", "asset"])
def test_initial_foreign_service_input_stays_400_and_http_lookup_stays_404(lab, kind):
    case = prepare(lab, kind)
    foreign = target(lab.other, kind)
    case.qr = qr_for(lab.other, foreign, kind, created_by=lab.mover)
    before = state()
    with pytest.raises(ValidationError, match="different makerspace") as error:
        add_qr_to_batch(lab.actor, lab.batch, case.qr)
    assert error.value.status_code == 400
    assert error.value.detail[0].code == "invalid"
    response = add_http(lab, case)
    assert response.status_code == 404, response.data
    assert response.data["detail"].code == "not_found"
    assert not QrPrintBatchItem.objects.exists()
    assert state() == before
