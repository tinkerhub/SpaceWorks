"""P3: the gate end to end -- lookup, then submit.

The properties under test are the ones a forged request would exploit: that the
lookup response is not a credential, that a mid and a name cannot be mixed and
matched, and that an unreachable upstream never reads as a denial.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.checkin.client import CheckinEntry, CheckinUnavailable
from apps.checkin.identity import resolve_principal
from apps.checkin.throttles import CheckinLookupMemberThrottle
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.request_access import MODE_ANYONE, MODE_CHECKED_IN

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Throttle counters live in the shared cache and would otherwise leak between
    tests -- every case here posts from the same client IP, so the second one would
    start half-way through the burst budget. Mirrors the anonymous-submit suite.

    It also clears the roster cache, which `fetch_roster(cached=True)` populates.
    """
    cache.clear()
    yield
    cache.clear()


CORE_PLUS = ["public_inventory", "request_workflow", "staff_admin", "scanner",
             "evidence_uploads", "qr_management"]


def _space(slug, mode=MODE_CHECKED_IN):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=list(CORE_PLUS),
        public_request_mode=mode, checkin_space_id=1,
    )


def _product(space):
    return InventoryProduct.objects.create(
        makerspace=space, name="Multimeter", total_quantity=2,
        available_quantity=2, is_public=True,
    )


def _entry(mid=443, name="Ada Example", purpose="Working on a project",
           project="Metrocard", space_id=1, checkout_hours=1):
    now = datetime.now(timezone.utc)
    return CheckinEntry(
        mid=mid, name=name, avatar="https://example.invalid/a.jpg",
        purpose=purpose, project_name=project,
        check_in_time=now - timedelta(hours=1),
        check_out_time=now + timedelta(hours=checkout_hours),
        space_id=space_id,
    )


def _roster(*entries):
    return patch("apps.checkin.client.fetch_roster", return_value=list(entries))


def _submit(space, product, *, mid, name, key="k1", client=None):
    return (client or APIClient()).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {"checkin_mid": mid, "name": name,
         "items": [{"product_id": product.id, "quantity": 1}]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


# ------------------------------------------------------------------------ lookup


def test_lookup_returns_only_the_typed_name():
    space = _space("cs-lookup")
    with _roster(_entry(mid=1, name="Ada Example"), _entry(mid=2, name="Bee Sample")):
        response = APIClient().post(
            reverse("checkin:lookup", args=[space.slug]),
            {"name": "ada example"}, format="json",
        )

    assert response.status_code == 200
    assert [row["mid"] for row in response.json()] == [1]
    assert response.json()[0]["avatar"]


def test_lookup_never_serves_the_roster_for_an_unknown_name():
    space = _space("cs-lookup-none")
    with _roster(_entry(mid=1), _entry(mid=2, name="Bee Sample")):
        response = APIClient().post(
            reverse("checkin:lookup", args=[space.slug]),
            {"name": "Nobody Here"}, format="json",
        )

    assert response.status_code == 200
    assert response.json() == []


def test_lookup_reports_why_an_ineligible_match_is_refused():
    """So the person can fix their check-in rather than give up."""
    space = _space("cs-lookup-reason")
    with _roster(_entry(purpose="Visiting", project="")):
        response = APIClient().post(
            reverse("checkin:lookup", args=[space.slug]),
            {"name": "Ada Example"}, format="json",
        )

    row = response.json()[0]
    assert row["eligible"] is False
    assert row["reason"] == "purpose"


def test_lookup_is_absent_on_a_makerspace_not_running_the_policy():
    space = _space("cs-lookup-off", mode=MODE_ANYONE)
    response = APIClient().post(
        reverse("checkin:lookup", args=[space.slug]), {"name": "Ada"}, format="json",
    )
    assert response.status_code == 404


def test_authenticated_lookup_is_throttled_before_fetching_upstream(monkeypatch):
    space = _space("cs-lookup-auth-throttle")
    user = User.objects.create_user(username="lookup-throttled")
    client = APIClient()
    client.force_authenticate(user)
    monkeypatch.setattr(
        CheckinLookupMemberThrottle,
        "THROTTLE_RATES",
        {
            **CheckinLookupMemberThrottle.THROTTLE_RATES,
            "checkin_lookup_ip_burst": "2/hour",
        },
    )

    with _roster(_entry()) as fetch_roster:
        responses = [
            client.post(
                reverse("checkin:lookup", args=[space.slug]),
                {"name": "Ada Example"},
                format="json",
            )
            for _ in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert fetch_roster.call_count == 2


# ------------------------------------------------------------------------ submit


def test_an_eligible_person_can_submit():
    space = _space("cs-ok")
    product = _product(space)
    with _roster(_entry()):
        response = _submit(space, product, mid=443, name="Ada Example")

    assert response.status_code == 201, response.content


def test_authenticated_nonmember_is_still_held_to_the_checkin_gate():
    space = _space("cs-global-account")
    product = _product(space)
    user = User.objects.create_user(
        username="global-account", role=User.Role.SUPERADMIN, is_superuser=True
    )
    authenticated = APIClient()
    authenticated.force_authenticate(user)

    with _roster():
        anonymous_response = _submit(
            space, product, mid=443, name="Ada Example", key="anon-gate"
        )
    with _roster():
        authenticated_response = _submit(
            space,
            product,
            mid=443,
            name="Ada Example",
            key="account-gate",
            client=authenticated,
        )

    assert authenticated_response.status_code == anonymous_response.status_code == 403
    assert authenticated_response.json() == anonymous_response.json()


def test_authenticated_member_may_submit_without_the_roster():
    from apps.hardware_requests.models import HardwareRequest

    space = _space("cs-member-account")
    product = _product(space)
    user = User.objects.create_user(username="space-member", display_name="Space Member")
    MakerspaceMembership.objects.create(makerspace=space, user=user)
    authenticated = APIClient()
    authenticated.force_authenticate(user)

    with patch(
        "apps.checkin.client.fetch_roster",
        side_effect=AssertionError("member submission must not fetch the roster"),
    ):
        response = _submit(
            space,
            product,
            mid=None,
            name="",
            key="member-account",
            client=authenticated,
        )

    assert response.status_code == 201, response.content
    assert HardwareRequest.objects.get(makerspace=space).requester == user


@pytest.mark.parametrize(
    "access_status",
    [User.AccessStatus.RESTRICTED, User.AccessStatus.SUSPENDED],
)
def test_non_active_member_cannot_bypass_the_roster(access_status):
    space = _space(f"cs-blocked-member-{access_status}")
    product = _product(space)
    user = User.objects.create_user(
        username=f"blocked-member-{access_status}",
        access_status=access_status,
    )
    MakerspaceMembership.objects.create(makerspace=space, user=user)
    authenticated = APIClient()
    authenticated.force_authenticate(user)

    with patch(
        "apps.checkin.client.fetch_roster",
        side_effect=AssertionError("an authenticated member must not fall back to the roster"),
    ):
        response = _submit(
            space,
            product,
            mid=443,
            name="Ada Example",
            key=f"blocked-{access_status}",
            client=authenticated,
        )

    assert response.status_code == 403
    assert response.json()["code"] == "membership_required"


def test_the_canonical_roster_name_is_stored_not_the_typed_spelling():
    from apps.hardware_requests.models import HardwareRequest

    space = _space("cs-canonical")
    product = _product(space)
    with _roster(_entry(name="Ada Example")):
        _submit(space, product, mid=443, name="ada   EXAMPLE")

    request = HardwareRequest.objects.get(makerspace=space)
    assert request.requester_name == "Ada Example"


def test_the_project_and_purpose_are_captured():
    from apps.hardware_requests.models import HardwareRequest

    space = _space("cs-capture")
    product = _product(space)
    with _roster(_entry(project="Metrocard")):
        _submit(space, product, mid=443, name="Ada Example")

    request = HardwareRequest.objects.get(makerspace=space)
    assert request.checkin_project_name == "Metrocard"
    assert request.checkin_purpose == "Working on a project"
    assert request.checkin_verified_at is not None
    assert request.checkin_identity is not None


def test_no_contact_details_are_stored():
    """The operator asked for no email/name/phone collection: identity is the roster
    match, and a submitted contact field must not sneak into the record."""
    from apps.hardware_requests.models import HardwareRequest

    space = _space("cs-nocontact")
    product = _product(space)
    with _roster(_entry()):
        APIClient().post(
            reverse("hardware_requests:request-submit", args=[space.slug]),
            {"checkin_mid": 443, "name": "Ada Example",
             "contact_email": "spoof@example.test", "contact_phone": "12345",
             "contact_name": "Someone Else",
             "items": [{"product_id": product.id, "quantity": 1}]},
            format="json", HTTP_IDEMPOTENCY_KEY="k-nocontact",
        )

    request = HardwareRequest.objects.get(makerspace=space)
    assert request.requester_contact_email == ""
    assert request.requester_contact_phone == ""
    assert request.requester_name == "Ada Example"


# ----------------------------------------------------------------------- refusals


def test_a_mid_that_is_not_on_the_roster_is_refused():
    space = _space("cs-forged")
    product = _product(space)
    with _roster(_entry(mid=443)):
        response = _submit(space, product, mid=999, name="Ada Example")

    assert response.status_code == 403
    assert response.json()["code"] == "not_checked_in"


def test_a_real_mid_with_someone_elses_name_is_refused():
    """Both halves must agree, or a caller could borrow a mid from the public roster
    and attach their own name to it."""
    space = _space("cs-mismatch")
    product = _product(space)
    with _roster(_entry(mid=443, name="Ada Example"), _entry(mid=444, name="Bee Sample")):
        response = _submit(space, product, mid=443, name="Bee Sample")

    assert response.status_code == 403
    assert response.json()["code"] == "not_checked_in"


@pytest.mark.parametrize("purpose,project", [
    ("Visiting", "Metrocard"),
    ("Self Learning", "Metrocard"),
    ("Working on a project", ""),
    ("Working on a project", "   "),
])
def test_an_ineligible_person_is_told_what_to_fix(purpose, project):
    space = _space(f"cs-inelig-{abs(hash((purpose, project))) % 9999}")
    product = _product(space)
    with _roster(_entry(purpose=purpose, project=project)):
        response = _submit(space, product, mid=443, name="Ada Example")

    assert response.status_code == 403
    assert response.json()["code"] == "project_required"


def test_an_expired_checkout_is_refused():
    space = _space("cs-expired")
    product = _product(space)
    with _roster(_entry(checkout_hours=-1)):
        response = _submit(space, product, mid=443, name="Ada Example")

    assert response.status_code == 403
    assert response.json()["code"] == "not_checked_in"


@pytest.mark.parametrize(
    "user_updates",
    [
        {"access_status": User.AccessStatus.RESTRICTED},
        {"access_status": User.AccessStatus.SUSPENDED},
        {"is_active": False},
    ],
    ids=["restricted", "suspended", "deactivated"],
)
def test_an_existing_unusable_checkin_principal_is_refused(user_updates):
    space = _space(f"cs-principal-{next(iter(user_updates.values()))}")
    product = _product(space)
    identity = resolve_principal(space, _entry())
    User.objects.filter(pk=identity.user_id).update(**user_updates)

    with _roster(_entry()):
        response = _submit(space, product, mid=443, name="Ada Example")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Your makerspace access is restricted. Contact makerspace staff.",
        "code": "checkin_access_restricted",
    }


def test_another_spaces_roster_entry_is_refused():
    space = _space("cs-otherspace")
    product = _product(space)
    with _roster(_entry(space_id=2)):
        response = _submit(space, product, mid=443, name="Ada Example")

    assert response.status_code == 403


def test_an_unreachable_upstream_is_503_never_a_denial():
    """A denial would tell someone standing in the building that they are not in it."""
    space = _space("cs-down")
    product = _product(space)
    with patch("apps.checkin.client.fetch_roster", side_effect=CheckinUnavailable()):
        response = _submit(space, product, mid=443, name="Ada Example")

    assert response.status_code == 503
    assert response.json()["code"] == "checkin_unavailable"


# -------------------------------------------------------------------- idempotency


def test_a_retry_with_the_same_key_returns_the_original_request():
    from apps.hardware_requests.models import HardwareRequest

    space = _space("cs-replay")
    product = _product(space)
    with _roster(_entry()):
        first = _submit(space, product, mid=443, name="Ada Example", key="same")
        second = _submit(space, product, mid=443, name="Ada Example", key="same")

    assert first.json()["public_token"] == second.json()["public_token"]
    assert HardwareRequest.objects.filter(makerspace=space).count() == 1


def test_a_retry_succeeds_even_while_upstream_is_down():
    """Replay is checked BEFORE the upstream call precisely so an accepted request
    stays retryable when the roster is unreachable."""
    space = _space("cs-replay-down")
    product = _product(space)
    with _roster(_entry()):
        first = _submit(space, product, mid=443, name="Ada Example", key="dsame")

    with patch("apps.checkin.client.fetch_roster", side_effect=CheckinUnavailable()):
        second = _submit(space, product, mid=443, name="Ada Example", key="dsame")

    assert second.status_code == 201
    assert first.json()["public_token"] == second.json()["public_token"]


def test_two_people_sharing_a_name_cannot_replay_each_others_request():
    """The fingerprint includes the mid. Without it, identical names and identical
    item lists would collide and one person would receive the other's token."""
    space = _space("cs-collide")
    product = _product(space)
    with _roster(_entry(mid=1, name="Ada Example"), _entry(mid=2, name="Ada Example")):
        first = _submit(space, product, mid=1, name="Ada Example", key="shared")
        second = _submit(space, product, mid=2, name="Ada Example", key="shared")

    # Same key, different payload -> refused as a conflict rather than silently
    # returning the first person's request.
    assert first.status_code == 201
    assert second.status_code == 409, second.content
