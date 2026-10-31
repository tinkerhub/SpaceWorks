"""Exact native admin POST, CSRF, current custody, actor and origin decisions."""
from unittest.mock import Mock

import pytest
from django.contrib import admin
from django.test import Client, RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.makerspaces import admin_module_purge_receipts
from apps.makerspaces.models import Makerspace, MakerspaceMembership, ModulePurgeReceipt
from tests.makerspaces.module_cleanup_support import actor, module_space, module_receipt, module_store


def url(row):
    return reverse("admin:makerspaces_modulepurgereceipt_retry_cleanup", args=[row.pk])


def login(user, *, csrf=False):
    client = Client(enforce_csrf_checks=csrf)
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_exact_uuid_route_is_post_only_and_csrf_protected(monkeypatch, module_store):
    row, user = module_receipt(module_space(), completed=True), actor()
    service = Mock(side_effect=AssertionError("unprotected retry dispatch"))
    monkeypatch.setattr(admin_module_purge_receipts, "retry_cleanup", service)
    client = login(user, csrf=True)
    target = url(row)
    assert client.get(target).status_code == 405
    assert client.post(target).status_code == 403
    service.assert_not_called()
    match = resolve(target)
    assert match.view_name == "admin:makerspaces_modulepurgereceipt_retry_cleanup"
    assert "default" in match.func._non_atomic_requests and not getattr(match.func, "csrf_exempt", False)
    assert module_store.calls == []


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["role-only", "staff-only", "inactive", "restricted", "temporary", "not-staff"])
def test_middleware_and_model_admin_deny_noncurrent_superusers(kind, monkeypatch, module_store):
    overrides = {
        "role-only": {"is_superuser": False}, "staff-only": {"is_superuser": False, "role": "requester"},
        "inactive": {"is_active": False}, "restricted": {"access_status": "restricted"},
        "temporary": {"must_change_password": True}, "not-staff": {"is_staff": False},
    }[kind]
    user, row = actor(**overrides), module_receipt(module_space(), completed=True)
    service = Mock(side_effect=AssertionError("unauthorized dispatch"))
    monkeypatch.setattr(admin_module_purge_receipts, "retry_cleanup", service)
    assert login(user).post(url(row)).status_code in {302, 403}
    request = RequestFactory().get(url(row)); request.user = user
    model_admin = admin.site._registry[ModulePurgeReceipt]
    # The model-level gate is checked independently of middleware/session admission.
    if kind != "not-staff":
        assert not model_admin.has_view_permission(request, row)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request, row)
    assert not model_admin.has_delete_permission(request, row)
    service.assert_not_called()
    assert module_store.calls == []


@pytest.mark.django_db
@pytest.mark.parametrize("membership", [False, True], ids=["global-operator", "also-explicit-member"])
def test_hidden_custody_hides_list_detail_and_retry_even_for_member_superuser(membership, module_store):
    space, user = module_space(), actor()
    row = module_receipt(space, completed=True)
    if membership:
        MakerspaceMembership.objects.create(makerspace=space, user=user, role="space_manager", status="active")
    Makerspace.objects.filter(pk=space.pk).update(superadmin_access_enabled=False)
    client = login(user)
    response = client.get(reverse("admin:makerspaces_modulepurgereceipt_changelist"))
    assert response.status_code == 200 and str(row.pk).encode() not in response.content
    response = client.get(reverse("admin:makerspaces_modulepurgereceipt_change", args=[row.pk]))
    assert response.status_code in {302, 403, 404}
    assert client.post(url(row)).status_code == 404
    assert module_store.calls == []


@pytest.mark.django_db
@pytest.mark.parametrize("parameters", [{"action": "delete_selected"}, {"force": "1"},
                                          {"csrfmiddlewaretoken": ["a", "b"]}])
def test_mixed_or_duplicate_retry_parameters_do_not_dispatch(parameters, monkeypatch, module_store):
    user, row = actor(), module_receipt(module_space(), completed=True)
    service = Mock()
    monkeypatch.setattr(admin_module_purge_receipts, "retry_cleanup", service)
    assert login(user).post(url(row), parameters).status_code == 400
    assert login(user).post(url(row) + "?force=1").status_code == 400
    service.assert_not_called()
    assert module_store.calls == []


@pytest.mark.django_db
def test_malformed_uuid_cannot_resolve_to_retry_and_direct_parser_is_bounded(module_store, monkeypatch):
    user, row = actor(), module_receipt(module_space(), completed=True)
    target = url(row)
    service = Mock()
    monkeypatch.setattr(admin_module_purge_receipts, "retry_cleanup", service)
    model_admin = admin.site._registry[ModulePurgeReceipt]
    request = RequestFactory().post(target); request.user = user
    for raw in ("9" * 10000, str(row.pk).replace("-", ""), str(row.pk).upper(), "../" + str(row.pk)):
        assert admin_module_purge_receipts.retry_cleanup_view(request, raw, model_admin).status_code == 400
        malformed = target.replace(str(row.pk), raw)
        assert resolve(malformed).url_name != "makerspaces_modulepurgereceipt_retry_cleanup"
    service.assert_not_called()
    assert module_store.calls == []


@pytest.mark.django_db
def test_origin_scope_cannot_cross_tenant_receipts(module_store, settings):
    space, user = module_space(frontend_domain="cleanup-a.example.test"), actor()
    other = module_space("origin-other", frontend_domain="cleanup-b.example.test")
    row = module_receipt(space, completed=True)
    settings.PLATFORM_STAFF_ORIGINS = []
    response = login(user).post(url(row), HTTP_ORIGIN="https://cleanup-b.example.test")
    assert response.status_code in {403, 404}
    assert module_store.calls == []
    request = RequestFactory().get(url(row), HTTP_ORIGIN="https://cleanup-b.example.test")
    request.user = user
    assert not admin.site._registry[ModulePurgeReceipt].get_queryset(request).filter(pk=row.pk).exists()
    assert other.pk != space.pk


@pytest.mark.django_db(transaction=True)
def test_actual_csrf_post_completes_only_manual_retry_and_truthfully_reports_last_verification(module_store):
    from apps.makerspaces.module_purge import purge_module
    from apps.makerspaces.purge_storage import bucket_name

    space, user = module_space(), actor()
    row, _ = purge_module(space, "events", user)
    client = login(user, csrf=True)
    detail = reverse("admin:makerspaces_modulepurgereceipt_change", args=[row.pk])
    assert client.get(detail).status_code == 200
    token = client.cookies["csrftoken"].value
    key = f"staging/event/{space.pk}/{'a' * 32}.png"
    identity = module_store.put(bucket_name("public_image"), key)
    response = client.post(url(row), {"csrfmiddlewaretoken": token}, follow=True)
    assert response.status_code == 200 and identity not in module_store.objects
    assert b"Late-upload cleanup remains available" in response.content
    assert b"last verified" in response.content
    model_admin = admin.site._registry[ModulePurgeReceipt]
    assert model_admin.actions is None
    request = RequestFactory().post(detail); request.user = user
    assert not model_admin.has_delete_permission(request, row)
    assert not model_admin.has_change_permission(request, row)


@pytest.mark.django_db
@pytest.mark.parametrize("identity_field", ["public_code", "created_at"])
def test_reincarnated_source_identity_hides_receipt_detail_and_retry(
    identity_field, module_store, monkeypatch,
):
    space, user = module_space(), actor()
    row = module_receipt(space, completed=True)
    audit.record(user, "makerspace.module_purged", target=row,
                 meta={"source_makerspace_id": space.pk, "module_key": "events"})
    service = Mock(side_effect=AssertionError("reincarnated source dispatched cleanup"))
    monkeypatch.setattr(admin_module_purge_receipts, "retry_cleanup", service)
    detail = reverse("admin:makerspaces_modulepurgereceipt_change", args=[row.pk])
    client = login(user, csrf=True)
    assert client.get(detail).status_code == 200
    token = client.cookies["csrftoken"].value
    request = RequestFactory().get(detail)
    request.user = user
    model_admin = admin.site._registry[ModulePurgeReceipt]
    assert model_admin.get_queryset(request).filter(pk=row.pk).exists()
    assert model_admin.has_view_permission(request, row)
    original_maker = Makerspace.objects.values().get(pk=space.pk)
    original_receipt = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    original_audits = list(AuditLog.objects.order_by("pk").values())
    replacement = (
        "NEW1" if space.public_code != "NEW1" else "NEW2"
    ) if identity_field == "public_code" else space.created_at + timezone.timedelta(seconds=1)
    assert replacement != original_maker[identity_field]

    # Change only one live identity field. The immutable receipt retains the
    # original PK/code/time; the other identity dimension still matches exactly.
    assert Makerspace.objects.filter(pk=space.pk).update(**{identity_field: replacement}) == 1
    assert Makerspace.objects.values().get(pk=space.pk) == {
        **original_maker, identity_field: replacement,
    }
    assert space.pk == row.source_makerspace_id
    assert not model_admin.get_queryset(request).filter(pk=row.pk).exists()
    assert not model_admin.has_view_permission(request, row)
    assert client.get(detail).status_code in {302, 403, 404}
    assert client.post(url(row), {"csrfmiddlewaretoken": token}).status_code == 404
    service.assert_not_called()
    assert module_store.calls == []
    assert ModulePurgeReceipt.objects.values().get(pk=row.pk) == original_receipt
    assert list(AuditLog.objects.order_by("pk").values()) == original_audits
