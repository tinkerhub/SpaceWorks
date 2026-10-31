"""Literal semantic-location hashes, independently read from immutable source rows."""

import hashlib
import json
from django.apps import apps

from apps.data_export.references import RAW_USER_REFERENCE_FIELDS, SEMANTIC_REFERENCES, USER_EDGES
from apps.data_export.types import Fidelity, SemanticUserRef, SourceLocalProvenance
from .tenant_dump_catalog import FIELD_POLICIES
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_raw import _RawDigestEncoder, _reset_value
from .tenant_dump_types import AuthorityDisposition, AuthorityField


def value_sha256(value):
    return hashlib.sha256(json.dumps(value, cls=_RawDigestEncoder, ensure_ascii=False,
                                    sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def semantic_locations():
    locations = {}
    for (fidelity, label, location), decisions in SEMANTIC_REFERENCES.items():
        if fidelity is not Fidelity.PORTABLE:
            continue
        if any(isinstance(decision, SemanticUserRef) and decision.included for decision in decisions):
            raise TenantDumpVerificationError("An included semantic user reference lacks a Lane D handler.")
        if not all(isinstance(decision, SourceLocalProvenance) for decision in decisions):
            raise TenantDumpVerificationError("An unreviewed semantic disposition cannot travel.")
        fields = (location.removeprefix("json:"),) if location.startswith("json:") else tuple(location.split("+"))
        locations[(label, location)] = fields
    # Raw live user identities are intentionally checked by USER_EDGES/closure, not
    # converted into inert semantic snapshots. Fence actors belong to bootstrap only.
    for label, field in RAW_USER_REFERENCE_FIELDS:
        edge = USER_EDGES.get((Fidelity.PORTABLE, label, field))
        if edge is None or not edge.raw:
            raise TenantDumpVerificationError("A raw user reference lacks its reviewed closure edge.")
        if label == "machines.ServiceRequestFile" and not edge.included:
            raise TenantDumpVerificationError("The service-file owner lost its live closure edge.")
        if label.startswith("encryption.Pii") and edge.included:
            raise TenantDumpVerificationError("Target fence actors must not become imported user authority.")
    from .tenant_dump_projection_schema import PROJECTED_LABELS, SEMANTIC_LOCATIONS
    if {key for key in locations if key[0] in PROJECTED_LABELS} != SEMANTIC_LOCATIONS:
        raise TenantDumpVerificationError("The reviewed semantic proof locations drifted.")
    return locations


def _expected_value(model, field_name, source):
    field = model._meta.get_field(field_name)
    policy = FIELD_POLICIES[(model._meta.label, field.name)]
    dispositions = policy.dispositions if isinstance(policy, AuthorityField) else (AuthorityDisposition.PRESERVE,)
    if AuthorityDisposition.PRESERVE in dispositions:
        return "preserve", source[field.attname]
    if len(dispositions) != 1:
        raise TenantDumpVerificationError("A semantic location needs an explicit conditional policy.")
    disposition = dispositions[0]
    if disposition not in {AuthorityDisposition.RESET, AuthorityDisposition.DROP}:
        raise TenantDumpVerificationError("An unknown semantic field policy cannot travel.")
    # This is the reviewed reset/default policy, not sanitizer output.
    return str(disposition), _reset_value(model, field, source)


def extract_semantic_references(rows, *, expected):
    result = []
    for (label, location), fields in sorted(semantic_locations().items()):
        model = apps.get_model(label)
        for row in rows.get(label, ()):
            selected = [_expected_value(model, field, row) for field in fields]
            dispositions = {item[0] for item in selected}
            if len(dispositions) != 1:
                raise TenantDumpVerificationError("A semantic location has mixed field dispositions.")
            disposition = next(iter(dispositions))
            from .tenant_dump_projection_schema import semantic_disposition
            if disposition != semantic_disposition(label, location):
                raise TenantDumpVerificationError("The reviewed semantic proof disposition drifted.")
            values = [item[1] if expected else row[model._meta.get_field(field).attname]
                      for field, item in zip(fields, selected, strict=True)]
            result.append(dict(model_label=label, source_row_pk=row[model._meta.pk.attname],
                               location=location, disposition=disposition,
                               value_sha256=value_sha256(values[0] if len(values) == 1 else values)))
    return sorted(result, key=semantic_key)


def semantic_key(item):
    return item["model_label"], str(item["source_row_pk"]), item["location"]


def verify_semantic_references(rows, expected, *, resolved_pks):
    # Only actual FK builtin mappings affect which physical row is read. Literal
    # polymorphic IDs and JSON snapshots are never looked up or remapped.
    source_ids = {(label, pk): source_pk for (label, source_pk), pk in resolved_pks.items()}
    normalized = {}
    for label, records in rows.items():
        model = apps.get_model(label)
        pk_name = model._meta.pk.attname
        normalized[label] = tuple(dict(row, **{
            pk_name: source_ids.get((label, row[pk_name]), row[pk_name])
        }) for row in records if not (
            label == "machines.MachineType" and row["makerspace_id"] is None
            and (label, row[pk_name]) not in source_ids
        ))
    actual = extract_semantic_references(normalized, expected=False)
    if actual != list(expected):
        raise TenantDumpVerificationError("Semantic location values differ from the frozen source policy.")
