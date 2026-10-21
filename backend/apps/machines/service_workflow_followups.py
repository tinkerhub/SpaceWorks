"""Follow-up actions on machine service requests: manual payment and reprints."""

from django.db import transaction
from django.utils import timezone

from apps.machines.models import MachineServiceRequest
from apps.machines.service_errors import ServiceInvalidTransition
from apps.machines.service_workflow_helpers import (
    _assert_request_write_allowed,
    _audit_transition,
    _locked_request,
    _require_module,
)


def record_manual_payment(service_request, actor):
    with transaction.atomic():
        from apps.payments.models import Payment
        from apps.payments.reconciliation import mark_offline
        _assert_request_write_allowed(service_request)
        locked = _locked_request(service_request)
        _require_module(locked.makerspace)
        payment = Payment.objects.select_for_update().filter(
            makerspace_id=locked.makerspace_id, subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
            subject_id=locked.pk, status=Payment.Status.PENDING).first()
        if payment is None:
            raise ServiceInvalidTransition("Only pending payments can be recorded as paid.")
        mark_offline(payment, actor)
        _audit_transition(actor, locked, "manual_payment_recorded")
        return locked


def create_reprint(service_request, actor):
    """Create an accepted child request that retains the original attachment root."""
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        original = _locked_request(service_request)
        if original.status not in {MachineServiceRequest.Status.FAILED, MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.COLLECTED}:
            raise ServiceInvalidTransition("Only terminal service requests can be reprinted.")
        root = original.reprint_of or original
        child = MachineServiceRequest.objects.create(
            bucket=original.bucket, queue=original.queue, makerspace=original.makerspace, requester=original.requester, member=original.member,
            requester_name=original.requester_name, contact_email=original.contact_email, contact_phone=original.contact_phone,
            title=original.title, description=original.description, source_link=original.source_link,
            capability_payload=original.capability_payload, status=MachineServiceRequest.Status.ACCEPTED,
            assigned_machine=original.assigned_machine if original.bucket_id else None, accepted_by=actor,
            accepted_at=timezone.now(), estimated_minutes=original.estimated_minutes, planned_grams=original.planned_grams,
            reprint_of=root,
        )
        _audit_transition(actor, child, "reprint_created", extra={"reprint_of_id": root.pk})
        return child
