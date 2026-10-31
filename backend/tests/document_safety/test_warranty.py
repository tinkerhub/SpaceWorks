"""Sparse PUT preserves omitted fields; native admin cannot move existing hosts."""
import pytest
from django.contrib import admin
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.warranty.models import Warranty
from tests.document_safety.helpers import asset, fail_after_audit, lab, machine

pytestmark = pytest.mark.django_db(transaction=True)


def host_url(case):
    kind = "asset" if case.target.asset_id else "machine"
    return reverse(f"admin-{kind}-warranty", kwargs={"pk": getattr(case.target, f"{kind}_id")})


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_sparse_put_preserves_omitted_fields_and_explicit_clear_is_honored(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    initial = {"purchased_on": "2025-01-02", "warranty_expires_on": "2028-01-02",
               "vendor_name": "Original", "vendor_contact": "555-0100"}
    response = case.client.put(host_url(case), initial, format="json")
    assert response.status_code == 200, response.data
    before = AuditLog.objects.filter(action="warranty.updated").count()
    response = case.client.put(host_url(case), {"vendor_name": "New vendor"}, format="json")
    assert response.status_code == 200, response.data
    for field in ("purchased_on", "warranty_expires_on", "vendor_contact"):
        assert response.data[field] == initial[field]
    assert response.data["vendor_name"] == "New vendor"
    assert AuditLog.objects.filter(action="warranty.updated").count() == before + 1
    response = case.client.put(host_url(case), {"purchased_on": None, "vendor_contact": ""}, format="json")
    assert response.status_code == 200
    assert response.data["purchased_on"] is None and response.data["vendor_contact"] == ""
    assert response.data["warranty_expires_on"] == initial["warranty_expires_on"]


@pytest.mark.parametrize("kind", ["asset", "machine"])
@pytest.mark.parametrize("existing", [False, True])
def test_upsert_real_audit_insert_failure_rolls_back_new_or_existing_warranty(
    kind, existing, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    url = host_url(case)
    if not existing:
        case.target.delete()  # No documents: no provider/lifecycle work is bypassed.
    before = list(Warranty.objects.values()), AuditLog.objects.count()
    action = "warranty.updated" if existing else "warranty.created"
    _, inserted = fail_after_audit(monkeypatch, action)
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        case.client.put(url, {"vendor_name": "rollback", "purchased_on": "2025-02-03"}, format="json")
    assert inserted
    assert (list(Warranty.objects.values()), AuditLog.objects.count()) == before


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_actual_native_change_form_excludes_host_and_tenant_but_accepts_vendor_dates(
    kind, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    request = RequestFactory().get("/control/")
    request.user = case.actor
    model_admin = admin.site._registry[Warranty]
    form_class = model_admin.get_form(request, case.target)
    assert not {"makerspace", "asset", "machine"} & form_class.base_fields.keys()
    form = form_class(instance=case.target, data={
        "vendor_name": "Usable", "vendor_contact": "555-0101", "purchased_on": "2025-01-02",
        "warranty_expires_on": "2028-01-02", "makerspace": case.other.pk,
        "asset": asset(case.other).pk, "machine": machine(case.other).pk,
    })
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.makerspace_id == case.home.pk
    assert (saved.asset_id, saved.machine_id) == (case.target.asset_id, case.target.machine_id)
    assert saved.vendor_name == "Usable" and saved.purchased_on.isoformat() == "2025-01-02"


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_malicious_actual_admin_post_cannot_change_host_tenant_but_can_edit_vendor_date(
    kind, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    original = (case.target.makerspace_id, case.target.asset_id, case.target.machine_id)
    root = User.objects.create_superuser(
        username="warranty-admin", email="warranty-admin@example.test", password="admin-password",
        role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
    )
    client = Client(HTTP_HOST="testserver")
    client.force_login(root)
    response = client.post(reverse("admin:warranty_warranty_change", args=[case.target.pk]), {
        "makerspace": case.other.pk, "asset": asset(case.other).pk,
        "machine": machine(case.other).pk, "vendor_name": "Updated in native admin",
        "vendor_contact": "555-0102", "purchased_on": "2025-03-04",
        "warranty_expires_on": "2029-03-04", "_save": "Save",
    })
    assert response.status_code == 302
    case.target.refresh_from_db()
    assert (case.target.makerspace_id, case.target.asset_id, case.target.machine_id) == original
    assert case.target.vendor_name == "Updated in native admin"
    assert case.target.purchased_on.isoformat() == "2025-03-04"
    assert case.target.warranty_expires_on.isoformat() == "2029-03-04"
    case.target.full_clean()
