"""User-closure shape checks survive recomputed ledger and proof hashes."""

from copy import deepcopy
import hashlib

import pytest

from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_projection_proof import canonical_digest, validate_projection_record
from .x13_proof_helpers import protocol_record, rehash


def populated_closure_inner():
    inner = protocol_record()
    entries = []
    for pk in (17, 18):
        ref = hashlib.sha256(b"lane-d-user-v1\0" + inner["capture_id"].encode() + b"\0" + str(pk).encode()).hexdigest()
        entries.append(dict(user_ref=ref, emitted_user_pk=pk, reason_code="tenant_exclusive",
                            stub_schema_version=None, referencing_edges=[dict(
                                model_label="machines.ServiceRequestFile", source_row_pk=2, field_name="owner_user_id")]))
    inner["user_closure"]["included"] = sorted(entries, key=lambda entry: entry["user_ref"])
    bind_closure(inner)
    return inner


def bind_closure(inner):
    closure = inner["user_closure"]
    closure["sha256"] = canonical_digest({name: closure[name] for name in ("included", "stubbed", "refused")})
    inner["projection_verification"]["user_closure_sha256"] = closure["sha256"]
    rehash(inner["projection_verification"])


def test_valid_raw_owner_closure_entries_and_digest_are_accepted():
    inner = populated_closure_inner()
    assert validate_projection_record(inner).mode == "verified_v1"


@pytest.mark.parametrize("case", [
    "duplicate_user", "unsorted_users", "wrong_capture_ref", "wrong_reason", "wrong_stub_version",
    "duplicate_edge", "unsorted_edges", "unknown_model", "bad_field", "extra_entry_field", "refused",
])
def test_closure_exact_shape_binding_order_and_uniqueness_refuse_even_after_rehash(case):
    inner = populated_closure_inner()
    closure = inner["user_closure"]
    entries = closure["included"]
    entry = entries[0]
    edge = entry["referencing_edges"][0]
    if case == "duplicate_user":
        entries[1] = deepcopy(entry)
    elif case == "unsorted_users":
        entries.reverse()
    elif case == "wrong_capture_ref":
        entry["user_ref"] = "0" * 64
    elif case == "wrong_reason":
        entry["reason_code"] = "not_tenant_exclusive"
    elif case == "wrong_stub_version":
        entry["stub_schema_version"] = 1
    elif case == "duplicate_edge":
        entry["referencing_edges"].append(deepcopy(edge))
    elif case == "unsorted_edges":
        entry["referencing_edges"] = [dict(edge, source_row_pk=3), dict(edge, source_row_pk=2)]
    elif case == "unknown_model":
        edge["model_label"] = "unknown.Model"
    elif case == "bad_field":
        edge["field_name"] = "owner-user-id"
    elif case == "extra_entry_field":
        entry["email"] = "private@example.test"
    else:
        closure["refused"] = [entries.pop()]
    bind_closure(inner)
    with pytest.raises(TenantDumpVerificationError):
        validate_projection_record(inner)
