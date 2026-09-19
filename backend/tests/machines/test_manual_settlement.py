from decimal import Decimal
from uuid import uuid4

import pytest

from apps.accounts.transition_services import transition_walk_in_to_account
from apps.checkin.models import CheckinIdentity
from apps.machines import role_scope
from apps.machines.models import Machine, MachineServiceRequest, MachineType, MakerspaceMachineTypePricing
from apps.machines.service_errors import ServiceInvalidTransition
from apps.machines.service_payments import requires_counter_settlement
from apps.machines.service_reports import build_printer_service_report
from apps.machines.service_workflow import accept, collect, complete, record_manual_payment, start, submit
from apps.makerspaces.walk_in_services import create_person_record
from apps.payments.models import Payment
from tests.return_helpers import make_member, make_space


# Defined here rather than imported from tests/test_machine_service_api.py: importing one
# test module from another makes pytest collect it twice and the second collection trips
# its finalizer assertion.
def request_row(space, requester=None):
    requester = requester or make_member(f"manual-settle-{uuid4().hex[:8]}", space)
    kind = MachineType.objects.create(
        makerspace=space, slug=f"manual-settle-{uuid4().hex[:8]}", name="Settlement type"
    )
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Settlement machine")
    return submit(
        machine, requester, requester_name="Service member",
        contact_email=requester.email, contact_phone="123", title="Tune the machine",
    )


pytestmark = pytest.mark.django_db


def complete_request(row, actor, *, actual_minutes=3):
    accept(row, actor)
    start(row, actor, role_scope.EXEMPT, machine_id=row.assigned_machine_id)
    return complete(row, actor, actual_minutes=actual_minutes, consumptions=[])


def test_free_job_completion_is_never_collection_gated():
    space = make_space("manual-settlement-free")
    row = request_row(space)

    completed = complete_request(row, row.requester)

    assert (completed.payment_amount, completed.payment_status) == (None, "none")
    assert collect(completed, row.requester).status == MachineServiceRequest.Status.COLLECTED


def test_priced_job_creates_and_settles_an_authoritative_offline_payment():
    space = make_space("manual-settlement-priced")
    row = request_row(space)
    machine_type = row.assigned_machine.machine_type
    machine_type.capability_config = {
        "metering_unit": "minutes",
        "requires_booking": False,
    }
    machine_type.save(update_fields=["capability_config"])
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space,
        machine_type=machine_type,
        rate_per_unit="2.00",
        flat_fee="1.00",
        payment_enabled=True,
    )

    historic = (row.payment_amount, row.payment_status, row.paid_at)
    completed = complete_request(row, row.requester)
    payment = Payment.objects.get(
        makerspace=space,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=row.pk,
    )

    assert (payment.amount, payment.status) == (
        Decimal("7.00"),
        Payment.Status.PENDING,
    )
    assert (completed.payment_amount, completed.payment_status, completed.paid_at) == historic

    record_manual_payment(completed, row.requester)
    payment.refresh_from_db()
    completed.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert (completed.payment_amount, completed.payment_status, completed.paid_at) == historic
    assert collect(completed, row.requester).status == MachineServiceRequest.Status.COLLECTED


def test_collection_is_never_blocked_by_an_unpaid_charge_or_historic_columns():
    space = make_space("unpaid-collection")
    row = request_row(space)
    # Reach COMPLETED through the workflow: status is workflow-managed and the model
    # refuses a queryset update of it. Only the LEGACY money columns are then forced,
    # which is exactly the shape an upgraded install carries after
    # payments/0003_backfill_legacy_machine_payments copied them into a Payment row
    # without clearing them.
    row = complete_request(row, row.requester)
    MachineServiceRequest.objects.filter(pk=row.pk).update(
        payment_amount=Decimal("7.00"),
        payment_status="pending",
    )
    row.refresh_from_db()
    payment = Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=row.pk,
        member=row.requester,
        amount=Decimal("7.00"),
        currency="usd",
        status=Payment.Status.PENDING,
        created_by=row.requester,
    )

    collected = collect(row, row.requester)

    assert collected.status == MachineServiceRequest.Status.COLLECTED
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    assert (collected.payment_amount, collected.payment_status) == (
        Decimal("7.00"),
        "pending",
    )


def test_manual_payment_requires_an_authoritative_pending_payment():
    space = make_space("manual-settlement-status")
    row = request_row(space)
    MachineServiceRequest.objects.filter(pk=row.pk).update(
        payment_amount=Decimal("7.00"),
        payment_status="pending",
    )
    row.refresh_from_db()

    with pytest.raises(ServiceInvalidTransition, match="Only pending payments"):
        record_manual_payment(row, row.requester)


def test_manual_payment_uses_the_requests_completion_regime(monkeypatch):
    space = make_space("manual-settlement-regime-snapshot")
    row = request_row(space)
    machine_type = row.assigned_machine.machine_type
    machine_type.capability_config = {
        "metering_unit": "minutes",
        "requires_booking": False,
    }
    machine_type.save(update_fields=["capability_config"])
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space,
        machine_type=machine_type,
        rate_per_unit="2.00",
        payment_enabled=True,
    )
    online = {"enabled": False}
    monkeypatch.setattr(
        "apps.payments.availability.online_payments_enabled",
        lambda *_args: online["enabled"],
    )

    completed = complete_request(row, row.requester)
    payment = Payment.objects.get(subject_id=row.pk)
    assert payment.status == Payment.Status.PENDING
    assert (completed.payment_amount, completed.payment_status) == (None, "none")

    online["enabled"] = True
    record_manual_payment(completed, row.requester)

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert collect(completed, row.requester).status == MachineServiceRequest.Status.COLLECTED


def test_counter_settlement_requires_current_walk_in_state_in_the_same_space():
    space = make_space("counter-settlement-space")
    other = make_space("counter-settlement-other")
    staff = make_member("counter-settlement-staff", space)
    other_walk_in = create_person_record("Other-space walk-in")
    CheckinIdentity.objects.create(makerspace=other, user=other_walk_in, mid="other-443")
    assert not requires_counter_settlement(request_row(space, other_walk_in))

    walk_in = create_person_record("Current walk-in")
    CheckinIdentity.objects.create(makerspace=space, user=walk_in, mid="current-443")
    row = request_row(space, walk_in)
    assert requires_counter_settlement(row)

    transition_walk_in_to_account(walk_in, actor=staff)
    row.requester.refresh_from_db()
    assert not requires_counter_settlement(row)


def test_offline_payment_creation_failure_never_blocks_completion(monkeypatch):
    space = make_space("manual-settlement-failure")
    row = request_row(space)
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space,
        machine_type=row.assigned_machine.machine_type,
        flat_fee="5.00",
        payment_enabled=True,
    )
    monkeypatch.setattr(
        "apps.payments.offline_payments.create_offline_payment",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("ledger unavailable")),
    )

    completed = complete_request(row, row.requester)

    assert completed.status == MachineServiceRequest.Status.COMPLETED
    assert (completed.payment_amount, completed.payment_status, completed.paid_at) == (
        None,
        "none",
        None,
    )
    assert not Payment.objects.filter(subject_id=row.pk).exists()


def test_service_report_moves_manual_payment_from_due_to_paid(monkeypatch):
    space = make_space("manual-settlement-report")
    row = request_row(space)
    machine_type = row.assigned_machine.machine_type
    machine_type.capability_config = {
        "metering_unit": "minutes",
        "requires_booking": False,
    }
    machine_type.save(update_fields=["capability_config"])
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space,
        machine_type=machine_type,
        rate_per_unit="2.00",
        flat_fee="1.00",
        payment_enabled=True,
    )
    monkeypatch.setattr(
        "apps.machines.service_reports.resolve_global_printer_type",
        lambda: machine_type,
    )

    completed = complete_request(row, row.requester)
    report_row = build_printer_service_report(space.id).records[0]
    assert (report_row["payment_due"], report_row["payment_paid"]) == (
        Decimal("7.00"),
        Decimal("0.00"),
    )

    record_manual_payment(completed, row.requester)
    report_row = build_printer_service_report(space.id).records[0]
    assert (report_row["payment_due"], report_row["payment_paid"]) == (
        Decimal("0.00"),
        Decimal("7.00"),
    )


def test_service_report_ignores_stale_legacy_debt_when_payment_exists(monkeypatch):
    space = make_space("backfilled-settlement-report")
    row = request_row(space)
    row = complete_request(row, row.requester)
    machine_type = row.assigned_machine.machine_type
    monkeypatch.setattr(
        "apps.machines.service_reports.resolve_global_printer_type",
        lambda: machine_type,
    )
    # Migration 0003 copied this legacy debt into Payment without clearing it.
    MachineServiceRequest.objects.filter(pk=row.pk).update(
        payment_amount=Decimal("7.00"),
        payment_status="pending",
    )
    Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=row.pk,
        member=row.requester,
        amount=Decimal("7.00"),
        currency="usd",
        status=Payment.Status.PAID_OFFLINE,
        created_by=row.requester,
    )

    report_row = build_printer_service_report(space.id).records[0]

    assert (report_row["payment_due"], report_row["payment_paid"]) == (
        Decimal("0.00"),
        Decimal("7.00"),
    )
