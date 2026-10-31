"""Real scoped encryption, PostgreSQL write fences, and portable classifications."""
from importlib import import_module

import pytest
from django.db import DatabaseError, connection, transaction
from rest_framework.test import APIClient

from apps.encryption.models import PiiMakerspaceWriteFence
from apps.encryption.registry import field_for
from apps.encryption.write_fence import PiiWriteFenced, close_makerspace, reopen
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest
from tests.encryption.conftest import enabled_encryption
from tests.test_request_workflow import history_url, public_status_url
from tests.hardware_requests.cancellation_support import accepted_lab, cancel, snapshot

pytestmark = pytest.mark.django_db


def raw_reason(pk):
    with connection.cursor() as cursor:
        cursor.execute("SELECT cancellation_reason FROM hardware_requests_hardwarerequest WHERE id = %s", [pk])
        return cursor.fetchone()[0]


def test_reason_is_encrypted_at_rest_staff_readable_and_absent_from_public_bearer(settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    reason = "Private borrower circumstance 731: household emergency."
    with enabled_encryption():
        lab = accepted_lab()
        response = lab.client.post(f"/api/v1/admin/requests/{lab.request.pk}/cancel",
                                   {"reason": reason}, format="json")
        assert response.status_code == 200, response.content
        assert response.data["cancellation_reason"] == reason
        ciphertext = raw_reason(lab.request.pk)
        assert ciphertext.startswith("pii:gcm:v1:")
        assert reason not in ciphertext
        assert HardwareRequest.objects.get(pk=lab.request.pk).cancellation_reason == reason
        history = lab.client.get(history_url(lab.space))
        assert history.status_code == 200
        assert history.data["results"][0]["cancellation_reason"] == reason
        public = APIClient().get(public_status_url(lab.request.public_token))
        assert public.status_code == 200, public.content
        assert set(public.data) == {"status", "created_at", "items"}
        assert public.data["status"] == "cancelled"
        assert "cancellation_reason" not in public.data
        assert "closed_by" not in public.data
        assert "closed_at" not in public.data
        assert reason not in public.content.decode()


def trigger_columns():
    with connection.cursor() as cursor:
        cursor.execute("""SELECT a.attname FROM pg_trigger t
            CROSS JOIN LATERAL unnest(t.tgattr::smallint[]) AS watched(attnum)
            JOIN pg_attribute a ON a.attrelid=t.tgrelid AND a.attnum=watched.attnum
            WHERE t.tgname='pii_fence_hardware_request_trigger'""")
        return {row[0] for row in cursor.fetchall()}


def touch(column, pk):
    # Column identifiers below come only from this test's finite literal allowlist.
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE hardware_requests_hardwarerequest SET {column}={column} WHERE id=%s", [pk])


def test_forward_reverse_trigger_sql_preserves_all_five_existing_column_guards():
    migration = import_module("apps.encryption.migrations.0009_request_cancellation_pii_fence")
    original = {"requester_username", "requester_name", "requester_contact_email",
                "requester_contact_phone", "checkin_project_name"}
    lab = accepted_lab()
    operation = close_makerspace(lab.space.pk,
        PiiMakerspaceWriteFence.OperationKind.DECRYPT_ROLLBACK, lab.actor.pk)
    try:
        assert trigger_columns() == original | {"cancellation_reason"}
        for column in original | {"cancellation_reason"}:
            with pytest.raises(DatabaseError), transaction.atomic():
                touch(column, lab.request.pk)
        with connection.cursor() as cursor:
            cursor.execute(migration.REVERSE_SQL)
        assert trigger_columns() == original
        for column in original:
            with pytest.raises(DatabaseError), transaction.atomic():
                touch(column, lab.request.pk)
        # Reversal intentionally restores the pre-feature five-column contract.
        touch("cancellation_reason", lab.request.pk)
    finally:
        with connection.cursor() as cursor:
            cursor.execute(migration.FORWARD_SQL)
        reopen(operation, lab.actor.pk)
    assert trigger_columns() == original | {"cancellation_reason"}


def test_closed_fence_refuses_before_any_request_row_lock():
    lab = accepted_lab()
    operation = close_makerspace(lab.space.pk, "decrypt_rollback", lab.actor.pk)
    before = snapshot()
    locks = []

    def observe(execute, sql, params, many, context):
        if 'FROM "hardware_requests_hardwarerequest"' in sql and " FOR " in sql:
            locks.append(sql)
        return execute(sql, params, many, context)

    try:
        with connection.execute_wrapper(observe), pytest.raises(PiiWriteFenced):
            workflow.cancel_request(lab.actor, lab.request, "Fenced private reason")
        assert locks == []
        assert snapshot() == before
        response = cancel(lab)
        assert response.status_code == 503
        assert response.data["code"] == "pii_write_fenced"
        assert snapshot() == before
    finally:
        reopen(operation, lab.actor.pk)


def test_stale_request_tenant_refuses_without_acquiring_a_different_tenant_fence():
    from tests.test_request_workflow import make_space

    lab = accepted_lab()
    other = make_space("cancel-changed-tenant")
    # Keep the caller's original request instance pointing at its pre-fenced scope.
    HardwareRequest.objects.filter(pk=lab.request.pk).update(makerspace=other)
    operation = close_makerspace(other.pk, "decrypt_rollback", lab.actor.pk)
    before = snapshot()
    try:
        # A late fence on the locked tenant would instead raise PiiWriteFenced;
        # changing tenants under a concrete caller must refuse as a transition.
        with pytest.raises(workflow.InvalidTransition):
            workflow.cancel_request(lab.actor, lab.request, "Do not cross tenant fences")
        assert snapshot() == before
    finally:
        reopen(operation, lab.actor.pk)


def test_catalog_and_real_reference_guards_classify_reason_and_typed_box_edge():
    from apps.data_export.classification import EXPORTED_MODEL_FIELDS
    from apps.data_export.guards import validate_model_and_field_coverage
    from apps.tenant_migration.audit_reference_guards import validate_audit_meta_references
    from apps.tenant_migration.audit_references import AUDIT_META_REFERENCES, AuditReferenceDisposition
    from apps.tenant_migration.tenant_dump_catalog import (
        CATALOG_SCHEMA_SHA256, FIELD_POLICIES, schema_digest, validate_catalog,
    )
    from apps.tenant_migration.tenant_dump_types import NoAuthorityField

    validate_catalog()
    validate_model_and_field_coverage()
    validate_audit_meta_references()
    assert schema_digest() == CATALOG_SCHEMA_SHA256
    assert isinstance(FIELD_POLICIES[("hardware_requests.HardwareRequest", "cancellation_reason")], NoAuthorityField)
    assert "cancellation_reason" in EXPORTED_MODEL_FIELDS["hardware_requests.HardwareRequest"].split()
    rule = field_for(HardwareRequest, "cancellation_reason")
    assert rule is not None
    assert (rule.classification, rule.makerspace_path, rule.max_length, rule.index_kind) == (
        "source", "makerspace_id", 500, "none",
    )
    edge = AUDIT_META_REFERENCES[("request.cancelled", "previous_box_id")]
    assert edge.disposition is AuditReferenceDisposition.REMAP
    assert edge.target_model_label == "boxes.Box"
