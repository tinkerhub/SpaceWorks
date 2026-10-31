"""Real immutable alias versus changed live clients, with a SQL credential allowlist."""

import hashlib
import json

import pytest

from apps.apiclients.models import ApiClient
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.tenant_dump_api_clients import build_source_client_catalog
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from tests.tenant_migration.x12_real_producer_helpers import freeze_client_source
from tests.tenant_migration.x13_proof_helpers import CAPTURE, DEPLOYMENT


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("allow_projection_databases")
def test_immutable_alias_catalog_preserves_exact_tenant_metadata_without_credential_queries(tmp_path, settings):
    settings.PII_ENCRYPTION_ENABLED = False
    frozen = freeze_client_source(tmp_path / "source")
    catalog = frozen.catalog
    assert catalog["version"] == 1
    assert catalog["capture_id"] == str(frozen.capture.pk)
    assert catalog["source_deployment_id"] == frozen.capture.source_deployment_identity["deployment_id"]
    assert catalog["source_makerspace_id"] == frozen.space.pk
    entries = catalog["entries"]
    assert {row["label"] for row in entries} == {"Frozen active", "Frozen inactive", "Frozen invalid"}
    assert len(entries) == 3
    by_label = {row["label"]: row for row in entries}
    assert by_label["Frozen inactive"]["is_active"] is False
    assert by_label["Frozen inactive"]["ineligibility_reason"] == "inactive"
    assert by_label["Frozen invalid"]["stored_scopes"] == ["unknown:scope"]
    assert by_label["Frozen invalid"]["ineligibility_reason"] == "invalid_scopes"
    assert by_label["Frozen active"]["eligible_for_reissue"] is True
    assert all(row["stored_origins"] == ["https://source.example.test"] for row in entries)
    refs = [hashlib.sha256(
        f"lane-d-source-client-v1\0{frozen.capture.pk}\0{catalog['source_deployment_id']}\0{frozen.space.pk}\0{client.pk}".encode()
    ).hexdigest() for client, _ in frozen.own]
    assert [row["source_client_ref"] for row in entries] == sorted(refs)
    assert set(ApiClient.objects.filter(makerspace=frozen.space).values_list("label", flat=True)) == {"Changed live row"}
    assert len(frozen.queries) == 1
    sql = frozen.queries[0].lower()
    for forbidden in ("client_id", "secret_encrypted", "previous_secret", "created_by", "last_seen_ip"):
        assert forbidden not in sql
    encoded = json.dumps(catalog).encode()
    for client, secret in frozen.own:
        assert client.client_id.encode() not in encoded
        assert secret.encode() not in encoded
        assert bytes(client.secret_encrypted) not in encoded
    for forbidden in (b"Global excluded", b"Foreign excluded", b"Changed live row", b"live.example.test"):
        assert forbidden not in encoded


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("label", "control\x01metadata"), ("label", "control\x7fmetadata"), ("label", "control\x85metadata"), ("label", "control\x9fmetadata"),
    ("scopes", [["public:read"]]), ("scopes", ["s" * 2049]),
    ("allowed_origins", ["https://user:private-secret@example.test"]),
])
def test_source_producer_refuses_unsafe_raw_metadata_without_echoing_bytes(field, value):
    space = Makerspace.objects.create(name="X12 unsafe", slug="x12-unsafe")
    client, _ = ApiClient.issue(label="Before corruption", scopes=["public:read"], makerspace=space,
                                allowed_origins=["https://source.example.test"])
    ApiClient.objects.filter(pk=client.pk).update(**{field: value})
    with pytest.raises(TenantDumpVerificationError) as refused:
        build_source_client_catalog(CAPTURE, DEPLOYMENT, space)
    assert "private-secret" not in str(refused.value)
    assert "control" not in str(refused.value)
