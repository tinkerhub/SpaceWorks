"""Desk handout on a space without the `membership` module (check-in mode in production).

Presence sessions and waiver acceptance are both recorded through member self-service, so
with the community module off no borrower can ever hold one. The handout used to demand an
open presence session regardless and refused every walk-in with `presence_required`; the
staffer at the desk is the presence witness there, exactly as staff acceptance is for the
borrow request (`public_views.RequestSubmitView`).
"""

from unittest.mock import Mock

import pytest
from django.test import override_settings

from apps.accounts.models import User
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import PublicToolLoan
from apps.makerspaces.request_access import MODE_CHECKED_IN
from apps.makerspaces.walk_in_services import create_walk_in_member
from tests.test_admin_direct_loans import (
    _direct_issue_evidence,
    authed,
    direct_url,
    make_admin,
    make_product,
    make_space,
)

pytestmark = pytest.mark.django_db

PROD_LIKE = [
    "public_inventory", "request_workflow", "staff_admin", "scanner", "evidence_uploads",
    "qr_management", "guest_handover", "containers", "asset_units",
]


def _checkin_space(slug):
    space = make_space(slug)
    space.enabled_modules = list(PROD_LIKE)
    space.public_request_mode = MODE_CHECKED_IN
    space.checkin_space_id = 1
    space.save()
    return space


def _allow_upload(monkeypatch):
    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        Mock(side_effect=lambda evidence, max_bytes: EvidenceValidationResult(size=123, content_type="image/jpeg")),
    )


def _issue(space, admin, borrower, product):
    return authed(admin).post(
        direct_url(space),
        {
            "borrower_id": borrower.id,
            "evidence_id": _direct_issue_evidence(space).id,
            "items": [{"product_id": product.id, "quantity": 1}],
        },
        format="json",
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_walk_in_handout_needs_no_presence_session_with_membership_off(monkeypatch):
    _allow_upload(monkeypatch)
    space = _checkin_space("handout-no-membership")
    admin = make_admin(space)
    walk_in = create_walk_in_member(admin, space, display_name="Ravi Kumar").user
    product = make_product(space)

    response = _issue(space, admin, walk_in, product)

    assert "membership" not in space.enabled_modules
    assert response.status_code == 201, response.data
    # The desk can tell open handouts apart by who holds them.
    assert response.data["borrower_name"] == "Ravi Kumar"
    assert PublicToolLoan.objects.get().requester == walk_in
    listed = authed(admin).get(direct_url(space))
    assert listed.data["results"][0]["borrower_name"] == "Ravi Kumar"


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_restricted_borrower_is_still_refused_with_membership_off(monkeypatch):
    """Dropping the presence half must not drop the account-standing half."""
    _allow_upload(monkeypatch)
    space = _checkin_space("handout-restricted")
    admin = make_admin(space)
    walk_in = create_walk_in_member(admin, space, display_name="Blocked Person").user
    walk_in.access_status = User.AccessStatus.RESTRICTED
    walk_in.save(update_fields=["access_status"])

    response = _issue(space, admin, walk_in, make_product(space))

    assert response.status_code == 403
    assert not PublicToolLoan.objects.exists()
