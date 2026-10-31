"""Small real-row factories and a provider-only network boundary for these tests."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from tests.return_helpers import authenticated_client, make_product, make_space, make_user


ROUTES = ("hardware_requests:own-requests", "public-own-machine-service-requests")
ITEM_KEYS = {
    "product_name", "requested_quantity", "accepted_quantity",
    "issued_quantity", "returned_quantity",
}
MACHINE_KEYS = {
    "public_token", "status", "title", "created_at", "accepted_at", "started_at",
    "completed_at", "estimated_minutes", "queue_position", "queue_approved_ahead",
    "queue_awaiting_review_ahead",
}


@pytest.fixture(autouse=True)
def providers(monkeypatch, settings):
    """Run the real engine; capture Telegram HTTP, block every other provider IO.

    No deployment credentials are read or changed. New spaces have no stored
    credentials, and settings are temporary synthetic values restored by pytest.
    """
    settings.TELEGRAM_BOT_TOKEN = "123456:synthetic-test-token"
    settings.TELEGRAM_API_URL = "https://telegram.invalid"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    calls = []

    def telegram_http(request, **kwargs):
        assert request.full_url == "https://telegram.invalid/bot123456:synthetic-test-token/sendMessage"
        assert request.get_method() == "POST" and kwargs == {"timeout": 5}
        payload = json.loads(request.data)
        assert set(payload) == {"chat_id", "text"}
        calls.append(payload)
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected external provider transport")

    monkeypatch.setattr("urllib.request.urlopen", telegram_http)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    monkeypatch.setattr("django.core.mail.backends.smtp.EmailBackend.send_messages", forbidden)
    monkeypatch.setattr("apps.integrations.push.send_fcm", forbidden)
    monkeypatch.setattr("apps.integrations.push_apns.send_apns", forbidden)
    return calls


@pytest.fixture
def history_lab():
    space, other_space = make_space("own-history"), make_space("foreign-history")
    for tenant in (space, other_space):
        tenant.enabled_modules = [
            key for key in tenant.enabled_modules
            if key not in {"membership", "member_accounts"}
        ]
        tenant.save(update_fields=["enabled_modules"])
    user = make_user("history-owner", access_status=User.AccessStatus.ACTIVE)
    other = make_user("history-other", access_status=User.AccessStatus.ACTIVE)
    kind = MachineType.objects.create(makerspace=space, slug="laser", name="Laser cutter")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser one")
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=kind, name="Laser queue")
    return SimpleNamespace(
        space=space, other_space=other_space, user=user, other=other,
        client=authenticated_client(user), product=make_product(space),
        kind=kind, machine=machine, queue=queue,
    )


def history_url(lab, route=ROUTES[0], *, space=None):
    return reverse(route, args=[(space or lab.space).slug])


def hardware(lab, *, owner=None, space=None, status="pending_approval", **fields):
    owner = owner or lab.user
    row = HardwareRequest.objects.create(
        makerspace=space or lab.space, requester=owner,
        requester_username=owner.username, status=status, **fields,
    )
    HardwareRequestItem.objects.create(
        request=row, product=make_product(space) if space else lab.product, requested_quantity=7,
        accepted_quantity=5, issued_quantity=4, returned_quantity=2,
    )
    return row


def service(lab, *, member=None, requester=None, queue=None, **fields):
    return MachineServiceRequest.objects.create(
        queue=queue or lab.queue, requester=requester or lab.user,
        member=member, title=fields.pop("title", "Member project"), **fields,
    )


def submit_hardware(lab, *, anonymous=False):
    from apps.hardware_requests.request_workflow import RequesterSnapshot
    from apps.hardware_requests.workflow import submit_request

    return submit_request(
        lab.space, [{"product": lab.product, "quantity": 3}],
        requester_principal=lab.user, audit_actor=lab.user,
        contact_snapshot=RequesterSnapshot(
            username=lab.user.username, name="Private borrower",
            email="private-borrower@example.test", phone="+15550123456",
            contact_verified=not anonymous,
        ),
        idempotency_key_fingerprint="a" * 64 if anonymous else "",
        payload_fingerprint="b" * 64 if anonymous else "",
    )


def submit_service(lab, *, queue=None):
    from apps.machines.printer_capabilities import is_printer_type
    from apps.machines.service_workflow import submit

    target = queue or lab.queue
    payload = (
        {"requested_material": "PLA", "requested_color": "Black", "quantity": 1}
        if is_printer_type(target.machine_type) else {}
    )
    return submit(
        target, lab.user, actor=lab.user, member=lab.user, capability_payload=payload,
        title="Housing project", requester_name="Private maker",
        contact_email="private-maker@example.test", contact_phone="+15550987654",
        source_link="https://private.invalid/model.stl",
    )
