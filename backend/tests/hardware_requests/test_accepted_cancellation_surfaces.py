"""Reason validation, guarded control review, and honest offline notification sinks."""
from types import SimpleNamespace

import pytest
from django.contrib.messages import get_messages

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.data_export.pii_raw import aad_inputs, raw_value
from apps.encryption.crypto import PiiAuthenticationFailed, decrypt, parse_envelope
from apps.encryption.services import get_dek
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.integrations import notify
from apps.integrations.models import (
    EmailLog, NotificationChannel, NotificationDeliveryStatus, NotificationPreference,
)
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.materialization import materialize_tenant
from tests.data_export.portable_helpers import csv_rows, make_space
from tests.encryption.conftest import enabled_encryption
from tests.hardware_requests.test_accepted_cancellation_encryption import raw_reason
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.test_hardware_admin_actions import (
    action_payload, admin_client, changelist_url, make_superadmin, review_url,
)
from tests.test_request_workflow import history_url
from tests.hardware_requests.cancellation_support import (
    accepted_lab, assignment, buckets, cancel_url, snapshot,
)

pytestmark = pytest.mark.django_db


def test_invalid_reason_returns_400_without_any_effects():
    lab = accepted_lab()
    before = snapshot()
    for body in ({}, {"reason": None}, {"reason": ""}, {"reason": " \t\n "},
                 {"reason": "x" * 501}, {"reason": []}):
        response = lab.client.post(cancel_url(lab.request), body, format="json")
        assert response.status_code == 400, response.content
        assert snapshot() == before


@pytest.mark.parametrize("length", [1, 500])
def test_reason_boundary_is_measured_after_trimming(length):
    lab = accepted_lab()
    response = lab.client.post(cancel_url(lab.request),
        {"reason": " \t" + "x" * length + "\n "}, format="json")
    assert response.status_code == 200, response.content
    assert response.data["cancellation_reason"] == "x" * length


def test_control_review_requires_reason_confirmation_and_keeps_durable_history():
    lab = accepted_lab()
    assignment(lab)
    root = make_superadmin("cancel-control-root")
    client = admin_client(root)
    url = review_url(lab.request)
    page = client.get(url)
    assert page.status_code == 200
    html = page.content.decode()
    assert 'name="cancellation_reason"' in html
    assert 'name="confirm_cancel"' in html
    assert 'name="cancel"' in html
    for body in [{"cancel": "1", "cancellation_reason": "No confirmation"},
                 {"cancel": "1", "confirm_cancel": "yes", "cancellation_reason": "  "}]:
        before = snapshot()
        response = client.post(url, body)
        assert response.status_code == 302
        assert snapshot() == before
    # Unknown actions must not become a second bulk cancellation surface.
    before = snapshot()
    response = client.post(changelist_url(), action_payload("cancel_selected", lab.request), follow=True)
    assert response.status_code == 200
    assert "No action selected." in [str(message) for message in get_messages(response.wsgi_request)]
    assert snapshot() == before
    approval = (lab.request.accepted_by_id, lab.request.accepted_at)
    response = client.post(url, {"cancel": "1", "confirm_cancel": "yes",
                                 "cancellation_reason": "  Control private decision  "})
    assert response.status_code == 302
    lab.request.refresh_from_db()
    assert lab.request.status == "cancelled"
    assert lab.request.cancellation_reason == "Control private decision"
    assert (lab.request.closed_by_id, lab.request.closed_at is not None) == (root.pk, True)
    assert (lab.request.accepted_by_id, lab.request.accepted_at) == approval
    assert buckets(lab.product) == (8, 0, 0, 8)
    closed = (lab.request.closed_by_id, lab.request.closed_at)
    history = lab.client.get(history_url(lab.space))
    assert history.status_code == 200
    row = history.data["results"][0]
    assert row["cancellation_reason"] == "Control private decision"
    assert row["closed_by"] == {"username": root.username, "role": root.role}
    assert row["closed_at"]
    before = snapshot()
    response = client.post(url, {"cancel": "1", "confirm_cancel": "yes",
                                 "cancellation_reason": "Overwrite attempt"})
    assert response.status_code == 302
    assert snapshot() == before
    lab.request.refresh_from_db()
    assert (lab.request.closed_by_id, lab.request.closed_at) == closed
    event = AuditLog.objects.get(action="request.cancelled")
    assert event.actor_id == root.pk
    assert "Control private decision" not in str(event.meta)


@pytest.mark.parametrize("verified", [True, False])
def test_generic_cancel_notification_is_deferred_and_guards_unverified_contact(
    verified, monkeypatch, django_capture_on_commit_callbacks,
):
    lab = accepted_lab()
    lab.request.requester_contact_email = "cancel-borrower@example.test"
    lab.request.requester_contact_verified = verified
    lab.request.save(update_fields=["requester_contact_email", "requester_contact_verified"])
    # Real channel preferences and recipient selection; replace only the common
    # outbound transport so neither SMTP nor Telegram can reach a provider.
    for channel in NotificationChannel.values:
        NotificationPreference.objects.create(makerspace=lab.space, feature="hardware_requests",
            channel=channel, enabled=channel in {"email", "telegram"})
    emails, chats = [], []

    def email_transport(**kwargs):
        emails.append(kwargs)
        return SimpleNamespace(status=EmailLog.Status.SENT)

    def channel_transport(**kwargs):
        chats.append(kwargs)
        return [SimpleNamespace(status=NotificationDeliveryStatus.SENT)]

    monkeypatch.setattr(notify, "dispatch_email", email_transport)
    monkeypatch.setattr(notify, "dispatch_channel", channel_transport)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = lab.client.post(cancel_url(lab.request),
            {"reason": "Sensitive family circumstance must stay private 819"}, format="json")
    assert response.status_code == 200, response.content
    assert emails == chats == []
    assert callbacks, "The allowed cancellation catalogue event must schedule delivery"
    for callback in callbacks:
        callback()
    assert chats and all(call["event"] == "cancelled" for call in chats)
    assert {call["channel"] for call in chats} == {"telegram"}
    assert all("cancelled" in call["text_body"].lower() for call in chats)
    recipients = {call["to_email"] for call in emails}
    assert lab.actor.email in recipients
    assert ("cancel-borrower@example.test" in recipients) is verified
    assert all(call["event"] in {"cancelled", "request_cancelled"} for call in emails)
    assert "Sensitive family circumstance" not in repr(emails + chats)
    assert "must stay private 819" not in repr(emails + chats)


@pytest.mark.django_db(transaction=True)
def test_portable_cancelled_request_preserves_history_and_rebinds_private_reason(monkeypatch):
    # Restore the migration seed after transactional flush, without bypassing guards.
    DeploymentDatabaseIdentity.objects.get_or_create(pk=1)
    monkeypatch.setattr(notify, "dispatch_email",
                        lambda **kwargs: SimpleNamespace(status=EmailLog.Status.SENT))
    monkeypatch.setattr(notify, "dispatch_channel", lambda **kwargs: [])
    reason = "Private household circumstance 604: borrower cannot collect the tools."

    def prepare_source(space, actor, request):
        product = InventoryProduct.objects.create(
            makerspace=space, name="Portable cancellation tool", tracking_mode="quantity",
            total_quantity=5, available_quantity=5,
        )
        item = HardwareRequestItem.objects.create(
            request=request, product=product, requested_quantity=3,
        )
        approved = workflow.accept_request(actor, request, accepted={item.pk: 2})
        workflow.cancel_request(actor, approved, reason)

    with enabled_encryption():
        # One identity supplies legitimate global review authority; the fixture's
        # imported membership still follows its existing Member/walk-in policy.
        source_user = User.objects.create_superuser(
            username="portable-cancel-root", email="portable-cancel-root@example.test",
            password="pw",
        )
        source = make_space("portable-cancel-source")
        with portable_import_case(source, source_user, prepare_source=prepare_source) as case:
            files = {path.relative_to(case.root).as_posix(): path.read_bytes()
                     for path in case.root.rglob("*") if path.is_file()}
            archived = csv_rows(files, "lending/requests.csv")[0]
            source_ciphertext = raw_reason(case.request.pk)
            assert archived["status"] == "cancelled"
            assert archived["cancellation_reason"] == source_ciphertext
            assert source_ciphertext != reason
            assert parse_envelope(source_ciphertext)[0] >= 1
            assert all(reason.encode() not in content for content in files.values())
            archived_item = csv_rows(files, "lending/request_items.csv")[0]
            assert (archived_item["requested_quantity"], archived_item["accepted_quantity"]) == ("3", "2")
            case.decide_walk_in(source_user)
            # The canonical workflows created immutable audit UUIDs. Release only
            # the fixture's documented collisions to model a separate deployment.
            case.release_non_regenerable_identities()
            result = materialize_tenant(
                case.root, case.job, case.carried,
                target_identity={"slug": "portable-cancel-target"}, batch_size=2,
            )

        target = Makerspace.objects.get(pk=result.target_makerspace_id)
        imported = HardwareRequest.objects.get(makerspace=target)
        assert target.pk != source.pk and imported.pk != case.request.pk
        assert imported.status == "cancelled"
        assert imported.cancellation_reason == reason
        assert (imported.items.get().requested_quantity, imported.items.get().accepted_quantity) == (3, 2)
        target_ciphertext = raw_value(imported, "cancellation_reason")
        version, _, _ = parse_envelope(target_ciphertext)
        assert target_ciphertext not in (reason, source_ciphertext)
        bindings = aad_inputs(imported, "cancellation_reason")
        assert bindings == {"makerspace_id": target.pk,
                            "table": "hardware_requests_hardwarerequest",
                            "pk": imported.pk, "field": "cancellation_reason"}
        dek = get_dek(target.pk, version)
        assert decrypt(target_ciphertext, dek, **bindings).decode() == reason
        for old_binding in ({"makerspace_id": source.pk}, {"pk": case.request.pk}):
            with pytest.raises(PiiAuthenticationFailed):
                decrypt(target_ciphertext, dek, **{**bindings, **old_binding})
