"""Real lending producers and byte-valid evidence for HW001 boundary tests."""
from types import SimpleNamespace

from apps.audit.models import AuditLog
from apps.evidence import storage
from apps.evidence.models import EvidenceUploadFinalization
from apps.hardware_requests import workflow
from apps.hardware_requests.models import PublicProblemReport, PublicToolLoan, ReturnEvent
from apps.makerspaces import limits
from tests.atomic_publication.store import png
from tests.inventory_lending_evidence_helpers import domain_snapshot, photo, uploaded_images
from tests.inventory_lending_helpers import submit_request
from tests.return_helpers import authenticated_client, make_member, make_product, make_space
from tests.test_public_self_checkout import checkout_url, eligible_member, make_qr


def make_boundary_lab(monkeypatch, settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    settings.MANAGED_RESOURCE_LIMITS = {**settings.MANAGED_RESOURCE_LIMITS, "storage": 1_000_000}
    # Use originless local API requests, but enable real managed PUT quota accounting
    # (the documented limits seam); no workflow/availability/permission is replaced.
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    space = make_space("loan-return-boundary")
    actor = make_member("boundary-manager", space)
    borrower = eligible_member(space, "boundary-borrower")
    lab = SimpleNamespace(
        space=space, actor=actor, borrower=borrower,
        product=make_product(space, total_quantity=8, available_quantity=8,
                             public_self_checkout_enabled=True),
        client=authenticated_client(actor),
    )
    lab.store = uploaded_images(monkeypatch, settings)
    settings.STORAGE_PRESIGN_METHOD = "put"
    return lab


def uploaded_photo(lab, kind="return", *, actor=None):
    return photo(SimpleNamespace(space=lab.space, actor=actor or lab.actor), lab.store, kind)


def checkout_public(lab, *, borrower=None, count=1):
    """One real public batch, with one unique active product QR per product."""
    borrower = borrower or lab.borrower
    products = [lab.product] + [make_product(
        lab.space, name=f"Boundary additional tool {index}", total_quantity=8,
        available_quantity=8, public_self_checkout_enabled=True,
    ) for index in range(1, count)]
    lab.batch_products = products
    qrs = [make_qr(lab.space, product) for product in products]
    evidence = uploaded_photo(lab, "issue", actor=borrower)
    response = authenticated_client(borrower).post(checkout_url(lab.space), {
        "qr_payloads": [qr.payload for qr in qrs], "evidence_id": evidence.pk,
    }, format="json")
    assert response.status_code == 201, response.data
    # Public responses deliberately expose a request token rather than an internal ID.
    loan = PublicToolLoan.objects.get(request__public_token=response.data["public_token"])
    assert loan.source == PublicToolLoan.Source.PUBLIC_SELF_CHECKOUT
    assert sum(loan.request.items.values_list("issued_quantity", flat=True)) == count
    assert EvidenceUploadFinalization.objects.get(evidence=evidence).quota_charged
    return loan, qrs


def checkout_direct(lab, *, borrower=None, quantity=2):
    evidence = uploaded_photo(lab, "issue")
    response = lab.client.post(f"/api/v1/admin/makerspace/{lab.space.pk}/direct-loans", {
        "borrower_id": (borrower or lab.borrower).pk, "evidence_id": evidence.pk,
        "remark": "Staff witnessed handover.",
        "items": [{"product_id": lab.product.pk, "quantity": quantity}],
    }, format="json")
    assert response.status_code == 201, response.data
    loan = PublicToolLoan.objects.get(pk=response.data["id"])
    assert loan.source == PublicToolLoan.Source.ADMIN_DIRECT
    assert loan.request.items.get().issued_quantity == quantity
    assert EvidenceUploadFinalization.objects.get(evidence=evidence).quota_charged
    return loan


def checkout_reviewed(lab):
    request = submit_request(lab, suffix="boundary-reviewed")
    request = workflow.accept_request(lab.actor, request)
    evidence = uploaded_photo(lab, "issue")
    return workflow.issue_request(lab.actor, request, evidence.pk, "Verified two units.")


def resolutions(request):
    return [{"item_id": item.pk, "returned": item.issued_quantity,
             "damaged": 0, "missing": 0} for item in request.items.order_by("pk")]


def reviewed_body(request, evidence):
    return {"evidence_id": evidence.pk, "remark": "Checked condition.",
            "box_code": "", "resolutions": resolutions(request)}


def boundary_snapshot(lab, *, finalizations=True):
    state = domain_snapshot(lab)
    for model in (PublicToolLoan, PublicProblemReport, AuditLog):
        state[model.__name__] = list(model.objects.filter(
            makerspace=lab.space,
        ).order_by("pk").values())
    lab.space.refresh_from_db()
    state["storage_bytes_used"] = lab.space.storage_bytes_used
    if finalizations:
        state["finalizations"] = list(EvidenceUploadFinalization.objects.filter(
            evidence__makerspace=lab.space,
        ).order_by("pk").values())
    return state


def assert_unpromoted(lab, evidence, before, calls):
    assert boundary_snapshot(lab) == before
    assert lab.store.calls == calls
    assert storage.staging_key(evidence.object_key) in lab.store.objects
    assert evidence.object_key not in lab.store.objects
    assert not EvidenceUploadFinalization.objects.filter(evidence=evidence).exists()


def assert_promoted_unattached(lab, evidence):
    assert evidence.object_key in lab.store.objects
    assert storage.staging_key(evidence.object_key) not in lab.store.objects
    state = EvidenceUploadFinalization.objects.get(evidence=evidence)
    assert state.status == EvidenceUploadFinalization.Status.FINALIZED
    assert state.size_bytes == len(png()) and state.content_type == "image/png"
    assert state.quota_charged is False
    assert not PublicToolLoan.objects.filter(return_evidence=evidence).exists()
    assert not ReturnEvent.objects.filter(evidence=evidence).exists()


def change_after_finalization(monkeypatch, lab, evidence, change, queries):
    """Deterministic I/O interleaving, not a concurrent-transaction/lock proof.

    Delegate real promotion, then simulate state visible when the workflow starts
    its domain transaction. Only this photo triggers the supplied state change.
    """
    real_finalize = storage.finalize_upload
    observed = []

    def finalize(photo, max_bytes):
        result = real_finalize(photo, max_bytes)
        if photo.pk == evidence.pk:
            assert result is not None
            change()
            observed.append({"state": boundary_snapshot(lab, finalizations=False),
                             "query_offset": len(queries.captured_queries)})
        return result

    monkeypatch.setattr(storage, "finalize_upload", finalize)
    return observed


def assert_no_settlement_writes(queries):
    """Inspect attempted SQL too: rollback alone cannot prove admission preceded debit."""
    forbidden_tables = (
        "hardware_requests_hardwarerequest", "hardware_requests_hardwarerequestitem",
        "hardware_requests_publictoolloan", "hardware_requests_returnevent",
        "hardware_requests_requesteraccountability", "inventory_inventoryproduct",
        "boxes_boxscan", "boxes_qrscanevent", "audit_auditlog",
    )
    for query in queries:
        sql = query["sql"].lstrip().lower()
        if not sql.startswith(("insert ", "update ", "delete ")):
            continue
        assert not any(f'"{table}"' in sql for table in forbidden_tables), sql
        assert not (sql.startswith("update ") and any(
            column in sql for column in ('"quota_charged"', '"storage_bytes_used"')
        )), sql


def associate_loan(request):
    """Adversarial association on genuinely issued stock; no quantity fabrication."""
    return PublicToolLoan.objects.create(
        makerspace=request.makerspace, request=request, requester=request.requester,
        source=PublicToolLoan.Source.ADMIN_DIRECT, target_type="direct",
        target_id=request.pk, target_label="Association introduced at the return boundary",
    )


def buckets(product):
    product.refresh_from_db()
    fields = ("available_quantity", "reserved_quantity", "issued_quantity",
              "damaged_quantity", "lost_quantity", "needs_fix_quantity")
    values = tuple(getattr(product, field) for field in fields)
    assert min(values) >= 0 and sum(values) == product.total_quantity
    return values
