"""Closed, field-specific object holders; module names never infer ownership."""

import re

SITES = {
    "events": {
        ("events.Event", "image_key", "public_image"),
        ("events.EventSeries", "image_key", "public_image"),
        ("events.EventAttendanceCertificate", "object_key", "private"),
    },
    "bookings": {("bookings.BookableSpace", "image_key", "public_image")},
    "membership": {("makerspaces.MemberProfile", "avatar_key", "public_image"),
                   ("makerspaces.MemberProject", "image_key", "public_image")},
    "maintenance": {("maintenance.MaintenanceLogDocument", "object_key", "private")},
    "procurement": {("procurement.ToBuyReceipt", "object_key", "private")},
    "machine_service": {("machines.ServiceRequestFile", "object_key", "private")},
}


def validate_sites(receipt):
    from .module_purge_receipt_authority import procurement_identity, refuse

    allowed = SITES.get(receipt.module_key, set())
    bindings = {str(row["id"]): row for row in receipt.rollback_bindings}
    exact = {tuple(pair) for pair in receipt.exact_keys}
    seen = set()
    for label, pk, field, kind, key in receipt.holder_sites:
        identity = (label, pk, field)
        if (identity in seen or key.startswith("staging/")
                or (kind, f"staging/{key}") not in exact):
            refuse()
        seen.add(identity)
        if label == "backup.RestoreRollbackObject":
            row = bindings.get(pk)
            if (row is None or field not in {"copy_key", "source_key"}
                    or row[field] != key or row["bucket_kind"] != kind):
                refuse()
        elif (label, field, kind) not in allowed:
            refuse()
        if not pk.isascii() or not pk.isdecimal() or pk[0] == "0" or int(pk) > 9223372036854775807:
            refuse()
    expected = {(str(row["id"]), field, row["bucket_kind"], row[field])
                for row in receipt.rollback_bindings for field in ("source_key", "copy_key") if row[field]}
    actual = {(pk, field, kind, key) for label, pk, field, kind, key in receipt.holder_sites
              if label == "backup.RestoreRollbackObject"}
    if expected != actual:
        refuse()
    obligations = {}
    typed_sites = {tuple(site) for site in receipt.holder_sites}
    site_ids = {(label, pk, kind, key) for label, pk, field, kind, key in receipt.holder_sites}
    types = {"maintenance": "maintenance.MaintenanceLogDocument", "service": "machines.ServiceRequestFile",
             "certificate": "events.EventAttendanceCertificate", "rollback": "backup.RestoreRollbackObject"}
    for identity, kind, key, size in receipt.charge_obligations:
        category, pk = identity.split(":", 1)
        if category == "public":
            if kind != "public_image" or not re.fullmatch(r"[0-9a-f]{64}", pk) or not any(k == kind and value == key and label != "backup.RestoreRollbackObject"
                       for label, _pk, k, value in site_ids):
                refuse()
        elif category == "procurement":
            pk, _event_uuid = procurement_identity(identity)
            if (("procurement.ToBuyReceipt", pk, "object_key", "private", key) not in typed_sites
                    or kind != "private" or size <= 0):
                refuse()
        elif (types[category], pk, kind, key) not in site_ids:
            refuse()
        if category == "rollback":
            row = bindings.get(pk)
            if row is None or row["copy_key"] != key or row["size_bytes"] != size:
                refuse()
        # A copy and its source must be different physical locators; they are
        # independent obligations, never two credits for one charged physical key.
        physical = (receipt.storage_origins[kind], key)
        if physical in obligations:
            refuse()
        obligations[physical] = identity
