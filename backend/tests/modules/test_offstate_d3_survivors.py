"""The DELIBERATE SURVIVORS: surfaces that stay open with their module switched off.

"Modules that are off disappear everywhere" has exceptions, and each one is a decision
with a reason in `docs/INVARIANTS.md`, not an oversight. They are listed here, in one
place, each mapped to the test that proves it still works with its module off -- so a
future gate that swallows one fails a named test instead of silently stranding money,
staff or account recovery.
"""

import importlib
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.integrations.dispatch import dispatch_email
from apps.integrations.models import EmailLog
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceBucket
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.module_install import uninstall_module
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from apps.payments.models import Payment


pytestmark = pytest.mark.django_db

THIS = "tests.modules.test_offstate_d3_survivors"
MONEY = "tests.modules.test_offstate_money"
MEMBERSHIP = "tests.modules.test_offstate_d3_membership"

# (module, survivor) -> "python.module::test_function" proving it with the module OFF.
SURVIVORS = {
    ("payments", "provider webhook settles a retained charge"):
        f"{MONEY}::test_payments_off_still_lets_the_webhook_settle_an_existing_charge",
    ("payments", "staff records offline money on a retained charge"):
        f"{MONEY}::test_payments_off_still_lets_staff_record_offline_money",
    ("payments", "machine-service mark-offline / waive of a retained charge"):
        f"{THIS}::test_machine_service_settlement_of_a_retained_charge_survives_payments_off",
    ("payments", "member receipt and payment history"):
        f"{THIS}::test_member_payment_history_survives_payments_off",
    ("payments", "archived-payment discovery"):
        f"{THIS}::test_archived_payment_discovery_survives_payments_off",
    ("membership", "staff invitation: invite, claim, list, approve"):
        f"{MEMBERSHIP}::test_staff_invitation_survives_membership_off_end_to_end",
    ("email", "platform account-recovery mail"):
        f"{THIS}::test_platform_recovery_mail_is_never_gated",
    ("email", "documented tenant exemptions (return reminder, custody alarms, ...)"):
        f"{THIS}::test_documented_email_exemptions_still_send_with_email_off",
    ("email", "email logs stay readable"):
        f"{THIS}::test_email_logs_survive_email_off",
    ("modules admin", "lists disabled modules so they can be reinstalled"):
        f"{THIS}::test_modules_admin_lists_disabled_modules",
}

CORE = frozenset(core_module_keys())


def test_every_listed_survivor_points_at_a_real_test():
    for survivor, target in SURVIVORS.items():
        module_path, function = target.split("::")
        assert callable(getattr(importlib.import_module(module_path), function, None)), survivor


def _space(slug, *extra):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=sorted(with_dependencies(CORE | set(extra)))
    )


def _user(slug, *, superadmin=False):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        role=User.Role.SUPERADMIN if superadmin else User.Role.REQUESTER,
        is_staff=superadmin,
        is_superuser=superadmin,
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _member(space, slug):
    user = _user(slug)
    membership = MakerspaceMembership.objects.create(
        makerspace=space, user=user, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )
    return user, membership


def _membership_charge(space, user, membership):
    return Payment.objects.create(
        makerspace=space, subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk, member=user, amount=Decimal("9.00"), currency="usd",
        created_by=user,
    )


# --- payments ----------------------------------------------------------------------


def test_machine_service_settlement_of_a_retained_charge_survives_payments_off():
    space = _space("d3-survive-ms", "payments", "machines", "machine_service")
    requester = _user("d3-survive-ms-requester")
    machine_type = MachineType.objects.create(makerspace=space, slug="d3-laser", name="Laser")
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Laser 1")
    bucket = ServiceBucket.objects.create(machine=machine, name="Service Requests")
    charges = []
    for index in range(2):
        job = MachineServiceRequest.objects.create(
            bucket=bucket, makerspace=space, requester=requester, member=requester,
            assigned_machine=machine, title=f"Cut {index}",
        )
        charges.append(Payment.objects.create(
            makerspace=space, subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
            subject_id=job.pk, member=requester, amount=Decimal("4.00"), currency="usd",
            created_by=requester,
        ))
    uninstall_module(space, "payments")
    client = _client(_user("d3-survive-ms-admin", superadmin=True))

    offline = client.post(f"/api/v1/admin/machine-service/payments/{charges[0].pk}/mark-offline")
    waived = client.post(f"/api/v1/admin/machine-service/payments/{charges[1].pk}/waive")

    assert offline.status_code == 200, offline.data
    assert waived.status_code == 200, waived.data
    assert [Payment.objects.get(pk=c.pk).status for c in charges] == [
        Payment.Status.PAID_OFFLINE, Payment.Status.WAIVED,
    ]


def test_member_payment_history_survives_payments_off():
    space = _space("d3-survive-history", "payments")
    user, membership = _member(space, "d3-survive-history-member")
    payment = _membership_charge(space, user, membership)
    uninstall_module(space, "payments")

    response = _client(user).get(reverse("member-payment-history", args=[space.pk]))

    assert response.status_code == 200, response.data
    assert [row["id"] for row in response.data] == [payment.pk]


def test_archived_payment_discovery_survives_payments_off():
    space = _space("d3-survive-archived", "payments")
    user, membership = _member(space, "d3-survive-archived-member")
    _membership_charge(space, user, membership)
    uninstall_module(space, "payments")
    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())

    response = _client(user).get(reverse("member-archived-payments"))

    assert response.status_code == 200, response.data
    assert [row["makerspace"]["id"] for row in response.data] == [space.pk]


# --- email -------------------------------------------------------------------------


def _mail(makerspace, stream, event):
    return dispatch_email(
        makerspace=makerspace, to_email="someone@example.test", subject="Subject",
        text_body="Body", stream=stream, event=event, audience="member", sync=True,
    )


def test_platform_recovery_mail_is_never_gated():
    for event in ("password_reset", "email_verification"):
        assert _mail(None, "account", event).status != EmailLog.Status.SKIPPED


@pytest.mark.parametrize(
    ("stream", "event"),
    [
        ("hardware", "return_reminder"),
        ("backup", "archive_custody_alarm"),
        ("backup", "tenant_exit_custody_alarm"),
    ],
)
def test_documented_email_exemptions_still_send_with_email_off(stream, event):
    space = _space(f"d3-survive-mail-{event}".replace("_", "-"))
    assert "email" not in space.enabled_modules

    assert _mail(space, stream, event).status != EmailLog.Status.SKIPPED
    # The pair proves the exemption, not a mail path that ignores the module entirely.
    assert _mail(space, "hardware", "submitted").status == EmailLog.Status.SKIPPED


def test_email_logs_survive_email_off():
    space = _space("d3-survive-email-logs")
    _mail(space, "hardware", "submitted")

    response = _client(_user("d3-survive-email-logs-admin", superadmin=True)).get(
        f"/api/v1/admin/makerspace/{space.pk}/email-logs"
    )

    assert response.status_code == 200, response.data


# --- modules admin -----------------------------------------------------------------


def test_modules_admin_lists_disabled_modules():
    space = _space("d3-survive-modules")

    response = _client(_user("d3-survive-modules-admin", superadmin=True)).get(
        f"/api/v1/admin/makerspace/{space.pk}/modules"
    )

    assert response.status_code == 200, response.data
    rows = {row["key"]: row for group in response.data["groups"] for row in group["modules"]}
    assert rows["events"]["installed"] is False
    assert rows["payments"]["installed"] is False
