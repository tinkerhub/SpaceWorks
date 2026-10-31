"""HTTP clients and observations for the frozen QR/native Stage-3 regressions."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.admin.models import LogEntry
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles
from apps.operations.models import QrPrintBatch, QrPrintBatchItem
from tests.admin_form_helpers import page_data


def configure(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    settings.PLATFORM_STAFF_ORIGINS = []
    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
    settings.API_CLIENT_AUTH_REQUIRED = False


def space():
    slug = f"qr-stage3-{uuid4().hex[:12]}"
    return Makerspace.objects.create(
        name=slug, slug=slug, frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )


def membership(actor, tenant, role="space_manager"):
    ensure_default_roles(tenant)
    return MakerspaceMembership.objects.create(
        user=actor, makerspace=tenant, role=role,
        assigned_role=MakerspaceRole.objects.get(makerspace=tenant, slug=role),
    )


def staff(tenant, role="space_manager"):
    actor = User.objects.create_user(
        username=f"qr-staff-{uuid4().hex[:12]}",
        access_status=User.AccessStatus.ACTIVE,
    )
    membership(actor, tenant, role)
    return actor


def superadmin():
    return User.objects.create_superuser(
        username=f"qr-root-{uuid4().hex[:12]}", email="qr-root@example.test",
        password="Stage3-native-test-password", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def jwt_client(actor):
    token = SpaceWorksRefreshToken.for_user(actor)
    token["surface"] = "staff_api"
    client = APIClient(HTTP_HOST="testserver")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def native_client(actor):
    client = Client(HTTP_HOST="testserver")
    assert client.login(username=actor.username, password="Stage3-native-test-password")
    return client


def target(tenant, kind):
    if kind == "box":
        return Box.objects.create(makerspace=tenant, label=f"Box {uuid4().hex[:8]}")
    product = InventoryProduct.objects.create(
        makerspace=tenant, name=f"Meter {uuid4().hex[:8]}",
        tracking_mode="individual" if kind == "asset" else "quantity",
        total_quantity=1, available_quantity=1,
    )
    if kind == "product":
        return product
    return InventoryAsset.objects.create(
        makerspace=tenant, product=product, asset_tag=f"A-{uuid4().hex[:8]}",
    )


def qr_for(tenant, obj, kind, **kwargs):
    return QrCode.objects.create(
        makerspace=tenant, target_type=kind, target_id=obj.pk, **kwargs,
    )


def snapshot(*extra_models):
    models = (Box, QrCode, QrScanEvent, QrPrintBatchItem, AuditLog,
              InventoryProduct, InventoryAsset, LogEntry, *extra_models)
    return {model._meta.label_lower: list(model.objects.order_by("pk").values())
            for model in models}


def request_qr(case, operation, qr, **headers):
    if operation == "print":
        return case.client.get(reverse("qr-print", args=[qr.pk]), **headers)
    if operation == "batch":
        return case.client.post(
            reverse("qr-print-batch-items", args=[case.batch.pk]),
            {"qr_code_id": qr.pk, "label_text": "Explicit manual label"},
            format="json", **headers,
        )
    body = {"payload": qr.payload}
    if operation == "scan":
        body["context"] = "inventory_check"
    return case.client.post(reverse(f"qr-{operation}"), body, format="json", **headers)


def native_form(client, admin_name, obj=None, **changes):
    url = reverse(f"admin:{admin_name}_{'change' if obj else 'add'}", args=[obj.pk] if obj else [])
    page = client.get(url)
    assert page.status_code == 200
    data = page_data(page)
    data.update(changes)
    data["_save"] = "Save"
    return url, data


def fail_after_insert(monkeypatch, action):
    """Exercise a real audit INSERT before simulating its caller's refusal."""
    real_record, inserted = audit.record, []

    def failing(actor, event, **kwargs):
        row = real_record(actor, event, **kwargs)
        if event == action:
            assert AuditLog.objects.filter(pk=row.pk).exists()
            inserted.append(row.pk)
            raise RuntimeError("Stage3 refusal after real audit INSERT")
        return row

    monkeypatch.setattr(audit, "record", failing)
    return inserted


@pytest.fixture
def qr_lab(settings, monkeypatch):
    configure(settings)
    calls = []

    def unexpected_provider(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("QR/native form flow must not enter a provider")

    monkeypatch.setattr("boto3.client", unexpected_provider)
    home, other = space(), space()
    actor = staff(home)
    case = SimpleNamespace(
        home=home, other=other, actor=actor, client=jwt_client(actor), provider_calls=calls,
        batch=QrPrintBatch.objects.create(makerspace=home, title="Stage3", created_by=actor),
    )
    yield case
    assert calls == []
