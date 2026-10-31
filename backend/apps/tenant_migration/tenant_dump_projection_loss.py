"""Frozen, PII-free source ownership facts and independently derived D6 losses."""

from dataclasses import dataclass
from django.apps import apps
from django.db.models import Q

from .tenant_dump_errors import TenantDumpDispositionRefused, TenantDumpVerificationError
from .tenant_dump_cross_tenant_rules import CROSS_TENANT_EDGE_RULES, LOST_EDGE_REASON_CODES, TERMINAL_PAYMENT_STATUSES

# Deliberate total handler map, not generated from the registry being checked.
EDGE_HANDLERS = {
    ("events.EventCollaborator", "event"): "collaborator",
    ("events.EventCollaborator", "makerspace"): "collaborator",
    ("events.EventSeriesCollaborator", "series"): "series_collaborator",
    ("events.EventSeriesCollaborator", "makerspace"): "series_collaborator",
    ("operations.StockTransfer", "source_makerspace"): "transfer_pair",
    ("operations.StockTransfer", "destination_makerspace"): "transfer_pair",
    ("operations.StockTransfer", "source_container"): "transfer_pair",
    ("operations.StockTransfer", "destination_container"): "transfer_pair",
    ("events.EventRegistration", "registered_via_makerspace"): "registration_reset",
    ("events.EventRegistration", "payment_via_makerspace"): "registration_reset",
    ("payments.Payment", "via_makerspace"): "terminal_payment_reset",
    ("operations.StockTransferLine", "transfer"): "derived_transfer_line",
}
DERIVED_LINE_HANDLER = ("operations.StockTransferLine", "transfer")


@dataclass(frozen=True)
class SourceLossFacts:
    makerspace_id: int
    ownership_rows: tuple  # (model label, sorted primitive field/value tuple)


@dataclass(frozen=True)
class LossDecisions:
    ledger: tuple  # sorted primitive tuples, thawed only at the manifest boundary
    dropped: frozenset
    transfer_pairs: tuple  # (source PK, prefix, exact expected space, container)

    def manifest(self):
        return [dict(item) for item in self.ledger]


def validate_loss_handlers():
    expected = {
        "collaborator": "drop_row", "series_collaborator": "drop_row",
        "transfer_pair": "null_with_paired_container", "registration_reset": "null",
        "terminal_payment_reset": "clear_terminal_provider_binding",
    }
    if set(EDGE_HANDLERS) != set(CROSS_TENANT_EDGE_RULES) | {DERIVED_LINE_HANDLER} or any(
        str(rule.disposition) != expected[EDGE_HANDLERS[key]]
        for key, rule in CROSS_TENANT_EDGE_RULES.items() if key in EDGE_HANDLERS
    ):
        raise TenantDumpDispositionRefused(
            "A cross-tenant edge lacks a reviewed proof handler.",
            reason_code="unclassified_cross_tenant_proof_handler",
        )

    reasons = {
        ("operations.StockTransfer", "makerspace", "foreign_owned_transfer_dropped"),
        (*DERIVED_LINE_HANDLER, "foreign_owned_transfer_line_dropped"),
    }
    for (label, field), handler in EDGE_HANDLERS.items():
        reason = {
            "collaborator": "foreign_collaborator_dropped",
            "series_collaborator": "foreign_series_collaborator_dropped",
        }.get(handler)
        if handler == "transfer_pair":
            reason = ("foreign_counterparty_container_nulled" if field.endswith("_container")
                      else "foreign_counterparty_nulled")
        if reason:
            reasons.add((label, field, reason))
    if reasons != set(LOST_EDGE_REASON_CODES):
        raise TenantDumpVerificationError("The reviewed loss reason catalog and proof handlers differ.")


def capture_loss_facts(makerspace_id, *, using):
    """Read the immutable alias, including rows excluded from the projection."""
    validate_loss_handlers()
    owner = int(makerspace_id)
    facts = []

    def retain(label, rows):
        facts.extend((label, tuple(sorted(row.items()))) for row in rows)

    for label, parent in (("events.EventCollaborator", "event"),
                          ("events.EventSeriesCollaborator", "series")):
        host = f"{parent}__makerspace_id"
        retain(label, apps.get_model(label)._base_manager.using(using).filter(
            Q(**{host: owner}) | Q(makerspace_id=owner)
        ).values("id", host, "makerspace_id"))
    transfers = tuple(apps.get_model("operations.StockTransfer")._base_manager.using(using).filter(
        Q(makerspace_id=owner) | Q(source_makerspace_id=owner)
        | Q(destination_makerspace_id=owner)
    ).values("id", "makerspace_id", "source_makerspace_id", "source_container_id",
             "source_container__makerspace_id", "destination_makerspace_id",
             "destination_container_id", "destination_container__makerspace_id"))
    retain("operations.StockTransfer", transfers)
    retain("operations.StockTransferLine", apps.get_model(
        "operations.StockTransferLine"
    )._base_manager.using(using).filter(
        transfer_id__in=[row["id"] for row in transfers]
    ).values("id", "transfer_id", "transfer__makerspace_id",
             "product__makerspace_id", "asset__makerspace_id"))
    retain("payments.Payment", apps.get_model("payments.Payment")._base_manager.using(using).filter(
        makerspace_id=owner
    ).values("id", "status"))
    return SourceLossFacts(owner, tuple(sorted(facts, key=lambda item: (item[0], str(dict(item[1])["id"])))))


def derive_loss_decisions(facts):
    """Never consult the projection's supplied ledger or the erased target rows."""
    validate_loss_handlers()
    owner, losses, dropped, pairs = facts.makerspace_id, [], set(), []

    def loss(label, pk, field, reason):
        losses.append(dict(model_label=label, source_row_pk=pk,
                           field_name=field, reason_code=reason))

    for label, fields in facts.ownership_rows:
        row = dict(fields)
        pk = row["id"]
        if label in {"events.EventCollaborator", "events.EventSeriesCollaborator"}:
            series = label == "events.EventSeriesCollaborator"
            parent = "series" if series else "event"
            host, invited = row[f"{parent}__makerspace_id"], row["makerspace_id"]
            if host == owner != invited or invited == owner != host:
                loss(label, pk, "makerspace" if host == owner else parent,
                     "foreign_series_collaborator_dropped" if series else "foreign_collaborator_dropped")
            dropped.add((label, pk))  # local authority is dropped, without a foreign loss
        elif label == "operations.StockTransfer":
            if row["makerspace_id"] != owner:
                dropped.add((label, pk))
                loss(label, pk, "makerspace", "foreign_owned_transfer_dropped")
                continue
            for prefix in ("source", "destination"):
                space, container = row[f"{prefix}_makerspace_id"], row[f"{prefix}_container_id"]
                container_owner = row[f"{prefix}_container__makerspace_id"]
                foreign = space not in (None, owner) or container_owner not in (None, owner)
                if space not in (None, owner):
                    loss(label, pk, f"{prefix}_makerspace", "foreign_counterparty_nulled")
                if container is not None and container_owner != owner:
                    loss(label, pk, f"{prefix}_container", "foreign_counterparty_container_nulled")
                pairs.append((pk, prefix, None if foreign else space, None if foreign else container))
        elif label == "operations.StockTransferLine":
            if row["transfer__makerspace_id"] != owner or any(
                row[name] not in (None, owner)
                for name in ("product__makerspace_id", "asset__makerspace_id")
            ):
                dropped.add((label, pk))
                loss(label, pk, "transfer", "foreign_owned_transfer_line_dropped")
        elif label == "payments.Payment":
            if row["status"] not in TERMINAL_PAYMENT_STATUSES:
                raise TenantDumpDispositionRefused(
                    "A source payment is not terminal.", reason_code=(
                        "pending_payment" if row["status"] == "pending" else "unclassified_payment_status"
                    ),
                )
        else:
            raise TenantDumpVerificationError("An ownership fact has no proof handler.")
    key = lambda item: tuple(str(item[name]) for name in (
        "model_label", "source_row_pk", "field_name", "reason_code"
    ))
    return LossDecisions(tuple(tuple(sorted(item.items())) for item in sorted(losses, key=key)),
                         frozenset(dropped), tuple(sorted(pairs)))


def verify_loss_postconditions(using, facts, supplied_ledger):
    decisions = derive_loss_decisions(facts)
    if list(supplied_ledger) != decisions.manifest():
        raise TenantDumpVerificationError("The loss ledger differs from frozen source ownership.")
    for label, pk in decisions.dropped:
        if apps.get_model(label)._base_manager.using(using).filter(pk=pk).exists():
            raise TenantDumpVerificationError("A source-excluded row survived the projection.")
    Transfer = apps.get_model("operations.StockTransfer")
    for pk, prefix, space, container in decisions.transfer_pairs:
        actual = list(Transfer._base_manager.using(using).filter(pk=pk).values_list(
            f"{prefix}_makerspace_id", f"{prefix}_container_id"
        ))
        if actual != [(space, container)]:
            raise TenantDumpVerificationError("A transfer pair differs from its frozen source decision.")
