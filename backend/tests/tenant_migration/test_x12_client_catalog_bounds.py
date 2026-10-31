"""Exact catalog identities, raw metadata bounds, deterministic classification."""


import pytest

from apps.tenant_migration import tenant_client_catalog as contracts
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused
from tests.tenant_migration.x12_selected_test_helpers import catalog, catalog_entry


def redigest(document):
    for entry in document["entries"]:
        entry["source_entry_sha256"] = contracts._digest({
            key: value for key, value in entry.items() if key != "source_entry_sha256"
        })
    document["sha256"] = contracts._digest(document["entries"])


@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", 2), ("capture_id", "not-a-uuid"),
    ("capture_id", "568267BE-8127-4DA6-810D-D3C2B90C6FC0"),
    ("source_deployment_id", {"deployment_id": "ignored"}),
    ("source_deployment_id", "opaque-deployment"),
    ("source_makerspace_id", True), ("source_makerspace_id", 0),
    ("sha256", "A" * 64), ("entries", {}),
])
def test_catalog_header_is_exact_canonical_version_uuid_and_digest(field, value):
    document = catalog(catalog_entry())
    document[field] = value
    with pytest.raises(TenantRestoreRefused):
        contracts.validate_client_catalog(document)


@pytest.mark.parametrize("case", ["missing", "extra", "entry_extra", "entry_missing", "entry_hash", "catalog_hash", "duplicate", "order"])
def test_catalog_allowlist_order_and_both_digests_are_enforced(case):
    document = catalog(catalog_entry(), catalog_entry(source_client_ref="2" * 64))
    if case == "missing":
        document.pop("source_deployment_id")
    elif case == "extra":
        document["approved"] = True
    elif case == "entry_extra":
        document["entries"][0]["client_id"] = "never allowed"
    elif case == "entry_missing":
        document["entries"][0].pop("is_active")
    elif case == "entry_hash":
        document["entries"][0]["label"] = "altered"
    elif case == "catalog_hash":
        document["sha256"] = "0" * 64
    elif case == "duplicate":
        document["entries"] *= 2
    else:
        document["entries"].reverse()
    with pytest.raises(TenantRestoreRefused):
        contracts.validate_client_catalog(document)


@pytest.mark.parametrize("field,value", [
    ("label", "private\x00label"), ("label", "control\x7fmetadata"), ("label", "control\x85metadata"), ("label", "control\x9fmetadata"), ("label", "\ud800"), ("label", "L" * 201),
    ("is_active", 1), ("eligible_for_reissue", 1),
    ("stored_scopes", ["public:read\n"]), ("stored_scopes", ["\udfff"]),
    ("stored_scopes", [["public:read"]]), ("stored_scopes", {"scope": "public:read"}),
    ("stored_scopes", ["x" * 2049]), ("stored_scopes", ["public:read"] * 129),
    ("stored_origins", ["https://user:password@example.test"]),
    ("stored_origins", ["https://example.test\x1f"]),
])
def test_unsafe_metadata_refuses_even_with_recomputed_digests(field, value):
    document = catalog(catalog_entry())
    document["entries"][0][field] = value
    # Surrogates cannot be safely hashed either; retain a syntactically valid old digest.
    try:
        redigest(document)
    except UnicodeError:
        pass
    with pytest.raises(TenantRestoreRefused) as refused:
        contracts.validate_client_catalog(document)
    assert "password" not in str(refused.value)
    assert "private" not in str(refused.value)


@pytest.mark.parametrize("changes,reason", [
    ({"is_active": False}, "inactive"),
    ({"label": ""}, "invalid_label"),
    ({"client_type": "unknown"}, "invalid_client_type"),
    ({"rate_limit_tier": "unknown"}, "invalid_rate_limit_tier"),
    ({"stored_scopes": ["unknown:scope"]}, "invalid_scopes"),
    ({"stored_scopes": True}, "invalid_scopes"),
    ({"stored_origins": ["https://example.test/path"]}, "invalid_origins"),
    ({"stored_origins": False}, "invalid_origins"),
])
def test_invalid_representable_metadata_is_retained_with_fixed_reason(changes, reason):
    entry = catalog_entry(**changes)
    document = catalog(entry)
    assert contracts.validate_client_catalog(document) == document
    retained = document["entries"][0]
    for field, value in changes.items():
        assert retained[field] == value
    assert retained["eligible_for_reissue"] is False
    assert retained["ineligibility_reason"] == reason


def test_valid_empty_catalog_and_independent_identity_bindings():
    document = catalog()
    assert contracts.validate_client_catalog(document) == document
    for field, value in (("capture_id", "00000000-0000-0000-0000-000000000001"),
                         ("source_deployment_id", "00000000-0000-0000-0000-000000000002"),
                         ("source_makerspace_id", 8)):
        with pytest.raises(TenantRestoreRefused):
            contracts.validate_client_catalog(document, **{field: value})


def test_catalog_row_and_serialized_byte_budgets_are_enforced(monkeypatch):
    document = catalog(catalog_entry())
    monkeypatch.setattr(contracts, "MAX_CLIENTS", 0)
    with pytest.raises(TenantRestoreRefused):
        contracts.validate_client_catalog(document)
    monkeypatch.setattr(contracts, "MAX_CLIENTS", 10000)
    monkeypatch.setattr(contracts, "MAX_CATALOG_BYTES", 1)
    with pytest.raises(TenantRestoreRefused):
        contracts.validate_client_catalog(document)
