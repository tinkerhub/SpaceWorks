"""Real PostgreSQL competitors; existing event-coordinated workers own connections."""
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.boxes.models import BoxScan, QrScanEvent
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.integrations import notify
from apps.integrations.models import EmailLog
from tests.atomic_publication.store import png
from tests.box_parent_safety.pg_helpers import blocked_by, workers
from tests.inventory_lending_evidence_helpers import photo as uploaded_photo, uploaded_images
from tests.test_request_workflow import authenticated_client, make_hardware_request
from tests.hardware_requests.cancellation_support import (
    accept, accepted_lab, assignment, buckets, cancel_url,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def physical_lab(monkeypatch, settings):
    # Migration seed is legitimately recreated after TransactionTestCase flush;
    # production's identity loader must remain read-only and fail closed.
    DeploymentDatabaseIdentity.objects.get_or_create(pk=1)
    # Suppress only outbound transports, including acceptance's immediate commit.
    monkeypatch.setattr(notify, "dispatch_email",
                        lambda **kwargs: SimpleNamespace(status=EmailLog.Status.SENT))
    monkeypatch.setattr(notify, "dispatch_channel", lambda **kwargs: [])
    store = uploaded_images(monkeypatch, settings)
    lab = accepted_lab()
    lab.store = store
    lab.evidence = uploaded_photo(lab, store, "issue")
    assignment(lab)
    return lab


def row_lock(table, pk):
    def matches(statement):
        return (f'FROM "{table}"' in statement.sql and " FOR " in statement.sql
                and pk in statement.params)
    return matches


def post_as(actor_id, path, body):
    # Each worker resolves a fresh actor and owns its own authenticated HTTP client.
    actor = User.objects.get(pk=actor_id)
    return authenticated_client(actor).post(path, body, format="json")


def immutable_rows():
    return {model: list(model.objects.order_by("pk").values())
            for model in (EvidencePhoto, BoxScan, QrScanEvent)}


def finish_workers(*owned):
    """Release every peer and propagate every exception after both have settled."""
    for worker in owned:
        worker.release.set()
    results, errors = [], []
    for worker in owned:
        try:
            results.append(worker.finish())
        except BaseException as error:
            errors.append(error)
    if errors:
        raise BaseExceptionGroup("Cancellation competitors failed", errors)
    return results


@pytest.mark.parametrize("winner", ["issue", "cancel"])
def test_same_request_serializes_issue_and_cancel_with_one_winner(physical_lab, winner):
    lab = physical_lab
    before = immutable_rows()
    request_lock = row_lock("hardware_requests_hardwarerequest", lab.request.pk)
    operations = {
        "issue": lambda: post_as(lab.actor.pk, f"/api/v1/admin/requests/{lab.request.pk}/issue",
                                  {"evidence_id": lab.evidence.pk, "remark": "Real handover"}),
        "cancel": lambda: post_as(lab.actor.pk, cancel_url(lab.request),
                                   {"reason": "Cancelled before handover"}),
    }
    loser = "cancel" if winner == "issue" else "issue"
    with workers() as start:
        first = start(operations[winner], pause=request_lock)
        first.paused()  # A real completed SELECT FOR UPDATE holds the common row.
        second = start(operations[loser])
        pending = blocked_by(second, first.pid, request_lock)
        assert not pending.completed
        won, lost = finish_workers(first, second)
        assert (won.status_code, lost.status_code) == (200, 409), (won.content, lost.content)
        assert pending.completed
    assert immutable_rows() == before
    lab.request.refresh_from_db()
    if winner == "issue":
        assert lab.request.status == "issued"
        assert lab.request.issue_evidence_id == lab.evidence.pk
        assert buckets(lab.product) == (6, 0, 2, 8)
        assert not AuditLog.objects.filter(action="request.cancelled").exists()
        assert AuditLog.objects.filter(action="request.issued", target_id=str(lab.request.pk)).count() == 1
    else:
        assert lab.request.status == "cancelled"
        assert lab.request.issue_evidence_id is None
        assert buckets(lab.product) == (8, 0, 0, 8)
        assert not AuditLog.objects.filter(action="request.issued").exists()
        assert AuditLog.objects.filter(action="request.cancelled", target_id=str(lab.request.pk)).count() == 1
    # The losing issue may validly promote before admission; promotion is real,
    # durable and never permits deletion of the uploaded evidence metadata.
    journal = EvidenceUploadFinalization.objects.get(evidence=lab.evidence)
    assert (journal.status, journal.size_bytes) == ("finalized", len(png()))
    assert lab.store.objects[lab.evidence.object_key][:2] == (png(), "image/png")
    assert any(name == "copy" for name, _ in lab.store.calls)


def test_distinct_requests_share_box_and_product_without_lock_inversion(physical_lab):
    lab = physical_lab
    issuing = lab.request
    cancelling = make_hardware_request(lab.space, lab.product, quantity=2)
    accept(lab.client, cancelling)
    # Both accepted assignments are legitimate: a box is exclusive only once out.
    lab.request = cancelling
    box = issuing.assigned_box
    # physical_lab's assignment refreshed the request, so its FK is concrete.
    response = lab.client.post(f"/api/v1/admin/requests/{cancelling.pk}/assign-box",
                               {"box_code": box.code}, format="json")
    assert response.status_code == 200, response.content
    before = immutable_rows()
    box_lock = row_lock("boxes_box", box.pk)
    with workers() as start:
        issue = start(lambda: post_as(lab.actor.pk,
            f"/api/v1/admin/requests/{issuing.pk}/issue", {"evidence_id": lab.evidence.pk}),
            pause=box_lock)
        issue.paused()  # Actual issue owns Box, and has not yet acquired Product.
        cancel = start(lambda: post_as(lab.actor.pk, cancel_url(cancelling),
                                       {"reason": "Other request no longer needed"}))
        pending = blocked_by(cancel, issue.pid, box_lock)
        # Releasing at the observed Box wait exposes product->box inversion: if
        # cancellation already owns Product, real PostgreSQL must detect deadlock.
        issued_response, cancelled_response = finish_workers(issue, cancel)
        assert (issued_response.status_code, cancelled_response.status_code) == (200, 200), (
            issued_response.content, cancelled_response.content,
        )
        assert pending.completed
    issuing.refresh_from_db()
    cancelling.refresh_from_db()
    assert (issuing.status, cancelling.status) == ("issued", "cancelled")
    assert issuing.assigned_box_id == box.pk and cancelling.assigned_box_id is None
    assert buckets(lab.product) == (6, 0, 2, 8)
    assert immutable_rows() == before
    assert AuditLog.objects.filter(action="request.issued", target_id=str(issuing.pk)).count() == 1
    assert AuditLog.objects.filter(action="request.cancelled", target_id=str(cancelling.pk)).count() == 1
