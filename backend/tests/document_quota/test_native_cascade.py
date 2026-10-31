"""Actual guarded native deletion paths preserve charge PK and tenant scope."""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from tests.document_safety.helpers import assert_storage_boundary, cap, lab, usage
from tests.document_quota.helpers import KINDS, releases, upload

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("path", ["document", "parent", "bulk-parent"])
def test_native_guarded_document_or_cascade_delete_releases_real_charge(
    kind, path, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    row, charge, body = upload(case)
    doc_pk = row.pk
    survivor, _, survivor_body = upload(case, variant=True)
    # Cascade must remove both charged children; single-document deletion must
    # retain its real charged neighbor and exactly that neighbor's quota usage.
    root = User.objects.create_superuser(
        username=f"native-quota-{kind}", email="native-quota@example.test",
        password="test-native-quota", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = Client(HTTP_HOST="testserver")
    client.force_login(root)
    case.store.boundary = lambda: assert_storage_boundary(case)
    if path == "document":
        name = "procurement_tobuyreceipt" if kind == "receipt" else "warranty_warrantydocument"
        url = reverse(f"admin:{name}_delete", args=[doc_pk])
        data = {"post": "yes"}
    else:
        name = "procurement_tobuyitem" if kind == "receipt" else "warranty_warranty"
        if path == "parent":
            url, data = reverse(f"admin:{name}_delete", args=[case.target.pk]), {"post": "yes"}
        else:
            url = reverse(f"admin:{name}_changelist")
            data = {"action": "delete_selected", "_selected_action": [str(case.target.pk)], "post": "yes"}
    response = client.post(url, data)
    assert response.status_code == 302
    assert not case.model.objects.filter(pk=doc_pk).exists()
    assert not case.store.versions.get(row.object_key)
    release = releases(case).get(target_type=row._meta.label_lower, target_id=str(doc_pk))
    assert release.meta["charge_event_uuid"] == str(charge.event_uuid)
    assert release.makerspace_id == case.home.pk and release.meta["bytes"] == len(body)
    if path == "document":
        assert case.model.objects.filter(pk=survivor.pk).exists()
        assert case.store.objects[survivor.object_key][0] == survivor_body
        assert usage(case) == 900 + len(survivor_body) and releases(case).count() == 1
    else:
        assert not case.model.objects.filter(pk=survivor.pk).exists()
        assert not case.store.versions.get(survivor.object_key)
        assert usage(case) == 900 and releases(case).count() == 2
