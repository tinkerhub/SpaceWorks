"""Exact deleted-row inventory and typed object holder sites for each purge plan."""

import hashlib
import json

from django.apps import apps
from django.db import models
from django.db.models import Q

from apps.backup.object_ownership_registry import validate_object_reference_registry

from .module_purge_receipt_authority import ROLLBACK_FIELDS
from .purge_storage import PurgeStorageRefused


# These are the same scoped roots deleted by the existing collectors. Cascades
# are followed as row identities, never inferred from an app/module name.
ROOTS = {
    "events": (
        ("events.Event", "makerspace"), ("events.EventSeries", "makerspace"),
        ("events.EventCollaborator", "makerspace"),
        ("events.EventSeriesCollaborator", "makerspace"),
        ("events.EventCollaborator", "source_series_collaboration__makerspace"),
        ("events.EventCheckInEvent", "makerspace"),
        ("events.EventAttendanceCertificate", "registration__event__makerspace"),
        ("events.MemberCalendarFeed", "membership__makerspace"),
    ),
    "bookings": (("bookings.BookableSpace", "makerspace"),),
    "maintenance": (("maintenance.MaintenanceLog", "machine__makerspace"),
                    ("maintenance.MaintenanceSchedule", "machine__makerspace")),
    "procurement": (("procurement.ToBuyItem", "makerspace"),),
    "membership": (("makerspaces.MemberProfile", "membership__makerspace"),
                   ("makerspaces.MembershipRequest", "makerspace")),
    "notifications": (("notifications.Notification", "makerspace"),),
    "machine_service": (
        ("machines.ServiceRequestFile", "makerspace"),
        ("machines.MachineServiceRequest", "makerspace"),
        ("machines.MachineUsageEntry", "service_request__makerspace"),
        ("machines.MachineConsumableAdjustment", "service_request__makerspace"),
        ("machines.MachineConsumableAdjustment", "usage_entry__service_request__makerspace"),
        ("machines.ServiceRequestConsumption", "service_request__makerspace"),
        ("machines.ServiceBucket", "machine__makerspace"),
        ("machines.ServiceQueue", "makerspace"),
        ("machines.PrintingCutoverRepair", "makerspace"),
        ("machines.PrintingCutoverState", "makerspace"),
    ),
    "stocktake": (("operations.StocktakeSession", "makerspace"),),
    "qr_print_batches": (("operations.QrPrintBatch", "makerspace"),),
}


def graph_rows(space, plan):
    rows = {}

    def collect(model, query):
        label = model._meta.label
        existing = rows.setdefault(label, set())
        ids = set(query.values_list("pk", flat=True)) - existing
        existing.update(ids)
        if sum(len(values) for values in rows.values()) > 100000:
            raise PurgeStorageRefused("Module graph exceeds the bounded cleanup limit.")
        if not ids:
            return
        for relation in model._meta.related_objects:
            if getattr(relation.field.remote_field, "on_delete", None) is models.CASCADE:
                collect(relation.related_model, relation.related_model._base_manager.filter(
                    **{f"{relation.field.attname}__in": ids},
                ))

    if plan.key in {"telegram", "slack", "mattermost", "discord"}:
        model = apps.get_model("integrations.NotificationDestination")
        collect(model, model.objects.filter(makerspace=space, channel=plan.key))
    elif plan.key == "stock_transfers":
        model = apps.get_model("operations.StockTransfer")
        collect(model, model.objects.filter(Q(makerspace=space) | Q(source_makerspace=space)
                                           | Q(destination_makerspace=space)))
    else:
        if plan.key not in ROOTS:
            raise PurgeStorageRefused("Module graph collector is not explicitly classified.")
        for label, lookup in ROOTS[plan.key]:
            model = apps.get_model(label)
            collect(model, model._base_manager.filter(**{lookup: space}))
    from .module_purge_collectors_single_model import _cascade_model_labels

    # Match the collectors' declared source labels, including empty roots. The
    # derived indexes/rollups below do not widen generic provenance deletion.
    labels = set(rows)
    for label in tuple(labels):
        labels.update(_cascade_model_labels(apps.get_model(label)))
    # Non-relational indexes and generic provenance are part of the same commit.
    model = apps.get_model("encryption.PiiBlindIndex")
    collect(model, model.objects.filter(makerspace=space, model_label__in=plan.pii_labels))
    if plan.key == "machine_service":
        collect(model, model.objects.filter(
            makerspace=space, model_label="machines.MachineUsageEntry",
            object_id__in=rows.get("machines.MachineUsageEntry", set()),
        ))
    for label in ("operations.ReportMetricRollup", "operations.ReportRollupCursor"):
        model = apps.get_model(label)
        collect(model, model.objects.filter(makerspace=space, source_module=plan.key))
    model = apps.get_model("tenant_migration.ExternalTenantReference")
    collect(model, model.objects.filter(makerspace=space, target_model_label__in=labels))
    for label, ids in tuple(rows.items()):
        for relation in apps.get_model(label)._meta.related_objects:
            if getattr(relation.field.remote_field, "on_delete", None) is models.PROTECT:
                model = relation.related_model
                if model._base_manager.filter(**{f"{relation.field.attname}__in": ids}).exclude(
                    pk__in=rows.get(model._meta.label, set()),
                ).exists():
                    raise PurgeStorageRefused("A retained protected row prevents module graph deletion.")
    return rows


def holder_sites(rows):
    result = []
    for rule in validate_object_reference_registry():
        if rule.model_label not in rows:
            continue
        model = apps.get_model(rule.model_label)
        fields = ["pk", rule.field_name]
        if rule.bucket == "from_row":
            fields.append("bucket_kind")
        for row in model._base_manager.filter(pk__in=rows[rule.model_label]).values(*fields):
            key = row[rule.field_name]
            if key:
                kind = row["bucket_kind"] if rule.bucket == "from_row" else str(rule.bucket)
                result.append([rule.model_label, str(row["pk"]), rule.field_name, kind, str(key)])
    return sorted(result)


def rollback_bindings(space, module):
    model = apps.get_model("backup.RestoreRollbackObject")
    return [serialize_binding(row) for row in model.objects.filter(
        makerspace=space, module_key=module,
    ).order_by("pk").values(*ROLLBACK_FIELDS)]


def serialize_binding(row):
    return {key: value.isoformat() if key == "expires_at" else str(value) if key == "restore_id" else value
            for key, value in row.items()}


def snapshot(space, plan):
    from apps.document_storage_quota import proven_document_charge
    from apps.makerspaces import limits

    rows = graph_rows(space, plan)
    sites = holder_sites(rows)
    bindings = rollback_bindings(space, plan.key)
    for row in bindings:
        for field in ("source_key", "copy_key"):
            if row[field]:
                sites.append(["backup.RestoreRollbackObject", str(row["id"]), field,
                              row["bucket_kind"], row[field]])
    # Freeze charge eligibility and sizes without persisting PII or arbitrary JSON.
    facts = []
    fields = {
        "maintenance.MaintenanceLogDocument": ("object_key", "size_bytes"),
        "machines.ServiceRequestFile": ("object_key", "size_bytes", "service_request_id", "attached_at"),
        "events.EventAttendanceCertificate": ("object_key", "size_bytes", "rendered_at"),
    }
    for label, names in fields.items():
        if label in rows:
            for row in apps.get_model(label)._base_manager.filter(pk__in=rows[label]).order_by("pk").values("pk", *names):
                facts.append([label, {key: value.isoformat() if hasattr(value, "isoformat") else value
                                     for key, value in row.items()}])
    label = "procurement.ToBuyReceipt"
    # Self-host mode cannot settle a managed debit. Omitting new facts also
    # makes a pending managed receipt fail its frozen graph check after a switch.
    if label in rows and not limits.is_self_host():
        for document in apps.get_model(label)._base_manager.filter(
            pk__in=rows[label],
        ).select_related("to_buy_item").order_by("pk"):
            charge = proven_document_charge(document, makerspace_id=space.pk)
            if charge is not None:
                facts.append([label, {"pk": document.pk, "object_key": charge.object_key,
                                      "size_bytes": charge.size_bytes,
                                      "charge_event_uuid": charge.charge_event_uuid}])
    provenance = []
    if plan.key == "events":
        provenance = list(apps.get_model("events.EventRegistration").objects.filter(
            registered_via_makerspace=space,
        ).exclude(event__makerspace=space).order_by("pk").values_list("pk", "event_id"))
    payload = {"rows": {label: sorted(str(pk) for pk in ids) for label, ids in sorted(rows.items())},
               "sites": sorted(sites), "rollback": bindings, "charge_facts": facts,
               "provenance": provenance}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return digest, sorted(sites), bindings, facts
