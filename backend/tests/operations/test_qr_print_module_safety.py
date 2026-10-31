"""OPS-S03: service/control guards and observed PostgreSQL toggle races."""
import pytest
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.messages import get_messages
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.makerspaces.module_install import uninstall_module
from apps.operations.models import QrPrintBatch
from apps.operations.services_qr_assets import mark_batch_printed
from tests.evidence.safety_pg_helpers import policy_claim_race
from tests.operations.qr_safety_helpers import (
    add_item, assert_event, asset, audit_ids, batch, generate, jwt_client,
    new_events, product, qr, qr_lab, state,
)

pytestmark = pytest.mark.django_db


def control_actor():
    return User.objects.create_user(
        username="qr-control-super", role=User.Role.SUPERADMIN,
        is_staff=True, is_superuser=True, access_status=User.AccessStatus.ACTIVE,
    )


def control_print(actor, labels):
    client = Client(HTTP_HOST="testserver")
    client.force_login(actor)
    response = client.post(
        reverse("admin:operations_qrprintbatch_changelist"),
        {"action": "mark_printed_selected", ACTION_CHECKBOX_NAME: [str(labels.pk)], "index": "0"},
    )
    assert response.status_code == 302
    return [(message.level, str(message)) for message in get_messages(response.wsgi_request)]


@pytest.mark.parametrize("entrypoint", ["service", "control"])
@pytest.mark.parametrize("enabled", [True, False], ids=["enabled-success", "disabled-refusal"])
def test_print_module_guard_uses_real_service_and_control_action(settings, entrypoint, enabled):
    lab = qr_lab(settings)
    labels = batch(lab)
    actor = control_actor() if entrypoint == "control" else lab.actor
    if not enabled:
        assert uninstall_module(lab.home, "qr_print_batches", actor=lab.actor) == ["qr_print_batches"]
    before, events_before = state(), audit_ids()

    if entrypoint == "control":
        notices = control_print(actor, labels)
        if enabled:
            assert notices == [(messages.SUCCESS, "Marked 1 QR print batch(es) as printed.")]
        else:
            assert len(notices) == 1 and notices[0][0] == messages.ERROR
            assert f"{labels.pk}:" in notices[0][1]
            assert "qr_print_batches" in notices[0][1] and "disabled" in notices[0][1]
    elif enabled:
        printed = mark_batch_printed(actor, labels)
        assert printed.pk == labels.pk
    else:
        with pytest.raises(ValidationError) as error:
            mark_batch_printed(actor, labels)
        assert error.value.detail["module"].code == "invalid"
        assert "qr_print_batches" in str(error.value.detail["module"])

    labels.refresh_from_db()
    if enabled:
        assert labels.status == QrPrintBatch.Status.PRINTED
        assert labels.printed_at is not None
        assert new_events(events_before).count() == 1
        assert_event(new_events(events_before).get(), lab, "qr_print_batch.printed", labels, actor=actor)
    else:
        assert labels.status == QrPrintBatch.Status.DRAFT and labels.printed_at is None
        assert state() == before


@pytest.mark.parametrize("entrypoint", ["service", "control"])
@pytest.mark.parametrize("status", [QrPrintBatch.Status.PRINTED, QrPrintBatch.Status.ARCHIVED])
def test_non_draft_guard_keeps_status_timestamp_and_audits_unchanged(settings, entrypoint, status):
    lab = qr_lab(settings)
    labels = batch(lab, status=status, printed_at=timezone.now())
    actor = control_actor() if entrypoint == "control" else lab.actor
    before = state()

    if entrypoint == "control":
        notices = control_print(actor, labels)
        assert len(notices) == 1 and notices[0][0] == messages.ERROR
        assert "Only draft QR print batches" in notices[0][1] and status in notices[0][1]
    else:
        with pytest.raises(ValidationError, match="Only draft QR print batches"):
            mark_batch_printed(actor, labels)
    assert state() == before


@pytest.mark.parametrize("route", ["generate", "asset-qr", "batch-create", "item-add"])
def test_module_off_http_refusal_has_no_domain_side_effects(settings, route):
    lab = qr_lab(settings)
    target = product(lab)
    unit = asset(target)
    labels, code = batch(lab), qr(lab, target)
    module = "asset_units" if route in {"generate", "asset-qr"} else "qr_print_batches"
    assert uninstall_module(lab.home, module, actor=lab.actor) == [module]
    before = state()

    if route == "generate":
        response = generate(lab, target)
    elif route == "asset-qr":
        response = lab.client.post(f"/api/v1/admin/assets/{unit.pk}/qr", {}, format="json")
    elif route == "batch-create":
        response = lab.client.post(
            f"/api/v1/admin/makerspace/{lab.home.pk}/qr-print-batches", {"title": "Blocked"}, format="json",
        )
    else:
        response = add_item(lab, labels, code)

    assert response.status_code == 400, response.data
    assert module in str(response.data["module"])
    assert response.data["module"].code == "invalid"
    assert state() == before


@pytest.mark.parametrize("denial", ["cross-tenant", "rbac"])
@pytest.mark.parametrize("route", ["generate", "asset-qr", "batch-create", "item-add"])
def test_http_scope_and_action_denials_do_not_mutate_rows(settings, denial, route):
    lab = qr_lab(settings)
    space = lab.other if denial == "cross-tenant" else lab.home
    target = product(lab, space=space)
    unit, code = asset(target), qr(lab, target)
    labels = QrPrintBatch.objects.create(makerspace=space, title="Scoped labels", created_by=lab.actor)
    if denial == "rbac":
        member = User.objects.create_user(username="qr-member", role=User.Role.REQUESTER)
        role = MakerspaceRole.objects.get(makerspace=space, slug="member")
        MakerspaceMembership.objects.create(makerspace=space, user=member, role="member", assigned_role=role)
        lab.client = jwt_client(member)
    before = state()

    if route == "generate":
        response = generate(lab, target)
    elif route == "asset-qr":
        response = lab.client.post(f"/api/v1/admin/assets/{unit.pk}/qr", {}, format="json")
    elif route == "batch-create":
        response = lab.client.post(
            f"/api/v1/admin/makerspace/{space.pk}/qr-print-batches", {"title": "Blocked"}, format="json",
        )
    else:
        response = add_item(lab, labels, code)

    assert response.status_code == (403 if route == "batch-create" else 404), response.data
    assert response.data["detail"].code == ("permission_denied" if route == "batch-create" else "not_found")
    assert state() == before


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("disable_first", [True, False], ids=["disable-wins", "print-wins"])
def test_canonical_module_toggle_serializes_with_printing_in_both_pg_winner_orders(settings, disable_first):
    lab = qr_lab(settings)
    labels = batch(lab)
    assert connection.vendor == "postgresql", "Real PostgreSQL is required"
    assert connection.get_autocommit() and not connection.in_atomic_block
    before = audit_ids()

    def disable():
        return uninstall_module(lab.home, "qr_print_batches", actor=lab.actor)

    def printing():
        try:
            result = mark_batch_printed(lab.actor, labels)
        except ValidationError as error:
            return "refused", error.detail
        return "printed", result.pk

    first, second, pids, captured, waited = policy_claim_race(
        disable if disable_first else printing, printing if disable_first else disable,
        pause_after=lambda sql: 'FROM "makerspaces_makerspace"' in sql and "FOR UPDATE" in sql,
        waiter_clause="FOR UPDATE",
    )

    # The helper sampled pg_stat_activity + pg_blocking_pids for this exact pair,
    # matched the in-flight SQL, and enforced finite lock/statement/join timeouts.
    assert len(set(pids.values())) == 2
    assert waited in [" ".join(sql.split()) for sql, _ in captured["second"]]
    disable_result, print_result = (first, second) if disable_first else (second, first)
    assert disable_result == ["qr_print_batches"]
    toggle_sql = [sql for sql, _ in captured["first" if disable_first else "second"]]
    assert any(sql.startswith('UPDATE "makerspaces_makerspace"') for sql in toggle_sql)
    print_sql = [sql for sql, _ in captured["second" if disable_first else "first"]]
    maker_lock = next(i for i, sql in enumerate(print_sql)
                      if 'FROM "makerspaces_makerspace"' in sql and "FOR UPDATE" in sql)
    batch_locks = [i for i, sql in enumerate(print_sql)
                   if 'FROM "operations_qrprintbatch"' in sql and "FOR UPDATE" in sql]
    lab.home.refresh_from_db()
    labels.refresh_from_db()
    assert "qr_print_batches" not in lab.home.enabled_modules
    events = new_events(before)
    toggle_event = events.get(action="makerspace.capabilities_changed")
    assert_event(toggle_event, lab, "makerspace.capabilities_changed", lab.home)
    if disable_first:
        assert print_result[0] == "refused"
        assert print_result[1]["module"].code == "invalid"
        assert "qr_print_batches" in str(print_result[1]["module"])
        assert not batch_locks  # Refusal precedes even the batch lock.
        assert labels.status == QrPrintBatch.Status.DRAFT and labels.printed_at is None
        assert events.count() == 1
    else:
        assert print_result == ("printed", labels.pk)
        assert len(batch_locks) == 1 and maker_lock < batch_locks[0]
        assert labels.status == QrPrintBatch.Status.PRINTED and labels.printed_at is not None
        assert events.count() == 2
        printed_event = events.get(action="qr_print_batch.printed")
        assert_event(printed_event, lab, "qr_print_batch.printed", labels)
        assert printed_event.pk < toggle_event.pk
