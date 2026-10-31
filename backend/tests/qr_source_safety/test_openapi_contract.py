"""Inspect the generated public contract without making native a client input."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MUTATIONS = (
    "/api/v1/admin/qr/boxes", "/api/v1/admin/qr/tools", "/api/v1/admin/qr/scan",
    "/api/v1/admin/qr/resolve", "/api/v1/admin/qr/{id}/revoke",
    "/api/v1/admin/qr/{id}/rebind-target", "/api/v1/admin/products/{id}/assets/generate",
)


def schema():
    return json.loads((ROOT / "frontend/openapi-schema.json").read_text())


@pytest.mark.parametrize("path", MUTATIONS)
def test_qr_mutation_schema_documents_typed_gate_refusals(path):
    responses = schema()["paths"][path]["post"]["responses"]
    assert "tenant_migration_quiesced" in responses["423"]["description"]
    assert "tenant_migration_gate_unavailable" in responses["503"]["description"]


def test_native_generation_keyword_is_not_a_public_request_schema_field():
    contract = schema()
    operation = contract["paths"]["/api/v1/admin/products/{id}/assets/generate"]["post"]
    for media in operation["requestBody"]["content"].values():
        request = media["schema"]
        if "$ref" in request:
            request = contract["components"]["schemas"][request["$ref"].split("/")[-1]]
        assert "native" not in request["properties"]
        assert set(request["properties"]) == {
            "count", "name_prefix", "serial_numbers", "print_batch_id", "create_print_batch",
        }


def test_print_get_retains_its_read_error_contract_without_write_gate_responses():
    operation = schema()["paths"]["/api/v1/admin/qr/{id}/print"]["get"]
    assert set(operation["responses"]) == {"200", "400", "403", "404"}
