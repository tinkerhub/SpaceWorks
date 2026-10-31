"""Dedicated POST/CSRF authorization and truthful purge/receipt admin outcomes."""

from unittest.mock import Mock

import pytest
from django.test import Client
from django.urls import resolve, reverse

from apps.makerspaces import admin_purge, admin_purge_receipts
from apps.makerspaces.models import Makerspace
from tests.makerspaces.purge_test_support import actor, archived_space, purge_clock, purge_store, receipt

pytestmark = pytest.mark.django_db(transaction=True)


def logged_in(user, *, csrf=False):
    client = Client(enforce_csrf_checks=csrf)
    client.force_login(user)
    return client


def confirmation_url():
    return reverse("admin:makerspaces_makerspace_purge_confirmed")


def confirmation_data(space):
    return {"makerspace_id": str(space.pk), f"slug_{space.pk}": space.slug}


@pytest.mark.parametrize("route", ["confirm", "retry"])
def test_dedicated_routes_are_post_only_and_csrf_protected(route, monkeypatch):
    user, space, row = actor(), archived_space(), receipt()
    url = confirmation_url() if route == "confirm" else reverse("admin:makerspaces_purgereceipt_retry_cleanup", args=[row.pk])
    data = confirmation_data(space) if route == "confirm" else {}
    service = Mock(side_effect=AssertionError("unprotected dispatch"))
    monkeypatch.setattr(admin_purge if route == "confirm" else admin_purge_receipts,
                        "purge" if route == "confirm" else "retry_cleanup", service)
    client = logged_in(user, csrf=True)
    assert client.get(url).status_code == 405
    assert client.post(url, data).status_code == 403
    service.assert_not_called()
    match = resolve(url)
    assert "default" in match.func._non_atomic_requests
    assert not getattr(match.func, "csrf_exempt", False)


@pytest.mark.parametrize("identity", ["role_only", "staff", "inactive", "restricted", "password_reset"])
@pytest.mark.parametrize("route", ["confirm", "retry"])
def test_active_unrestricted_real_superuser_is_required(identity, route, monkeypatch):
    overrides = {
        "role_only": {"is_superuser": False, "role": "superadmin"},
        "staff": {"is_superuser": False, "role": "requester"}, "inactive": {"is_active": False},
        "restricted": {"access_status": "restricted"},
        "password_reset": {"must_change_password": True},
    }[identity]
    user, space, row = actor(**overrides), archived_space(), receipt()
    service = Mock(side_effect=AssertionError("unauthorized purge service dispatch"))
    monkeypatch.setattr(admin_purge if route == "confirm" else admin_purge_receipts,
                        "purge" if route == "confirm" else "retry_cleanup", service)
    url = confirmation_url() if route == "confirm" else reverse("admin:makerspaces_purgereceipt_retry_cleanup", args=[row.pk])
    response = logged_in(user).post(url, confirmation_data(space) if route == "confirm" else {})
    assert response.status_code in {302, 403}
    service.assert_not_called()


@pytest.mark.parametrize("invalid", ["wrong_slug", "huge_id", "malformed", "duplicate_id", "mixed", "duplicate_slug"])
def test_confirmation_rejects_ambiguous_or_unbounded_parameters(invalid, monkeypatch):
    user, space = actor(), archived_space()
    data = confirmation_data(space)
    if invalid == "wrong_slug":
        data[f"slug_{space.pk}"] = space.slug.upper()
    elif invalid == "huge_id":
        data["makerspace_id"] = "9" * 10000
    elif invalid == "malformed":
        data["makerspace_id"] = "1e3"
    elif invalid == "duplicate_id":
        data["makerspace_id"] = [str(space.pk), str(space.pk)]
    elif invalid == "mixed":
        data["action"] = "purge_makerspaces"
    else:
        data[f"slug_{space.pk}"] = [space.slug, space.slug]
    service = Mock()
    monkeypatch.setattr(admin_purge, "purge", service)
    assert logged_in(user).post(confirmation_url(), data).status_code == 400
    service.assert_not_called()


def test_receipt_uuid_and_mixed_parameters_do_not_dispatch(monkeypatch):
    user, row = actor(), receipt()
    service = Mock()
    monkeypatch.setattr(admin_purge_receipts, "retry_cleanup", service)
    url = reverse("admin:makerspaces_purgereceipt_retry_cleanup", args=[row.pk])
    client = logged_in(user)
    assert client.post(url, {"makerspace_id": "1"}).status_code == 400
    malformed = url.replace(str(row.pk), "9" * 1000)
    before = type(row).objects.values().get(pk=row.pk)
    assert resolve(malformed).url_name != "makerspaces_purgereceipt_retry_cleanup"
    response = client.post(malformed)
    # ModelAdmin redirects unknown paths to its readonly object change route.
    assert response.status_code == 302
    assert response.url == f"{malformed}change/"
    assert type(row).objects.values().get(pk=row.pk) == before
    service.assert_not_called()


def test_old_generic_action_only_renders_dedicated_confirmation(monkeypatch):
    user, space = actor(), archived_space()
    service = Mock(side_effect=AssertionError("generic action purged graph"))
    monkeypatch.setattr(admin_purge, "purge", service)
    response = logged_in(user).post(reverse("admin:makerspaces_makerspace_changelist"), {
        "action": "purge_makerspaces", "_selected_action": str(space.pk), "confirm_purge": "yes",
        f"slug_{space.pk}": space.slug,
    })
    assert response.status_code == 200
    assert confirmation_url().encode() in response.content
    assert b'csrfmiddlewaretoken' in response.content
    assert Makerspace.objects.filter(pk=space.pk).exists()
    service.assert_not_called()


def test_real_confirmation_arms_then_retries_without_shared_lock_self_deadlock(purge_store, purge_clock):
    user, space = actor(), archived_space()
    client = logged_in(user, csrf=True)
    assert client.get(reverse("admin:makerspaces_makerspace_changelist")).status_code == 200
    token = client.cookies["csrftoken"].value
    data = {**confirmation_data(space), "csrfmiddlewaretoken": token}
    first = client.post(confirmation_url(), data)
    assert first.status_code == 200 and b"Retry after" in first.content
    from apps.makerspaces.purge_intent import load_intent
    from django.utils.dateparse import parse_datetime

    space.refresh_from_db()
    purge_clock.now = parse_datetime(load_intent(space)["not_before"])
    second = client.post(confirmation_url(), data)
    assert second.status_code == 200
    body = second.content.decode()
    assert "Tenant graph removed" in body and "Storage verified at" in body
    assert "Late-upload cleanup remains available" in body and "View receipt" in body
    assert not Makerspace.objects.filter(pk=space.pk).exists()


def test_ambiguous_failure_never_claims_graph_retained_or_false_success(monkeypatch):
    user, space = actor(), archived_space()
    monkeypatch.setattr(admin_purge, "purge", Mock(side_effect=RuntimeError("commit reply lost")))
    response = logged_in(user).post(confirmation_url(), confirmation_data(space))
    text = response.content.decode()
    assert "completion is unconfirmed" in text
    assert "Tenant graph removed" not in text and "graph retained" not in text


def test_receipt_retry_success_uses_current_verification_time_and_retains_link(purge_store):
    user, row = actor(), receipt()
    url = reverse("admin:makerspaces_purgereceipt_retry_cleanup", args=[row.pk])
    response = logged_in(user).post(url, follow=True)
    assert response.status_code == 200
    assert b"Storage verified at" in response.content
    assert b"Late-upload cleanup remains available" in response.content
    row.refresh_from_db()
    assert row.namespace_prefixes and row.last_verified_at is not None
