"""Offline payment creation without resolving an online provider."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.audit import services as audit
from apps.payments.models import Payment


@transaction.atomic
def create_offline_payment(
    *, makerspace, subject_type, subject_id, member, amount, currency, created_by,
    subject_label="",
):
    """Create one pending counter-settlement charge for a domain subject.

    Counter settlement replaces ONLINE payment, not the `payments` module: with the
    module off no new charge is raised at all (an existing one stays settleable).
    """
    if amount <= 0:
        return None
    from apps.payments.availability import new_charges_allowed_locked

    if not new_charges_allowed_locked(makerspace):
        return None

    subject = {
        "makerspace": makerspace,
        "subject_type": subject_type,
        "subject_id": subject_id,
    }
    existing = Payment.objects.filter(**subject).first()
    if existing is not None:
        return existing

    try:
        # Keep the insert in its own savepoint: a concurrent winner of the unique
        # subject constraint must not poison the caller's workflow transaction.
        with transaction.atomic():
            payment = Payment.objects.create(
                **subject,
                member=member,
                subject_label=(subject_label or "")[:255],
                amount=amount,
                currency=currency.lower(),
                status=Payment.Status.PENDING,
                created_by=created_by,
            )
    except (IntegrityError, ValidationError):
        payment = Payment.objects.filter(**subject).first()
        if payment is None:
            raise
        return payment

    audit.record(
        created_by,
        "payment.created",
        makerspace=makerspace,
        target=payment,
        meta={
            "payment_id": payment.pk,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "amount": str(amount),
            "currency": payment.currency,
            "via_makerspace_id": None,
        },
    )
    return payment
