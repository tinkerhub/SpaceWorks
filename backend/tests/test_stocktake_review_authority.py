"""Stocktake approve/apply: superadmin, or a manage_makerspace holder who did not complete it."""
import pytest
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.operations import services
from apps.operations.models import StocktakeLine, StocktakeSession
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user

pytestmark = pytest.mark.django_db


def _completed(slug, completer=None):
    makerspace = make_space(slug)
    product = make_product(makerspace, total_quantity=5, available_quantity=5)
    stocktake = StocktakeSession.objects.create(makerspace=makerspace, started_by=completer)
    StocktakeLine.objects.create(
        stocktake=stocktake, product=product, expected_quantity=5, counted_quantity=4, variance_quantity=-1
    )
    if completer is not None:
        services.complete_stocktake(completer, stocktake)
    else:
        StocktakeSession.objects.filter(pk=stocktake.pk).update(status=StocktakeSession.Status.COMPLETED)
    stocktake.refresh_from_db()
    return makerspace, product, stocktake


def _post(user, stocktake, step):
    return authenticated_client(user).post(f"/api/v1/admin/stocktakes/{stocktake.id}/{step}", {}, format="json")


def _superadmin(username):
    return make_user(username, role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)


def test_complete_records_who_completed_it():
    counter = _superadmin("st-complete-sa")
    _ms, _product, stocktake = _completed("st-complete", completer=counter)
    assert stocktake.completed_by_id == counter.id


def test_space_manager_approves_and_applies_another_persons_stocktake():
    makerspace = make_space("st-sm-other")
    counter = make_member("st-sm-other-counter", makerspace, membership_role="inventory_manager", role=User.Role.REQUESTER)
    manager = make_member("st-sm-other-sm", makerspace)
    product = make_product(makerspace, total_quantity=5, available_quantity=5)
    stocktake = StocktakeSession.objects.create(makerspace=makerspace, started_by=counter)
    StocktakeLine.objects.create(
        stocktake=stocktake, product=product, expected_quantity=5, counted_quantity=4, variance_quantity=-1
    )
    assert _post(counter, stocktake, "complete").status_code == 200

    listed = authenticated_client(manager).get(f"/api/v1/admin/makerspace/{makerspace.id}/stocktakes")
    assert listed.data["results"][0]["can_approve"] is True
    approved = _post(manager, stocktake, "approve")
    assert approved.status_code == 200, approved.data
    assert (approved.data["can_approve"], approved.data["can_apply"]) == (False, True)
    applied = _post(manager, stocktake, "apply-adjustments")
    assert applied.status_code == 200, applied.data
    product.refresh_from_db()
    assert product.available_quantity == 4


def test_space_manager_cannot_review_a_stocktake_they_completed():
    makerspace = make_space("st-sm-own")
    manager = make_member("st-sm-own-sm", makerspace)
    _ms, _product, stocktake = _completed("st-sm-own-x", completer=None)
    StocktakeSession.objects.filter(pk=stocktake.pk).update(makerspace=makerspace, completed_by=manager)
    stocktake.refresh_from_db()

    detail = authenticated_client(manager).get(f"/api/v1/admin/stocktakes/{stocktake.id}")
    assert detail.data["can_approve"] is False
    assert _post(manager, stocktake, "approve").status_code == 403
    # The same rule binds the locked service, so the apply step cannot be reached either.
    StocktakeSession.objects.filter(pk=stocktake.pk).update(status=StocktakeSession.Status.APPROVED)
    assert _post(manager, stocktake, "apply-adjustments").status_code == 403
    stocktake.refresh_from_db()
    assert stocktake.status == StocktakeSession.Status.APPROVED


def test_legacy_stocktake_without_completer_is_superadmin_only():
    makerspace, product, stocktake = _completed("st-legacy", completer=None)
    manager = make_member("st-legacy-sm", makerspace)

    assert _post(manager, stocktake, "approve").status_code == 403
    superadmin = _superadmin("st-legacy-sa")
    assert _post(superadmin, stocktake, "approve").status_code == 200
    assert _post(manager, stocktake, "apply-adjustments").status_code == 403
    assert _post(superadmin, stocktake, "apply-adjustments").status_code == 200
    product.refresh_from_db()
    assert product.available_quantity == 4


def test_inventory_manager_cannot_approve():
    makerspace = make_space("st-im")
    counter = make_member("st-im-counter", makerspace)
    inventory_manager = make_member("st-im-im", makerspace, membership_role="inventory_manager", role=User.Role.REQUESTER)
    _ms, _product, stocktake = _completed("st-im-x", completer=counter)
    StocktakeSession.objects.filter(pk=stocktake.pk).update(makerspace=makerspace)

    response = _post(inventory_manager, stocktake, "approve")

    assert response.status_code == 403
    stocktake.refresh_from_db()
    assert stocktake.status == StocktakeSession.Status.COMPLETED


def test_control_plane_callers_obey_the_same_rule():
    makerspace, _product, stocktake = _completed("st-service", completer=None)
    manager = make_member("st-service-sm", makerspace)

    with pytest.raises(PermissionDenied):
        services.approve_stocktake(manager, stocktake)
