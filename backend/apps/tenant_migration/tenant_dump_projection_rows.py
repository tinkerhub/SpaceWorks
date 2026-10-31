"""Complete physical row universes, including zero labels and foreign roots."""

from django.apps import apps
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_projection_expectations import projected_labels
from .tenant_dump_projection_bootstrap import read_model_rows


def expected_target_identities(expectations, baseline):
    identities = {label: tuple(pks) for label, pks in expectations.allowed_identities.items()}
    identities["machines.MachineType"] = tuple(sorted((
        *(pk for pk in identities["machines.MachineType"] if pk not in expectations.builtin_source_ids),
        *(row["id"] for row in baseline.rows["machines.MachineType"]),
    ), key=str))
    if len(set(identities["machines.MachineType"])) != len(identities["machines.MachineType"]):
        raise TenantDumpVerificationError("A custom MachineType collides with a target builtin identity.")
    return identities


def complete_projected_rows(using, expected_identities, expected_row_counts):
    labels = set(projected_labels())
    if set(expected_identities) != labels or set(expected_row_counts) != labels:
        raise TenantDumpVerificationError("The projected identity/count universe lacks exact reviewed labels.")
    rows = read_model_rows(using, labels)
    for label in sorted(labels):
        model = apps.get_model(label)
        actual = tuple(sorted((row[model._meta.pk.attname] for row in rows[label]), key=str))
        expected = tuple(expected_identities[label])
        if (expected != tuple(sorted(set(expected), key=str))
                or type(expected_row_counts[label]) is not int
                or expected_row_counts[label] != len(expected)
                or actual != expected):
            raise TenantDumpVerificationError("The complete projected table identity universe differs: " + label)
    return rows


def portable_content_rows(rows):
    # Global target builtin content has its own independent baseline proof. The raw
    # projected digest retains its historical custom/imported-row meaning.
    return {label: tuple(row for row in records if not (
        label == "machines.MachineType" and row["makerspace_id"] is None
    )) for label, records in rows.items()}
