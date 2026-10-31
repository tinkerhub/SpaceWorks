from decimal import Decimal

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace, MakerspaceMembership, PurgeReceipt
from apps.makerspaces import purge_storage
from apps.makerspaces.purge_intent import load_intent
from django.utils.dateparse import parse_datetime
from tests.makerspaces.purge_test_support import purge_clock, purge_store
from apps.operations.models import StockTransfer

pytestmark = pytest.mark.django_db


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        access_status=User.AccessStatus.ACTIVE,
        **kwargs,
    )


def test_non_superadmin_staff_is_denied_from_django_admin_index():
    user = make_user(
        "admin-denied-manager",
        role=User.Role.SPACE_MANAGER,
        is_staff=True,
    )
    client = Client()
    client.force_login(user)

    response = client.get("/control/")

    assert response.status_code == 403


def test_superadmin_is_allowed_to_django_admin_index():
    user = make_user(
        "admin-allowed-superadmin",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(user)

    response = client.get("/control/")

    assert response.status_code == 200


def test_react_staff_admin_api_path_is_not_gated_by_django_admin_middleware():
    makerspace = Makerspace.objects.create(name="API Staff", slug="api-staff")
    user = make_user(
        "api-staff-manager",
        role=User.Role.SPACE_MANAGER,
        is_staff=True,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/admin/makerspaces")

    assert response.status_code == 200


def test_django_admin_login_csp_allows_unsafe_eval():
    client = Client()

    response = client.get("/control/login/", SERVER_NAME="localhost")

    assert response.status_code == 200
    csp = response["Content-Security-Policy"]
    script_src = next(
        section for section in csp.split(";") if section.strip().startswith("script-src")
    )
    assert "'unsafe-eval'" in script_src


def test_non_admin_docs_root_csp_does_not_allow_unsafe_eval():
    client = Client()

    response = client.get("/", SERVER_NAME="localhost")

    assert response.status_code == 200
    csp = response["Content-Security-Policy"]
    assert "'unsafe-eval'" not in csp


@pytest.mark.django_db(transaction=True)
def test_superadmin_can_delete_archived_makerspace_from_django_admin(purge_store, purge_clock):
    superadmin = make_user(
        "admin-delete-archived-superadmin",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    makerspace = Makerspace.objects.create(
        name="Admin Delete Archived",
        slug="admin-delete-archived",
    )
    StockTransfer.objects.create(
        makerspace=makerspace,
        created_by=superadmin,
        reason="Admin delete regression",
    )
    AuditLog.objects.create(
        actor=superadmin,
        action="admin.delete_regression",
        makerspace=makerspace,
    )
    archived = lifecycle.archive(makerspace, superadmin)
    survivor = Makerspace.objects.create(name="Purge survivor", slug="purge-survivor")
    history = AuditLog.objects.create(actor=superadmin, action="purge.survivor_history", makerspace=survivor)
    doomed_id = archived.pk
    bucket = purge_storage.bucket_name("private")
    key = f"evidence/{doomed_id}/admin-purge.jpg"
    versions = {
        purge_store.put(bucket, locator, payload, marker=marker)
        for locator in (key, f"staging/{key}")
        for payload, marker in ((b"old", False), (b"new", False), (b"", True))
    }
    survivor_version = purge_store.put(bucket, f"evidence/{survivor.pk}/keep.jpg")

    client = Client()
    client.force_login(superadmin)
    url = reverse("admin:makerspaces_makerspace_delete", args=[archived.pk])

    # The generic delete page is no purge entry point; only the slug-confirmed action is.
    assert client.get(url).status_code == 403
    assert client.post(url, {"post": "yes"}).status_code == 403

    response = client.post(
        reverse("admin:makerspaces_makerspace_changelist"),
        {
            "action": "purge_makerspaces",
            ACTION_CHECKBOX_NAME: [str(archived.pk)],
            "confirm_purge": "1",
            f"slug_{archived.pk}": archived.slug,
        },
    )

    # Legacy changelist POST only renders the dedicated CSRF confirmation form.
    assert response.status_code == 200
    confirmed_url = reverse("admin:makerspaces_makerspace_purge_confirmed")
    assert confirmed_url.encode() in response.content
    assert b'csrfmiddlewaretoken' in response.content
    assert Makerspace.objects.filter(pk=doomed_id).exists()
    assert not PurgeReceipt.objects.filter(source_makerspace_id=doomed_id).exists()
    assert set(purge_store.objects) == versions | {survivor_version}
    data = {"makerspace_id": str(doomed_id), f"slug_{doomed_id}": archived.slug}
    first = client.post(confirmed_url, data)
    assert first.status_code == 200 and b"Retry after" in first.content
    archived.refresh_from_db()
    assert archived.purge_started_at is not None
    assert set(purge_store.objects) == versions | {survivor_version}
    assert Makerspace.objects.filter(pk=doomed_id).exists()
    assert StockTransfer.objects.filter(makerspace_id=doomed_id).exists()
    assert AuditLog.objects.filter(makerspace_id=doomed_id).exists()
    purge_clock.now = parse_datetime(load_intent(archived)["not_before"])
    second = client.post(confirmed_url, data)
    assert second.status_code == 200 and b"Tenant graph removed" in second.content
    assert not Makerspace.objects.filter(pk=doomed_id).exists()
    receipt = PurgeReceipt.objects.get(source_makerspace_id=doomed_id)
    assert receipt.last_verified_at == purge_clock.now
    assert receipt.graph_purged_at == purge_clock.now
    assert {("private", key), ("private", f"staging/{key}")} <= set(map(tuple, receipt.exact_keys))
    removed = {
        (call["Bucket"], row["Key"], row["VersionId"])
        for call in purge_store.deletes for row in call["Delete"]["Objects"]
    }
    assert removed == versions
    assert set(purge_store.objects) == {survivor_version}
    assert Makerspace.objects.filter(pk=survivor.pk).exists()
    assert AuditLog.objects.filter(pk=history.pk, makerspace=survivor).exists()
    assert not StockTransfer.objects.filter(makerspace_id=doomed_id).exists()
    assert not AuditLog.objects.filter(makerspace_id=doomed_id).exists()
