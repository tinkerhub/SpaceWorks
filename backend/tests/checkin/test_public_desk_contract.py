"""The backend facts the public request desk copy promises (PublicRequestHeader.tsx).

On a `checked_in` space every public borrower is matched against the roster, signed in or
not: a borrow request (pinned in `test_submit_flow`) and a tool checkout are both recorded
under the check-in name, even for a signed-in staff member. And the desk
hides the scan tab entirely off the roster with `membership` off, because self-checkout
there demands membership, waiver and presence that nobody can establish. These pin both
halves so the copy cannot drift from the branch it describes.
"""

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.request_access import MODE_ANYONE, MODE_CHECKED_IN

pytestmark = pytest.mark.django_db

CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "evidence_uploads", "qr_management"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _staff_client(space, username):
    user = User.objects.create_user(username=username, display_name="Space Staff")
    MakerspaceMembership.objects.create(makerspace=space, user=user, status="active")
    client = APIClient()
    client.force_authenticate(user)
    return client


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_signed_in_staff_still_need_the_roster_to_self_checkout():
    space = Makerspace.objects.create(
        name="desk-checkin", slug="desk-checkin", enabled_modules=list(CORE),
        enabled_features=["inventory.self_checkout"],
        public_request_mode=MODE_CHECKED_IN, checkin_space_id=1,
    )
    client = _staff_client(space, "desk-checkin-staff")

    response = client.post(
        reverse("hardware_requests:public-tool-evidence-url", args=[space.slug]),
        {"evidence_type": "issue", "content_type": "image/png"},
        format="json",
    )

    # No membership bypass: the check-in identity is required, as for borrow requests.
    assert response.status_code == 400, response.content
    assert "checkin_mid" in response.json() or "name" in response.json()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_self_checkout_off_the_roster_is_unusable_with_membership_off():
    space = Makerspace.objects.create(
        name="desk-anyone", slug="desk-anyone", enabled_modules=list(CORE),
        enabled_features=["inventory.self_checkout"], public_request_mode=MODE_ANYONE,
    )
    client = _staff_client(space, "desk-anyone-staff")

    response = client.post(
        reverse("hardware_requests:public-tool-evidence-url", args=[space.slug]),
        {"evidence_type": "issue", "content_type": "image/png"},
        format="json",
    )

    # Even an active staff membership is refused without presence, and with `membership`
    # off there is no member area to start one from -- hence no scan tab on this policy.
    assert response.status_code == 403, response.content
