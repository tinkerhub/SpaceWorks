"""Original charge obligations are frozen before bytes and settled once with graph."""

import hashlib

from botocore.exceptions import ClientError
from django.apps import apps
from django.core.exceptions import ValidationError

from .module_purge_receipt_authority import procurement_identity
from .purge_storage import PurgeStorageRefused, bucket_name


def freeze_charges(sites, facts, bindings, s3, verify):
    from apps.document_storage_quota import proven_document_charge
    from apps.makerspaces import limits

    obligations, physical = [], set()
    typed_sites = {tuple(site) for site in sites}

    def add(identity, kind, key, size):
        if not key or type(size) is not int or not 0 <= size <= 9223372036854775807:
            raise PurgeStorageRefused("Original storage charge evidence is ambiguous.")
        pair = (bucket_name(kind), key)
        if pair in physical:
            raise PurgeStorageRefused("Duplicate physical charge obligations cannot be proven independent.")
        physical.add(pair)
        obligations.append([identity, kind, key, size])

    public = sorted({(kind, key) for label, pk, field, kind, key in sites
                     if kind == "public_image" and label != "backup.RestoreRollbackObject"})
    for kind, key in public:
        if (bucket_name(kind), key) in physical:
            continue
        verify()
        try:
            head = s3.head_object(Bucket=bucket_name(kind), Key=key)
            size = head.get("ContentLength")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise PurgeStorageRefused("Storage cannot prove the original public charge size.") from exc
            size = 0  # Missing accepted bytes carry no invented refund.
        except Exception as exc:
            raise PurgeStorageRefused("Storage cannot prove the original public charge size.") from exc
        identity = hashlib.sha256(f"{bucket_name(kind)}\0{key}".encode()).hexdigest()
        add(f"public:{identity}", kind, key, size)
    for label, row in facts:
        key = row["object_key"]
        if not key:
            continue
        if label == "maintenance.MaintenanceLogDocument":
            add(f"maintenance:{row['pk']}", "private", key, row["size_bytes"])
        elif (label == "machines.ServiceRequestFile" and row["service_request_id"] is not None
              and row["attached_at"] is not None):
            add(f"service:{row['pk']}", "private", key, row["size_bytes"])
        elif label == "events.EventAttendanceCertificate" and row["rendered_at"] is not None:
            add(f"certificate:{row['pk']}", "private", key, row["size_bytes"])
        elif label == "procurement.ToBuyReceipt":
            if limits.is_self_host():
                raise PurgeStorageRefused("Managed document accounting changed before intent.")
            identity = f"procurement:{row['pk']}:{row['charge_event_uuid']}"
            procurement_identity(identity)
            if (label, str(row["pk"]), "object_key", "private", key) not in typed_sites:
                raise PurgeStorageRefused("Procurement charge has no exact typed holder.")
            verify()
            document = apps.get_model(label)._base_manager.filter(
                pk=row["pk"], object_key=key,
            ).select_related("to_buy_item").first()
            charge = None if document is None else proven_document_charge(
                document, makerspace_id=document.to_buy_item.makerspace_id,
            )
            if (charge is None or charge.charge_event_uuid != row["charge_event_uuid"]
                    or charge.size_bytes != row["size_bytes"] or charge.object_key != key
                    or charge.target_type != "procurement.tobuyreceipt"
                    or charge.target_id != str(row["pk"])):
                raise PurgeStorageRefused("Original procurement charge changed before intent.")
            add(identity, "private", key, charge.size_bytes)
    for row in bindings:
        if row["copy_key"]:
            if row["copy_key"] != f"rollback/{row['restore_id']}/{row['bucket_kind']}/{row['source_key']}":
                raise PurgeStorageRefused("Rollback copy identity cannot be proven.")
            add(f"rollback:{row['id']}", row["bucket_kind"], row["copy_key"], row["size_bytes"])
        elif row["size_bytes"]:
            raise PurgeStorageRefused("Rollback charge has no independent copy locator.")
    # Legacy/unproven procurement and rowless namespaces carry no invented credit.
    return sorted(obligations)


def settle(space, receipt, *, verify):
    from apps.audit.models import AuditLog
    from apps.backup.models import RestoreRollbackObject
    from apps.document_storage_quota import charge_by_event, release_charge_once
    from apps.makerspaces import limits
    from .module_purge_graph import rollback_bindings

    verify()
    if rollback_bindings(space, receipt.module_key) != receipt.rollback_bindings:
        raise ValidationError("Frozen rollback ownership changed; settlement refused.")
    ids = [row["id"] for row in receipt.rollback_bindings]
    RestoreRollbackObject.objects.filter(pk__in=ids).delete()
    amount = sum(row[3] for row in receipt.charge_obligations if not row[0].startswith("procurement:"))
    if amount:
        # Never swallow accounting errors: graph/checkpoint/audit must roll back too.
        limits.free_storage(space, amount)
    for identity, kind, key, size in receipt.charge_obligations:
        if not identity.startswith("procurement:"):
            continue
        pk, event_uuid = procurement_identity(identity)
        # The row has gone; its immutable event preserves the exact ISO string.
        event = AuditLog.objects.filter(
            event_uuid=event_uuid, makerspace_id=space.pk,
            target_type="procurement.tobuyreceipt", target_id=pk,
            action="procurement.receipt_added",
        ).first()
        if kind != "private" or event is None or not isinstance(event.meta, dict):
            raise ValidationError("Frozen procurement charge provenance is missing.")
        proof = charge_by_event(
            makerspace_id=space.pk, target_type="procurement.tobuyreceipt", target_id=pk,
            object_key=key, size_bytes=size, row_created_at=event.meta.get("row_created_at"),
            charge_event_uuid=event_uuid,
        )
        if proof is None or release_charge_once(proof, verify=verify) is not True:
            raise ValidationError("Frozen procurement charge could not be settled exactly once.")
