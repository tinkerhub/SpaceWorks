import pytest
from django.urls import path
from drf_spectacular.generators import SchemaGenerator

from apps.operations.views_qr_batches import QrPrintBatchDetailView

pytestmark = pytest.mark.django_db


def references(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def test_detail_schema_explicitly_allows_null_qr_and_keeps_nested_component_and_snapshots():
    # Restrict generation to the real detail view. Never write global artifacts.
    schema = SchemaGenerator(patterns=[path(
        "api/v1/admin/qr-print-batches/<int:pk>", QrPrintBatchDetailView.as_view(),
        name="qr-print-batch-detail",
    )]).get_schema(request=None, public=True)
    assert len(schema["paths"]) == 1
    route = next(iter(schema["paths"].values()))
    assert set(route) == {"get"}
    components = schema["components"]["schemas"]
    response = route["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    detail = components[response["$ref"].rsplit("/", 1)[-1]]
    item_ref = detail["properties"]["items"]["items"]["$ref"]
    fields = components[item_ref.rsplit("/", 1)[-1]]["properties"]
    assert set(fields) == {"id", "qr_code", "label_text", "target_type", "target_id", "sort_order"}
    for name, field_type in {
        "id": "integer", "label_text": "string", "target_type": "string",
        "target_id": "integer", "sort_order": "integer",
    }.items():
        assert fields[name]["type"] == field_type
    qr = fields["qr_code"]
    # OAS 3.0 nullable and OAS 3.1 null unions both assert the actual schema.
    assert qr.get("nullable") is True or any(
        branch.get("type") == "null" for branch in qr.get("anyOf", [])
    )
    assert set(references(qr)) == {"#/components/schemas/QrCode"}
    assert set(components["QrCode"]["properties"]) == {
        "id", "makerspace", "payload", "target_type", "target_id", "status",
        "created_at", "updated_at", "revoked_at",
    }
