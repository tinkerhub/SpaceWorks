"""Persisted-state and real HTTP fixtures for the frozen OPS-S01–S03 source."""
from types import SimpleNamespace

from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode
from apps.inventory.models import Category, InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles
from apps.operations.models import InventoryAdjustment, QrPrintBatch, QrPrintBatchItem


def jwt_client(actor):
    token = SpaceWorksRefreshToken.for_user(actor)
    token["surface"] = "staff_api"
    client = APIClient(HTTP_HOST="testserver")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def qr_lab(settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    settings.PLATFORM_STAFF_ORIGINS = []
    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
    home = Makerspace.objects.create(
        name="QR safety home", slug="qr-safety-home",
        resource_limit_overrides={"assets": 20},
    )
    other = Makerspace.objects.create(name="QR safety other", slug="qr-safety-other")
    actor = User.objects.create_user(username="qr-safety-inventory", role=User.Role.REQUESTER)
    ensure_default_roles(home)
    role = MakerspaceRole.objects.get(makerspace=home, slug="inventory_manager")
    MakerspaceMembership.objects.create(
        makerspace=home, user=actor, role="inventory_manager", assigned_role=role,
    )
    return SimpleNamespace(home=home, other=other, actor=actor, client=jwt_client(actor))


def product(lab, *, space=None, name="Safety drill", **kwargs):
    return InventoryProduct.objects.create(
        makerspace=space or lab.home, name=name, tracking_mode=TrackingMode.INDIVIDUAL,
        **kwargs,
    )


def asset(item, tag="QR-SAFETY-1", **kwargs):
    return InventoryAsset.objects.create(
        makerspace=item.makerspace, product=item, asset_tag=tag, **kwargs,
    )


def qr(lab, target):
    return QrCode.objects.create(
        makerspace=target.makerspace, created_by=lab.actor, target_id=target.pk,
        target_type=QrCode.TargetType.ASSET if isinstance(target, InventoryAsset)
        else QrCode.TargetType.PRODUCT,
    )


def batch(lab, **kwargs):
    return QrPrintBatch.objects.create(
        makerspace=lab.home, created_by=lab.actor, title="Safety labels", **kwargs,
    )


def generate(lab, item, **data):
    return lab.client.post(
        f"/api/v1/admin/products/{item.pk}/assets/generate",
        {"count": 1, **data}, format="json",
    )


def add_item(lab, labels, code, **data):
    return lab.client.post(
        f"/api/v1/admin/qr-print-batches/{labels.pk}/items",
        {"qr_code_id": code.pk, **data}, format="json",
    )


def create_batch(lab, title):
    return lab.client.post(
        f"/api/v1/admin/makerspace/{lab.home.pk}/qr-print-batches",
        {"title": title}, format="json",
    )


def state():
    # Complete rows include quantity buckets, quota configuration/storage charge,
    # target snapshots and timestamps, so an UPDATE cannot hide behind stable counts.
    return {
        model._meta.label: list(model.objects.order_by("pk").values())
        for model in (
            Makerspace, Category, InventoryProduct, InventoryAsset, Box, QrCode,
            QrPrintBatch, QrPrintBatchItem, InventoryAdjustment, AuditLog,
        )
    }


def audit_ids():
    return set(AuditLog.objects.values_list("pk", flat=True))


def new_events(before):
    return AuditLog.objects.exclude(pk__in=before).order_by("pk")


def assert_event(event, lab, action, target, *, actor=None):
    assert (event.action, event.actor_id, event.makerspace_id) == (
        action, (actor or lab.actor).pk, lab.home.pk,
    )
    assert (event.target_type, event.target_id) == (
        target._meta.label_lower, str(target.pk),
    )


def item_updates(queries):
    table = QrPrintBatchItem._meta.db_table
    return [entry["sql"] for entry in queries if entry["sql"].startswith(f'UPDATE "{table}"')]
