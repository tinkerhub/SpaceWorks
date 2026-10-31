"""Standalone API regression: copy this file alone onto the pre-ledger source.

No ledger/new-test-package dependency: the old source must reach the assertion
after a successful 204 and physical version deletion, then expose its leaked debit.
"""
import pytest
from django.urls import reverse

from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from tests.document_safety.helpers import (
    accepted_body, cap, finalize, lab, presign, usage,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
def test_actual_document_delete_restores_finite_capacity_for_next_cycle(
    kind, monkeypatch, settings,
):
    # Use the original model directly: transaction-test flush removes the real
    # migration's singleton, including on the preserved pre-ledger checkout.
    DeploymentDatabaseIdentity.objects.get_or_create(pk=1)
    case = lab(monkeypatch, settings, kind)
    body = accepted_body("application/pdf")
    unrelated = 900
    cap(case, unrelated + len(body), used=unrelated)

    for _cycle in range(2):
        key, _upload = presign(case)
        case.store.seed(case.module.staging_key(key), body, "application/pdf")
        response = finalize(case, key)
        assert response.status_code == 201, response.data
        row = case.model.objects.get(pk=response.data["id"])
        row_id = row.pk
        assert usage(case) == unrelated + len(body)
        assert case.store.objects[key][0] == body
        assert case.store.versions[key]

        deleted = case.client.delete(
            reverse(f"{case.prefix}-detail", kwargs={"pk": row_id}),
        )
        assert deleted.status_code == 204
        assert not case.model.objects.filter(pk=row_id).exists()
        assert key not in case.store.objects
        assert not case.store.versions.get(key)
        assert not case.store.versions.get(case.module.staging_key(key))
        # Critical red assertion: old code has already deleted the object and
        # metadata successfully, but leaves 900 + len(body) charged forever.
        assert usage(case) == unrelated, "Successful physical deletion leaked its storage debit"
