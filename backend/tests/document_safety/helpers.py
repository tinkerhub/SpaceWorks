"""Real staff JWT/API fixtures; only the provider transport is replaced."""
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from django.db import connection
from django.urls import reverse
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.machines.models import Machine, MachineType
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.module_registry import with_dependencies
from apps.makerspaces.roles import ensure_default_roles
from apps.procurement import storage as receipts
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from apps.warranty import storage as documents
from apps.warranty.models import Warranty, WarrantyDocument
from tests.atomic_publication.store import Store, png
from tests.return_helpers import make_product


def jwt_client(actor):
    token = SpaceWorksRefreshToken.for_user(actor)
    token["surface"] = "staff_api"
    client = APIClient(HTTP_HOST="testserver")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def member(space, role="space_manager"):
    ensure_default_roles(space)
    user = User.objects.create_user(
        username=f"document-{uuid4().hex[:12]}", role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    assigned = MakerspaceRole.objects.get(makerspace=space, slug=role)
    MakerspaceMembership.objects.create(
        makerspace=space, user=user, role=role, assigned_role=assigned,
    )
    return user


def space():
    slug = f"document-{uuid4().hex[:12]}"
    return Makerspace.objects.create(
        name=slug, slug=slug, frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
        enabled_modules=sorted(with_dependencies(
            {"staff_admin", "machines", "procurement", "qr_management"},
        )),
        resource_limit_overrides={"storage": 1000000},
    )


def asset(space, tag="A1"):
    product = make_product(
        space, tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1, available_quantity=1,
    )
    return InventoryAsset.objects.create(makerspace=space, product=product, asset_tag=tag)


def machine(space):
    kind = MachineType.objects.create(makerspace=space, name="Laser", slug="laser")
    return Machine.objects.create(makerspace=space, machine_type=kind, name="Laser")


def configure(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    settings.PLATFORM_STAFF_ORIGINS = []
    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.PROCUREMENT_RECEIPT_MAX_BYTES = 100000
    settings.WARRANTY_DOC_MAX_BYTES = 100000
    settings.PROCUREMENT_RECEIPT_ALLOWED_MIME = ["application/pdf", "image/png"]
    settings.WARRANTY_DOC_ALLOWED_MIME = ["application/pdf", "image/png"]
    assert not limits.is_self_host()


class DocumentStore(Store):
    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self._call("presign-put", dict(operation=operation, **Params, ttl=ExpiresIn))
        return "https://objects.example.test/upload"

    def generate_presigned_post(self, **kwargs):
        self._call("presign-post", kwargs)
        return {"url": "https://objects.example.test/upload", "fields": kwargs["Fields"]}


def lab(monkeypatch, settings, kind="receipt"):
    configure(settings)
    # Production migration seeds this singleton; transaction=True flush removes it.
    # Provision only this document lab, preserving missing-identity evidence tests.
    DeploymentDatabaseIdentity.objects.get_or_create(pk=1)
    home, other = space(), space()
    actor = member(home)
    if kind == "receipt":
        target = ToBuyItem.objects.create(makerspace=home, kind="hardware", name="Drill")
        module, model = receipts, ToBuyReceipt
        create_name, prefix = "procurement:to-buy-receipt-list", "procurement:to-buy-receipt"
        module_key = "procurement"
    else:
        host = asset(home) if kind == "asset" else machine(home)
        target = Warranty.objects.create(makerspace=home, **{kind: host})
        module, model = documents, WarrantyDocument
        create_name, prefix = "admin-warranty-documents", "admin-warranty-document"
        module_key = "staff_admin" if kind == "asset" else "machines"
    store = DocumentStore()
    monkeypatch.setattr(module, "_client", lambda: store)
    monkeypatch.setattr(module, "_public_client", lambda: store)
    return SimpleNamespace(
        home=home, other=other, actor=actor, target=target, module=module, model=model,
        module_key=module_key, store=store, client=jwt_client(actor), prefix=prefix,
        url=reverse(create_name, kwargs={"pk": target.pk}),
    )


def accepted_body(mime, variant=False):
    if mime == "image/png":
        if not variant:
            return png()
        stream = BytesIO()
        metadata = PngInfo()
        metadata.add_text("Winner", "A different validated final snapshot size")
        Image.new("RGB", (17, 13), "red").save(stream, format="PNG", pnginfo=metadata)
        return stream.getvalue()
    # Complete one-page PDF without an optional test dependency.
    content = b"BT /F1 12 Tf 10 30 Td (Winner with different size) Tj ET" if variant else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result, offsets = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return result + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


def presign(case, mime="application/pdf"):
    ext = "pdf" if mime == "application/pdf" else "png"
    response = case.client.post(
        reverse(f"{case.prefix}-presign", kwargs={"pk": case.target.pk}),
        {"filename": f"bill.{ext}", "content_type": mime}, format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["object_key"], response.data["upload"]


def payload(key):
    return {"object_key": key, "original_filename": "bill.pdf"}


def finalize(case, key, **headers):
    return case.client.post(case.url, payload(key), format="json", **headers)


def usage(case):
    return Makerspace.objects.values_list("storage_bytes_used", flat=True).get(pk=case.home.pk)


def cap(case, size, used=0):
    case.home.resource_limit_overrides = {"storage": size}
    case.home.storage_bytes_used = used
    case.home.save(update_fields=["resource_limit_overrides", "storage_bytes_used"])
    assert limits.resource_limit(case.home, "storage") == size


def snapshot(case):
    return (list(case.model.objects.order_by("pk").values()), usage(case),
            list(AuditLog.objects.order_by("pk").values()))


def assert_storage_boundary(case):
    """Observe real dedicated locks at every provider call, outside app atomic."""
    assert connection.vendor == "postgresql"
    assert connection.get_autocommit() and not connection.in_atomic_block
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT classid, mode FROM pg_locks WHERE locktype='advisory' "
            "AND objid=%s AND objsubid=2 AND granted AND pid<>pg_backend_pid()",
            [case.home.pk],
        )
        held = set(cursor.fetchall())
    assert (734310, "ShareLock") in held, held
    assert (734312, "ExclusiveLock") in held, held


def fail_after_audit(monkeypatch, action):
    real_record = audit.record
    inserted = []

    def failing(actor, event, **kwargs):
        result = real_record(actor, event, **kwargs)
        if event == action:
            assert AuditLog.objects.filter(action=action).exists()
            inserted.append(result)
            raise RuntimeError("failure after real audit INSERT")
        return result

    monkeypatch.setattr(audit, "record", failing)
    return real_record, inserted
