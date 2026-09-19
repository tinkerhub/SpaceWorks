"""Machine-service charging boundary; payment failures never affect fulfilment."""

from django.db import transaction

from apps.machines.models import MakerspaceMachineTypePricing
from apps.machines.service_pricing import compute_amount
from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.services import create_checkout, create_payment


def requires_counter_settlement(service_request):
    requester = service_request.requester
    # A check-in principal is a credentialless walk-in: it has no account and no way
    # to reach an online checkout, so its debt must remain payable at the counter.
    if requester is None or not requester.is_walk_in:
        return False

    from apps.checkin.models import CheckinIdentity

    return CheckinIdentity.objects.filter(
        user_id=requester.pk,
        makerspace_id=service_request.makerspace_id,
    ).exists()


def create_for_completed_request(service_request, actor):
    try:
        with transaction.atomic():
            machine_type = service_request.assigned_machine.machine_type
            if requires_counter_settlement(service_request) or not online_payments_enabled(
                service_request.makerspace, "machines"
            ):
                return None
            pricing = MakerspaceMachineTypePricing.objects.filter(
                makerspace=service_request.makerspace, machine_type=machine_type, payment_enabled=True
            ).first()
            if pricing is None:
                return None
            amount = compute_amount(service_request)
            if amount <= 0:
                return None
            currency = MakerspacePaymentSettings.for_makerspace(service_request.makerspace).default_currency
            payment = create_payment(
                makerspace=service_request.makerspace,
                subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
                subject_id=service_request.pk,
                member=service_request.member or service_request.requester,
                amount=amount,
                currency=currency,
                created_by=actor,
                # NO subject_label. `title` is free text a public member types, so it can
                # contain their name, email or phone -- and a snapshot outlives the
                # `machine_service` purge that exists to destroy exactly that. Leaving it
                # blank keeps the live lookup (which still shows the title while the request
                # exists) and degrades to the generic display once the request is gone.
                # The other three subjects snapshot staff-authored or literal text instead.
            )
    except Exception:
        return None
    try:
        create_checkout(payment)
    except Exception:
        pass
    return payment
