"""API publication retains actual source/storage exclusion through the audit."""
import pytest
from django.db import connections

from apps.audit import services as audit
from tests.document_safety.helpers import (
    accepted_body, assert_storage_boundary, finalize, lab, presign,
)

pytestmark = pytest.mark.django_db(transaction=True)


def try_exclusions(makerspace_id):
    contender = connections["default"].copy()
    try:
        with contender.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(
                "SELECT pg_try_advisory_xact_lock(734310, %s), "
                "pg_try_advisory_xact_lock(734312, %s)", [makerspace_id, makerspace_id],
            )
            return cursor.fetchone()
    finally:
        contender.rollback()
        contender.close()


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
def test_real_source_and_storage_exclusion_survives_publication_until_metadata_commit(
    kind, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    case.store.seed(case.module.staging_key(key), accepted_body("application/pdf"))
    provider_probes, audit_probes = [], []
    real_record = audit.record
    action = "procurement.receipt_added" if kind == "receipt" else "warranty.document_added"

    def provider_boundary():
        assert_storage_boundary(case)
        provider_probes.append(try_exclusions(case.home.pk))

    def record(actor, event, **kwargs):
        result = real_record(actor, event, **kwargs)
        if event == action:
            assert case.model.objects.filter(object_key=key).exists()
            audit_probes.append(try_exclusions(case.home.pk))
        return result

    case.store.boundary = provider_boundary
    monkeypatch.setattr(audit, "record", record)
    response = finalize(case, key)
    assert response.status_code == 201, response.data
    assert provider_probes and all(result == (False, False) for result in provider_probes)
    assert audit_probes == [(False, False)]
    assert try_exclusions(case.home.pk) == (True, True)
