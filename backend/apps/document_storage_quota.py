"""Proven document debits and conservative, serialized one-shot settlement.

No provider I/O lives here. Callers own source/storage exclusion before row locks
and supply its verification callable explicitly when settling a deletion receipt.
"""

from django.db import transaction

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.document_storage_charge import (
    CHARGE_ACTIONS, PROOF_FIELDS, ChargeProof, canonical_row_time, canonical_uuid,
    charge_metadata, current_context, parse_charge, valid_target,
)
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace


RELEASE_ACTION = "storage.document_quota_released"


def _released(proof):
    # Any prior marker naming this event is conservative refusal, even if its
    # remaining metadata is malformed. The charge event UUID is the one-shot ID.
    return AuditLog.objects.filter(
        makerspace_id=proof.makerspace_id, action=RELEASE_ACTION,
        meta__charge_event_uuid=proof.charge_event_uuid,
    ).exists()


def _proven_charge(*, makerspace_id, target_type, target_id, object_key, row_created_at):
    if not valid_target(makerspace_id, target_type, target_id, object_key, row_created_at):
        return None
    context = current_context()
    if context is None:
        return None
    markers = []
    for event in AuditLog.objects.filter(
        makerspace_id=makerspace_id, target_type=target_type, target_id=target_id,
        action=CHARGE_ACTIONS[target_type],
    ).iterator():
        meta = event.meta
        if not isinstance(meta, dict) or not PROOF_FIELDS.intersection(meta):
            continue
        # A different canonical creation time belongs to another incarnation.
        # Missing/broken incarnation facts conflict rather than being ignored.
        row_time = meta.get("row_created_at")
        if canonical_row_time(row_time) and row_time != row_created_at:
            continue
        markers.append(event)
        if len(markers) > 1:
            return None
    if len(markers) != 1:
        return None
    proof = parse_charge(
        markers[0], makerspace_id=makerspace_id, target_type=target_type,
        target_id=target_id, object_key=object_key, row_created_at=row_created_at,
        context=context,
    )
    return proof if proof is not None and not _released(proof) else None


def proven_document_charge(document, *, makerspace_id):
    """Return ChargeProof or None for a live warranty document / ToBuyReceipt.

    Does not use declared row size or HEAD. Capture BEFORE Django clears the
    deleted instance's PK; reconciliation can use size_bytes while the row lives.
    """
    if document._meta.label_lower not in CHARGE_ACTIONS or document.pk is None:
        return None
    parent = (document.warranty if document._meta.label_lower == "warranty.warrantydocument"
              else document.to_buy_item)
    if parent.makerspace_id != makerspace_id or document.created_at is None:
        return None
    return _proven_charge(
        makerspace_id=makerspace_id, target_type=document._meta.label_lower,
        target_id=str(document.pk), object_key=document.object_key,
        row_created_at=document.created_at.isoformat(),
    )


def charge_by_event(*, makerspace_id, target_type, target_id, object_key,
                    size_bytes, row_created_at, charge_event_uuid):
    """Revalidate frozen facts after row deletion; return unreleased proof or None.

    Group 2 persists the canonical event UUID, string target PK, exact key,
    positive integer size and creation ISO string. No live document is required.
    Foreign/source-prefixed UUIDs and mismatched amounts never regain authority.
    """
    if (not canonical_uuid(charge_event_uuid)
            or type(size_bytes) is not int or size_bytes <= 0):
        return None
    proof = _proven_charge(
        makerspace_id=makerspace_id, target_type=target_type, target_id=target_id,
        object_key=object_key, row_created_at=row_created_at,
    )
    if (proof is None or proof.charge_event_uuid != charge_event_uuid
            or proof.size_bytes != size_bytes):
        return None
    return proof


def release_charge_once(proof: ChargeProof, *, verify):
    """Release a previously confirmed deletion, under HELD source/storage guards.

    verify() must validate that exclusion (raise on loss); no provider work may
    occur in it. Returns True only for a new refund+marker committed together.
    False is inert/refused/replayed/self-host. This is no S3 recovery queue:
    Ordinary callbacks require a nonempty DATA-version deletion receipt; module
    purge instead requires its validated frozen obligation and confirmed byte
    absence before atomic graph settlement.
    """
    if not isinstance(proof, ChargeProof) or limits.is_self_host():
        return False
    verify()
    with transaction.atomic():
        space = Makerspace.objects.select_for_update(no_key=True).get(pk=proof.makerspace_id)
        verify()
        current = charge_by_event(
            makerspace_id=proof.makerspace_id, target_type=proof.target_type,
            target_id=proof.target_id, object_key=proof.object_key,
            size_bytes=proof.size_bytes, row_created_at=proof.row_created_at,
            charge_event_uuid=proof.charge_event_uuid,
        )
        if current != proof or space.storage_bytes_used < proof.size_bytes:
            return False
        # Never rely on free_storage's clamp: a smaller balance refuses credit.
        limits.free_storage(space, proof.size_bytes)
        # A Model stub freezes the original PK; record() ignores non-Model targets.
        if proof.target_type == "warranty.warrantydocument":
            from apps.warranty.models import WarrantyDocument
            target = WarrantyDocument(pk=int(proof.target_id))
        else:
            from apps.procurement.models import ToBuyReceipt
            target = ToBuyReceipt(pk=int(proof.target_id))
        audit.record(
            None, "storage.document_quota_released", makerspace=space, target=target,
            meta={**proof.metadata(), "charge_event_uuid": proof.charge_event_uuid},
        )
        verify()
    return True
