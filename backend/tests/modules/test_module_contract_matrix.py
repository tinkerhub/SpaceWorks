"""One positive and one own-key negative contract for every optional module.

Each positive case installs only core, the module under test, and its declared
dependencies. Each negative case keeps those dependencies but removes the module
itself, so a refusal cannot be blamed on an unrelated optional prerequisite.
"""

from functools import partial

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import (
    BY_KEY,
    core_module_keys,
    with_dependencies,
)
from tests.modules.module_contract_identity_probes import (
    AUTH_DENIALS,
    member_accounts,
    mobile,
)
from tests.modules.module_contract_probes import (
    email_test,
    payment_settings,
    webhook_destination,
)
from tests.modules.test_offstate_inventory import _exercise_surface
from tests.modules.test_offstate_machines import _machine, _printer_queue

pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())
OPTIONAL = tuple(sorted(set(BY_KEY) - CORE))


def _space(module_key, state, modules):
    label = module_key.replace("_", "-")
    space = Makerspace.objects.create(
        name=f"contract-{label}-{state}",
        slug=f"contract-{label}-{state}",
        enabled_modules=sorted(modules),
        public_inventory_enabled=True,
    )
    space.refresh_from_db()
    assert set(space.enabled_modules) == modules
    return space


def _actor(module_key, state):
    username = f"contract-{module_key}-{state}"
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        display_name="Module contract probe",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def _inventory_probe(module_key):
    return lambda space, client: _exercise_surface(module_key, space, client)


def _guest_handover(space, client):
    return client.get(
        reverse("hardware_requests:guest-admin-active-loans", args=[space.pk])
    )


def _reports(space, client):
    return client.get(reverse("analytics-summary", args=[space.pk]))


def _qr_print_batches(space, client):
    return client.post(
        reverse("qr-print-batches", args=[space.pk]),
        {"title": "Contract labels"},
        format="json",
    )


def _machines(space, client):
    return client.get(reverse("admin-machine-types", args=[space.pk]))


def _machine_service(space, client):
    return client.get(
        reverse("admin-machine-service-request-list-create", args=[space.pk])
    )


def _printing(space, client):
    _printer_queue(space)
    return client.get(reverse("public-printer-service-queues", args=[space.slug]))


def _events(space, client):
    return client.get(reverse("admin-event-list-create", args=[space.pk]))


def _bookings(space, client):
    return client.get(reverse("admin-bookable-space-list-create", args=[space.pk]))


def _maintenance(space, client):
    machine = _machine(space, suffix="contract")
    return client.get(
        reverse(
            "admin-maintenance-log-list-create",
            kwargs={"makerspace_id": space.pk, "machine_id": machine.pk},
        )
    )


def _membership(space, client):
    return client.post(
        reverse("public-membership-request", args=[space.slug]), {}, format="json"
    )


def _notifications(space, client):
    return client.get(
        reverse("notifications:notifications-list", args=[space.pk])
    )


def _telegram(space, client):
    return client.post(
        reverse("telegram-test-alert"),
        {"makerspace_id": space.pk, "message": "Contract probe"},
        format="json",
    )


PROBES = {
    "asset_units": _inventory_probe("asset_units"),
    "bookings": _bookings,
    "bulk_import": _inventory_probe("bulk_import"),
    "containers": _inventory_probe("containers"),
    "discord": partial(webhook_destination, channel="discord"),
    "email": email_test,
    "events": _events,
    "guest_handover": _guest_handover,
    "machine_service": _machine_service,
    "machines": _machines,
    "maintenance": _maintenance,
    "mattermost": partial(webhook_destination, channel="mattermost"),
    "member_accounts": member_accounts,
    "membership": _membership,
    "mobile": mobile,
    "notifications": _notifications,
    "payments": payment_settings,
    "printing": _printing,
    "procurement": _inventory_probe("procurement"),
    "qr_print_batches": _qr_print_batches,
    "reports": _reports,
    "slack": partial(webhook_destination, channel="slack"),
    "stock_transfers": _inventory_probe("stock_transfers"),
    "stocktake": _inventory_probe("stocktake"),
    "telegram": _telegram,
}


def _probe(module_key, monkeypatch, settings, actor):
    probe = PROBES[module_key]
    if module_key in {"discord", "mattermost", "slack", "email", "payments"}:
        probe = partial(probe, actor=actor)
    # Bind fixture context only for new helpers; the original probes stay two-arg.
    if module_key in {"discord", "mattermost", "slack", "mobile"}:
        return partial(probe, monkeypatch=monkeypatch, settings=settings)
    if module_key == "email":
        return partial(probe, settings=settings)
    if module_key == "member_accounts":
        return partial(probe, monkeypatch=monkeypatch)
    return probe


@pytest.mark.parametrize("module_key", OPTIONAL)
def test_optional_module_primary_surface_works_with_only_its_dependencies(
    module_key, monkeypatch, settings
):
    modules = CORE | with_dependencies({module_key})
    space = _space(module_key, "on", modules)
    actor = _actor(module_key, "on")
    probe = _probe(module_key, monkeypatch, settings, actor)

    response = probe(space, _client(actor))

    assert 200 <= response.status_code < 300, (
        f"{module_key} positive probe: {response.status_code} {response.data}"
    )


@pytest.mark.parametrize("module_key", OPTIONAL)
def test_optional_module_primary_surface_refuses_when_only_its_key_is_absent(
    module_key, monkeypatch, settings
):
    modules = CORE | (with_dependencies({module_key}) - {module_key})
    space = _space(module_key, "off", modules)
    actor = _actor(module_key, "off")
    probe = _probe(module_key, monkeypatch, settings, actor)

    response = probe(space, _client(actor))

    assert response.status_code >= 400, (
        f"{module_key} negative probe unexpectedly returned {response.status_code}"
    )
    if module_key in AUTH_DENIALS:
        # Deployment-wide anonymous auth uses generic bodies, not tenant module keys.
        expected_status, expected_body = AUTH_DENIALS[module_key]
        assert response.status_code == expected_status
        assert response.data == expected_body
    else:
        assert module_key in str(response.data), (
            f"{module_key} surface refused without naming its own key: {response.data}"
        )


def test_probe_registry_covers_every_optional_module_key():
    assert set(PROBES) == set(OPTIONAL)
    assert all(callable(probe) for probe in PROBES.values())
