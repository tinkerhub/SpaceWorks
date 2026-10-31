"""Committed reprints notify once while retaining member and bearer ownership."""

import json

import pytest
from django.db import connection, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.integrations.models import EmailLog, NotificationDeliveryLog, NotificationPreference
from apps.machines.models import MachineServiceRequest, ServiceRequestFile
from apps.machines.service_errors import ServiceInvalidTransition
from apps.machines.service_workflow import create_reprint
from apps.makerspaces.models import MakerspaceMembership
from apps.notifications.models import Notification
from tests.own_requests.own_requests_support import (
    MACHINE_KEYS, ROUTES, history_lab, history_url, providers, service,
)
from tests.own_requests.reprint_test_support import effects, reprint_lab, terminal_request
from tests.return_helpers import authenticated_client, make_member
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("printer", [True, False], ids=["printer", "generic"])
def test_committed_reprint_notifies_and_preserves_member_history(reprint_lab, providers, printer):
    lab = reprint_lab
    original, attachment = terminal_request(lab, printer=printer)
    old_status, old_token = original.status, original.public_token
    file_before = ServiceRequestFile.objects.filter(pk=attachment.pk).values().get()
    assert connection.get_autocommit() and not connection.in_atomic_block

    # Use the pre-existing public workflow import on both old and new source.
    child = create_reprint(original, lab.actor)

    child.refresh_from_db()
    original.refresh_from_db()
    assert child.status == "accepted" and child.accepted_by_id == lab.actor.pk
    assert child.public_token != old_token and child.pk != original.pk
    assert child.member_id == original.member_id == lab.user.pk
    assert child.requester_id == original.requester_id == lab.actor.pk != lab.user.pk
    assert child.reprint_of_id == original.pk
    assert list(child.reprint_of.files.values_list("pk", flat=True)) == [attachment.pk]
    assert not child.files.exists()
    assert ServiceRequestFile.objects.filter(pk=attachment.pk).values().get() == file_before
    assert (original.status, original.public_token) == (old_status, old_token)
    audit = AuditLog.objects.get(action="machine_service.reprint_created", target_id=str(child.pk))
    assert audit.actor_id == lab.actor.pk and audit.meta["reprint_of_id"] == original.pk

    # These are the causal assertions: old followups create/audit but never notify.
    feature = "printing" if printer else "machine_service"
    log = NotificationDeliveryLog.objects.get()
    assert (log.feature, log.event, log.channel, log.status, log.attempts) == (
        feature, "reprinted", "telegram", "sent", 1,
    )
    assert providers == [{"chat_id": "-101101", "text": log.text_body}]
    inbox = Notification.objects.get()
    assert inbox.event == "machine_service.reprinted" and inbox.makerspace_id == lab.space.pk
    assert f"#{child.pk}" in inbox.body and f"#{child.pk}" in log.text_body
    assert "Status: accepted" in inbox.body and "Status: accepted" in log.text_body
    assert not EmailLog.objects.filter(audience="requester").exists()
    assert not EmailLog.objects.filter(stream="machine_service").exists()

    mine = lab.client.get(history_url(lab, ROUTES[1]))
    assert mine.status_code == 200 and mine.data["count"] == 2
    assert {str(row["public_token"]) for row in mine.data["results"]} == {
        str(old_token), str(child.public_token),
    }
    assert all(set(row) == MACHINE_KEYS for row in mine.data["results"])
    staff_mine = authenticated_client(lab.actor).get(history_url(lab, ROUTES[1]))
    assert staff_mine.status_code == 200 and staff_mine.data["count"] == 0
    old_public = APIClient().get(reverse("public-machine-service-status", args=[old_token]))
    assert old_public.status_code == 200 and set(old_public.data) == MACHINE_KEYS
    assert str(old_public.data["public_token"]) == str(old_token)
    assert old_public.data["status"] == old_status
    assert str(child.public_token) not in json.dumps(old_public.data, default=str)

    # No new public projection or child-token link; both messages remain staff-only.
    messages = json.dumps(providers) + inbox.title + inbox.body + inbox.url_path
    for email in EmailLog.objects.all():
        messages += email.subject + email.text_body + email.html_body
    for private in (
        str(old_token), str(child.public_token), original.source_link, original.reason,
    ):
        assert private and private not in messages
    if not printer:
        for contact in (original.contact_email, original.contact_phone):
            assert contact and contact not in messages


@pytest.mark.parametrize("inbox_enabled", [True, False], ids=["inbox-on", "inbox-off"])
def test_generic_explicit_telegram_off_keeps_independent_inbox_gate(
    reprint_lab, providers, inbox_enabled,
):
    lab = reprint_lab
    original, _ = terminal_request(lab)
    NotificationPreference.objects.create(
        makerspace=lab.space, feature="machine_service", channel="telegram", enabled=False,
    )
    if not inbox_enabled:
        lab.space.enabled_modules.remove("notifications")
        lab.space.save(update_fields=["enabled_modules"])

    child = create_reprint(original, lab.actor)

    assert child.status == "accepted" and child.reprint_of_id == original.pk
    assert not NotificationDeliveryLog.objects.exists() and providers == []
    assert Notification.objects.filter(event="machine_service.reprinted").count() == int(inbox_enabled)
    if inbox_enabled:
        assert f"#{child.pk}" in Notification.objects.get().body


def test_outer_rollback_discards_reprint_audit_and_callback(reprint_lab, providers):
    lab = reprint_lab
    original, _ = terminal_request(lab)
    before = effects(lab, providers)

    with pytest.raises(RuntimeError, match="rollback reprint"):
        with transaction.atomic():
            child = create_reprint(original, lab.actor)
            assert MachineServiceRequest.objects.filter(pk=child.pk).exists()
            assert AuditLog.objects.filter(target_id=str(child.pk), action="machine_service.reprint_created").exists()
            assert not NotificationDeliveryLog.objects.exists() and not Notification.objects.exists()
            assert providers == []
            raise RuntimeError("rollback reprint")

    assert effects(lab, providers) == before


def test_nonterminal_refusal_has_no_reprint_or_notification_effects(reprint_lab, providers):
    lab = reprint_lab
    original = service(lab, member=lab.user, requester=lab.actor, status="accepted")
    before = effects(lab, providers)

    with pytest.raises(ServiceInvalidTransition, match="Only terminal"):
        create_reprint(original, lab.actor)

    assert effects(lab, providers) == before


def test_real_reprint_api_checks_verified_origin_and_machine_action(reprint_lab, providers):
    lab = reprint_lab
    for space in (lab.space, lab.other_space):
        space.frontend_domain = f"{space.slug}.example.test"
        space.frontend_domain_status = "verified"
        space.save(update_fields=["frontend_domain", "frontend_domain_status"])
    # The manager has both memberships: only the verified origin excludes the row.
    MakerspaceMembership.objects.create(user=lab.actor, makerspace=lab.other_space, role="space_manager")
    limited = make_member(
        "reprint-inventory-manager", lab.space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER, role=User.Role.REQUESTER,
    )
    original, _ = terminal_request(lab)
    path = reverse("admin-machine-service-request-reprint", args=[original.pk])
    client = authenticated_client(lab.actor)
    before = effects(lab, providers)

    foreign = client.post(path, {}, format="json", HTTP_ORIGIN=f"https://{lab.other_space.frontend_domain}")
    assert foreign.status_code == 403
    denied = authenticated_client(limited).post(
        path, {}, format="json", HTTP_ORIGIN=f"https://{lab.space.frontend_domain}",
    )
    assert denied.status_code == 403
    assert effects(lab, providers) == before

    first = client.post(path, {}, format="json", HTTP_ORIGIN=f"https://{lab.space.frontend_domain}")
    assert first.status_code == 200, first.data
    child = MachineServiceRequest.objects.get(pk=first.data["id"])
    assert child.status == "accepted" and child.member_id == lab.user.pk
    assert child.reprint_of_id == original.pk
    assert AuditLog.objects.filter(action="machine_service.reprint_created", target_id=str(child.pk)).count() == 1
    # A legitimate repeat makes a distinct child; this endpoint is not idempotent.
    second = client.post(path, {}, format="json", HTTP_ORIGIN=f"https://{lab.space.frontend_domain}")
    assert second.status_code == 200, second.data
    assert second.data["id"] != first.data["id"]
    assert original.reprints.count() == 2
    assert NotificationDeliveryLog.objects.filter(event="reprinted", status="sent").count() == 2
    assert Notification.objects.filter(event="machine_service.reprinted").count() == 2
    assert len(providers) == 2


def test_quiesced_source_gate_refuses_api_before_reprint_effects(reprint_lab, providers):
    lab = reprint_lab
    original, _ = terminal_request(lab)
    gate = close_gate(lab.space, lab.actor)
    assert gate.state == "quiesced"
    before = effects(lab, providers)

    response = authenticated_client(lab.actor).post(
        reverse("admin-machine-service-request-reprint", args=[original.pk]), {}, format="json",
    )

    assert response.status_code == 423
    assert effects(lab, providers) == before
