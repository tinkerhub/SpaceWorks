"""Repository integration, not a host/provider drill: real PG, age and Django writer."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from rest_framework.exceptions import ValidationError

from apps.admin_api.api_client_serializers_clients import ApiClientSerializer
from apps.apiclients.models import ApiClient, ApiClientImportApproval
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.host_credential_delivery import CredentialDeliveryStore
from apps.tenant_migration.tenant_dump_database import empty_verification_database, restore_scratch_dump
from apps.tenant_migration.tenant_dump_lineage import DERIVATION_POLICY_VERSION
from apps.tenant_migration.tenant_restore_api_clients import provenance_digest, reissue_approved_client
from apps.tenant_migration.tenant_restore_artifact_admission import read_selected_artifact_context
from tests.tenant_migration.x12_real_producer_helpers import freeze_client_source, produce_encrypted_source
from tests.tenant_migration.x12_restore_test_helpers import RestoreScenario
from tests.tenant_migration.x12_selected_test_helpers import approvals_for, sha

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("allow_projection_databases")]


def test_real_source_producer_selected_reader_proof_approval_and_fresh_client_service(tmp_path, settings):
    settings.PII_ENCRYPTION_ENABLED = False
    frozen = freeze_client_source(tmp_path / "producer")
    produced = produce_encrypted_source(frozen)
    assert DERIVATION_POLICY_VERSION == 6
    assert produced.outer["version"] == 2
    context = read_selected_artifact_context(produced.inputs, produced.adapter)
    assert context.projection_mode == "verified_v1"
    assert context.projection_proof_sha256 == produced.inner["projection_verification"]["sha256"]
    assert context.database_member_sha256 == sha((produced.extracted / "database.dump").read_bytes())
    assert context.inner_manifest_sha256 == sha(produced.emitted)
    assert produced.inner["api_client_catalog"] == frozen.catalog
    assert {entry["label"] for entry in produced.inner["api_client_catalog"]["entries"]} == {
        "Frozen active", "Frozen inactive", "Frozen invalid",
    }
    assert b"source-secret" not in produced.emitted
    assert b"Frozen active" not in produced.path.read_bytes()
    assert b"source.example.test" not in produced.path.read_bytes()
    # A configured repository bridge uses the real test Django DB as its target;
    # it neither impersonates a live host nor replaces the default DB connection.
    target_space = Makerspace.objects.create(name="X12 target", slug="x12-target",
                                             resource_limit_overrides={"api_clients": 0})
    settings.PLATFORM_DOMAIN_SUFFIX = "managed.example.test"
    scenario = RestoreScenario(tmp_path / "target", produced.adapter)
    scenario.inputs = produced.inputs
    document = approvals_for(produced)
    document["approvals"] = [record for record in document["approvals"] if record["label"] == "Frozen active"]
    assert len(document["approvals"]) == 1
    scenario.inputs = replace(scenario.inputs, api_client_approvals=document)
    store = CredentialDeliveryStore(tmp_path / "delivery", require_root_owned=False)
    calls, restored = [], []
    def consume(_sibling, path):
        assert Path(path) != produced.extracted / "database.dump"
        assert sha(Path(path).read_bytes()) == context.database_member_sha256
        with empty_verification_database(frozen.space.pk, uuid4()) as (using, name):
            restore_scratch_dump(path, name)
            assert Makerspace.objects.using(using).filter(pk=frozen.space.pk).exists()
            assert not ApiClient.objects.using(using).exists()
            assert Path(path).exists()  # snapshot lifetime includes actual pg_restore
        restored.append(Path(path))
    scenario.database.restore = consume
    def bridge(sibling, inputs, *, approved_records, source_catalog_sha256, approval_records_sha256):
        assert source_catalog_sha256 == frozen.catalog["sha256"]
        assert len(approved_records) == 1
        assert isinstance(approved_records[0]["target_scopes"], tuple)
        calls.append(approved_records[0])
        client = reissue_approved_client(makerspace=target_space, record=approved_records[0], delivery_store=store)
        return {"client_secret": client.get_secret(), "client_id": client.client_id}
    scenario.target.reissue_validated_api_clients = bridge
    with pytest.raises(ValidationError, match="limit"):
        scenario.run()
    assert ApiClient.objects.filter(makerspace=target_space).count() == 0
    assert ApiClientImportApproval.objects.filter(makerspace=target_space).count() == 0
    assert AuditLog.objects.filter(makerspace=target_space, action="tenant_migration.api_client_reissued").count() == 0
    target_space.resource_limit_overrides = {"api_clients": 1}
    target_space.save(update_fields=["resource_limit_overrides"])
    scenario.run()
    assert len(calls) == 2
    assert len(restored) == 1  # quota retry resumes after the completed dump phase
    client = ApiClient.objects.get(makerspace=target_space)
    record = calls[-1]
    provenance = provenance_digest(artifact_sha256=produced.inputs.artifact_sha256,
                                   makerspace_id=target_space.pk, source_client_ref=record["source_client_ref"])
    assert client.import_provenance_digest == provenance
    delivered = store.read_unacknowledged(provenance)
    assert client.get_secret() == delivered["secret"]
    for old, old_secret in frozen.own:
        assert client.client_id != old.client_id
        assert hashlib.sha256(client.get_secret().encode()).digest() != hashlib.sha256(old_secret.encode()).digest()
        assert bytes(client.secret_encrypted) != bytes(old.secret_encrypted)
    approval = ApiClientImportApproval.objects.get(api_client=client)
    assert approval.source_catalog_sha256 == frozen.catalog["sha256"]
    assert approval.approval_record_sha256 == record["approval_record_sha256"]
    assert approval.host_principal == record["host_principal"]
    assert approval.approval_nonce == record["nonce"]
    assert str(approval.capture_id) == produced.inputs.capture_id
    public = ApiClientSerializer(client).data
    assert public["client_id"] == client.client_id
    assert public["scopes"] == ["public:read"]
    assert public["allowed_origins"] == ["https://target.example.test"]
    assert "client_secret" not in public and "secret_encrypted" not in public
    retried = reissue_approved_client(makerspace=target_space, record=record, delivery_store=store)
    assert retried.pk == client.pk
    assert store.read_unacknowledged(provenance) == delivered
    assert ApiClientImportApproval.objects.filter(makerspace=target_space).count() == 1
    audit = AuditLog.objects.get(makerspace=target_space, action="tenant_migration.api_client_reissued")
    assert audit.meta["provenance"] == provenance
    assert audit.meta["source_client_ref"] == record["source_client_ref"]
    ledger = scenario.ledger_path.read_text()
    for forbidden in (client.get_secret(), "Frozen active", "source.example.test", "target.example.test",
                      str(produced.path), str(produced.identity), str(restored[0]), "host_principal", "nonce"):
        assert forbidden not in ledger
    assert client.get_secret() not in json.dumps(audit.meta)
    before = scenario.ledger_path.read_bytes()
    scenario.run()
    assert scenario.ledger_path.read_bytes() == before
    assert len(calls) == 2
