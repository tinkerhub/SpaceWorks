"""Committed legitimate lending fixtures; no imports from the unfrozen box tests."""
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.evidence import storage
from apps.evidence.models import EvidenceUploadFinalization
from apps.hardware_requests.models import PublicProblemReport, PublicToolLoan, ReturnEvent
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.makerspaces import limits
from apps.presence.services import start_session
from tests.atomic_publication.store import png
from tests.inventory_lending_evidence_helpers import photo, uploaded_images
from tests.inventory_lending_helpers import make_lab, submit_request
from tests.return_helpers import return_url as reviewed_return_url
from tests.test_issue import assign_box_url, issue_url
from tests.test_request_workflow import accept_url


def client(lab):
    """Materialize an actor and API client in the calling worker's own session."""
    actor = get_user_model().objects.get(pk=lab.actor.pk)
    result = APIClient(HTTP_HOST="testserver")
    result.force_authenticate(user=actor)
    return result


def setup_lab(monkeypatch, settings, transport, *, individual=False, total=1):
    # Transactional flush removes the migration seed. Evidence only reads this
    # infrastructure identity; provision it here before exercising real quota.
    DeploymentDatabaseIdentity.load()
    lab = make_lab(
        monkeypatch, settings, total=total,
        tracking_mode=TrackingMode.INDIVIDUAL if individual else TrackingMode.QUANTITY,
    )
    lab.store = uploaded_images(monkeypatch, settings)
    settings.STORAGE_PRESIGN_METHOD = transport
    # Use the real managed-platform policy and a finite cap. No quota seam is mocked.
    settings.PLATFORM_DOMAIN_SUFFIX = "race.example.test"
    settings.INFRA_HOSTS = {*settings.INFRA_HOSTS, "testserver"}
    lab.client.defaults["HTTP_HOST"] = "testserver"
    lab.space.resource_limit_overrides = {"storage": len(png()) * 32}
    lab.space.enabled_features = list(set(lab.space.enabled_features) | {"inventory.self_checkout"})
    lab.space.save(update_fields=["resource_limit_overrides", "enabled_features"])
    assert not limits.is_self_host()
    assert limits.resource_limit(lab.space, "storage") == len(png()) * 32
    lab.product.public_self_checkout_enabled = True
    lab.product.save(update_fields=["public_self_checkout_enabled"])
    InventoryAsset.objects.filter(product=lab.product).update(public_self_checkout_enabled=True)
    start_session(lab.actor, lab.space, 60)
    lab.transport = transport
    return lab


def container(lab, *, contents=True):
    box = Box.objects.create(makerspace=lab.space, label="Race case")
    qr = QrCode.objects.create(
        makerspace=lab.space, target_type=QrCode.TargetType.BOX,
        target_id=box.pk, payload=box.code, created_by=lab.actor,
    )
    if contents:
        lab.product.box = box
        lab.product.save(update_fields=["box"])
        InventoryAsset.objects.filter(product=lab.product).update(box=box)
    return box, qr


def product_qr(lab):
    return QrCode.objects.create(
        makerspace=lab.space, target_type=QrCode.TargetType.PRODUCT,
        target_id=lab.product.pk, created_by=lab.actor,
    )


def issue_post(lab, url, payload):
    """Capture real Maker lock SQL, including add_storage's finite-cap PUT lock."""
    maker_locks = []
    prior_charge = None

    def capture(execute, sql, params, many, context):
        nonlocal prior_charge
        maker_lock = 'FROM "makerspaces_makerspace"' in sql and "FOR " in sql
        if maker_lock:
            maker_locks.append(sql)
        result = execute(sql, params, many, context)
        if maker_lock and prior_charge is None:
            # The real domain lock has now completed, after the Evidence locks.
            # A competing triage may have charged this shared image while this
            # request waited; an earlier unlocked snapshot would be stale.
            prior_charge = EvidenceUploadFinalization.objects.values_list(
                "quota_charged", flat=True,
            ).get(evidence_id=payload["evidence_id"])
        return result

    with connection.execute_wrapper(capture):
        response = client(lab).post(url, payload, format="json")
    if response.status_code in (200, 201):
        assert maker_locks and all("FOR NO KEY UPDATE" in sql for sql in maker_locks), maker_locks
        if lab.transport == "put" and prior_charge is False:
            # First charge takes both actual locks. A shared image already charged
            # by triage correctly skips add_storage while retaining the domain lock.
            assert len(maker_locks) >= 2, maker_locks
    return response


def public_checkout(lab, qr, evidence):
    return issue_post(lab, f"/api/v1/public/{lab.space.slug}/tools/checkout", {
        "payload": qr.payload, "evidence_id": evidence.pk, "remark": "Race handover",
    })


def direct_checkout(lab, box, qr, evidence):
    return issue_post(lab, f"/api/v1/admin/makerspace/{lab.space.pk}/direct-loans", {
        "borrower_id": lab.actor.pk, "container_id": box.pk,
        "qr_payloads": [qr.payload], "evidence_id": evidence.pk, "remark": "Race handover",
    })


def accept_and_assign(lab, box):
    request = submit_request(lab, quantity=1)
    response = lab.client.post(accept_url(request), {}, format="json")
    assert response.status_code == 200, response.data
    response = lab.client.post(assign_box_url(request), {"box_code": box.code}, format="json")
    assert response.status_code == 200, response.data
    request.refresh_from_db()
    assert request.status == "accepted" and request.assigned_box_id == box.pk
    stock(lab, lab.total - 1, 1, 0)
    return request


def reviewed_issue(lab, request, qr, evidence):
    return issue_post(lab, issue_url(request), {
        "evidence_id": evidence.pk, "asset_qr_payloads": [qr.payload], "remark": "Race handover",
    })


def stock(lab, available, reserved, issued):
    lab.product.refresh_from_db()
    fields = ("available_quantity", "reserved_quantity", "issued_quantity")
    assert tuple(getattr(lab.product, field) for field in fields) == (available, reserved, issued)
    assert lab.product.total_quantity == available + reserved + issued == lab.total
    assert min(available, reserved, issued) >= 0
    assert all(getattr(lab.product, field) == 0 for field in (
        "damaged_quantity", "lost_quantity", "needs_fix_quantity",
    ))
    if lab.assets:
        statuses = list(InventoryAsset.objects.filter(product=lab.product).values_list("status", flat=True))
        assert statuses.count("issued") == issued
        assert statuses.count("available") == available + reserved


def quota(lab, charged):
    lab.space.refresh_from_db()
    assert lab.space.storage_bytes_used == (charged * len(png()) if lab.transport == "put" else 0)
    states = EvidenceUploadFinalization.objects.filter(evidence__makerspace=lab.space)
    assert states.filter(quota_charged=True).count() == (charged if lab.transport == "put" else 0)


def finalized(lab, evidence, *, charged):
    state = EvidenceUploadFinalization.objects.get(evidence=evidence)
    assert state.status == "finalized" and state.size_bytes == len(png())
    assert state.content_type == "image/png"
    assert state.quota_charged == (charged and lab.transport == "put")
    assert lab.store.objects[evidence.object_key][0] == png()
    assert storage.staging_key(evidence.object_key) not in lab.store.objects


def loan_trace(lab, loan, qr, evidence, *, direct, box=None, asset=None):
    loan.refresh_from_db()
    request = loan.request
    assert loan.status == "checked_out" and request.status == "issued"
    assert loan.source == ("admin_direct" if direct else "public_self_checkout")
    assert loan.container_id == (box.pk if box else None)
    assert loan.qr_code_id == qr.pk and loan.qr_ids == [qr.pk]
    assert loan.asset_ids == ([asset.pk] if asset else [])
    assert loan.requester_id == request.requester_id == lab.actor.pk
    assert request.issue_evidence_id == evidence.pk and request.issue_remark == "Race handover"
    assert request.issued_by_id == lab.actor.pk and request.issued_at is not None
    assert request.assigned_box_id is None
    item = request.items.get()
    expected_product = qr.target_id if qr.target_type == "product" else lab.product.pk
    assert item.product_id == expected_product
    assert (item.requested_quantity, item.accepted_quantity, item.issued_quantity, item.returned_quantity) == (1, 1, 1, 0)
    scan = QrScanEvent.objects.get(request=request, context="issue")
    assert scan.qr_code_id == qr.pk and scan.actor_id == lab.actor.pk
    action = "admin_direct.checked_out" if direct else "public_tool.checked_out"
    entry = AuditLog.objects.get(makerspace=lab.space, action=action)
    assert entry.actor_id == lab.actor.pk
    if direct:
        assert entry.meta["loan_id"] == loan.pk
        attached = AuditLog.objects.get(action="evidence.attached", target_id=str(request.pk))
        assert attached.meta["evidence_id"] == evidence.pk
    else:
        assert entry.target_id == str(request.pk) and entry.meta["qr_id"] == qr.pk
    finalized(lab, evidence, charged=True)


def return_public(lab, qr, *, evidence=None, report=False):
    evidence = evidence or photo(lab, lab.store, "return")
    response = client(lab).post(f"/api/v1/public/{lab.space.slug}/tools/return", {
        "payload": qr.payload, "evidence_id": evidence.pk, "remark": "Inspected at return",
        "report_problem": report, "problem_note": "Inspect tip" if report else "",
    }, format="json")
    assert response.status_code == 200, response.data
    loan = PublicToolLoan.objects.get(
        makerspace=lab.space, request__public_token=response.data["public_token"],
    )
    assert loan.status == "returned" and loan.request.status == "returned"
    assert loan.return_evidence_id == evidence.pk and loan.return_notes == "Inspected at return"
    assert QrScanEvent.objects.filter(request=loan.request, context="return", qr_code=qr).count() == 1
    assert AuditLog.objects.filter(action="public_tool.returned", target_id=str(loan.request_id)).count() == 1
    return loan


def returned_report(lab, qr):
    image = photo(lab, lab.store, "issue")
    response = public_checkout(lab, qr, image)
    assert response.status_code == 201, response.data
    loan = return_public(lab, qr, report=True)
    report = PublicProblemReport.objects.get(loan=loan)
    assert report.request_id == loan.request_id and report.resolved_at is None
    stock(lab, lab.total, 0, 0)
    return report


def triage(lab, report, evidence):
    return client(lab).post(
        f"/api/v1/admin/makerspace/{lab.space.pk}/problem-reports/{report.pk}/triage",
        {"outcome": "no_issue", "resolutions": [], "note": "Inspected; no defect",
         "evidence_id": evidence.pk}, format="json",
    )


def return_direct(lab, loan, qr):
    evidence = photo(lab, lab.store, "return")
    response = client(lab).post(f"/api/v1/admin/direct-loans/{loan.pk}/return", {
        "evidence_id": evidence.pk, "notes": "Inspected at return", "qr_payload": qr.payload,
        "resolutions": [{"item_id": loan.request.items.get().pk, "returned": 1}],
    }, format="json")
    assert response.status_code == 200, response.data
    loan.refresh_from_db()
    assert loan.status == "returned" and loan.request.status == "returned"
    assert loan.return_evidence_id == evidence.pk
    assert ReturnEvent.objects.get(request=loan.request).evidence_id == evidence.pk
    assert QrScanEvent.objects.filter(request=loan.request, context="return", qr_code=qr).count() == 1
    assert AuditLog.objects.filter(
        makerspace=lab.space, action="admin_direct.returned", meta__loan_id=loan.pk,
    ).count() == 1
    finalized(lab, evidence, charged=True)


def return_reviewed(lab, request, box, asset):
    evidence = photo(lab, lab.store, "return")
    response = client(lab).post(reviewed_return_url(request), {
        "evidence_id": evidence.pk, "remark": "Inspected at return", "box_code": box.code,
        "resolutions": [{"item_id": request.items.get().pk, "returned": 1,
                         "assets": [{"asset_id": asset.pk, "outcome": "returned"}]}],
    }, format="json")
    assert response.status_code == 200, response.data
    request.refresh_from_db()
    assert request.status == "returned"
    event = ReturnEvent.objects.get(request=request)
    assert event.evidence_id == evidence.pk and event.box_id == box.pk
    link = request.items.get().asset_links.get()
    assert link.asset_id == asset.pk and link.outcome == "returned" and link.return_event_id == event.pk
    assert AuditLog.objects.filter(action="request.returned", target_id=str(request.pk)).count() == 1
    assert QrScanEvent.objects.filter(request=request, context="return", qr_code=lab.qrs[0]).count() == 1
    finalized(lab, evidence, charged=True)
