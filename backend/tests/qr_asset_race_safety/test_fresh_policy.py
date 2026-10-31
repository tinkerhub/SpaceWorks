"""Committed policy changes during real Maker, QR, and final asset waits."""
import pytest
from django.db import transaction
from django.urls import reverse

from apps.accounts.models import User
from apps.inventory.models import InventoryAsset
from apps.makerspaces.models import MakerspaceRole
from tests.box_parent_safety.pg_helpers import (
    assert_maker_mode, blocked_by, maker_lock, workers,
)
from tests.qr_asset_race_safety.helpers import (
    assert_no_domain_write, asset_http, asset_lock, backend_pid, code, lab,
    qr_lock, state,
)
from tests.qr_target_safety_helpers import jwt_client, membership, staff

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("existing", [False, True], ids=["create", "reuse"])
def test_actual_module_uninstall_commits_while_asset_qr_waits(lab, existing):
    if existing:
        code(lab)
    before = state()
    with workers() as start:
        uninstall = start(lambda: lab.move_api.post(
            reverse("admin-module-uninstall", args=[lab.home.pk]),
            {"key": "asset_units"}, format="json",
        ), pause=maker_lock)
        uninstall.paused()
        assert_maker_mode(next(s for s in uninstall.statements if maker_lock(s)), "FOR UPDATE")
        api = start(lambda: asset_http(lab))
        assert_maker_mode(blocked_by(api, uninstall.pid), "FOR NO KEY UPDATE")
        response = uninstall.finish()
        assert response.status_code == 200, response.data
        assert response.data["uninstalled"] == ["asset_units"]
        committed = state()
        denied = api.finish()
    assert denied.status_code == 400, denied.data
    assert denied.data == {"module": "asset_units is disabled for this makerspace."}
    assert state() == committed
    assert before["boxes.qrcode"] == committed["boxes.qrcode"]
    assert_no_domain_write(api.statements)


@pytest.mark.parametrize("wait,existing", [("qr", True), ("asset", True), ("asset", False)],
                         ids=["existing-qr-wait", "existing-asset-wait", "new-asset-wait"])
@pytest.mark.parametrize("change", ["permission", "inactive", "suspended"])
def test_actor_and_action_rechecked_after_last_row_lock_wait(lab, wait, existing, change):
    qr = code(lab) if existing else None
    role = MakerspaceRole.objects.create(
        makerspace=lab.home, name="Asset QR writer", slug="asset-qr-writer",
        granted_actions=["view_inventory", "manage_qr"],
    )
    member = lab.actor.makerspace_memberships.get(makerspace=lab.home)
    member.role, member.assigned_role = "custom", role
    member.save(update_fields=["role", "assigned_role"])
    with workers() as start:
        with transaction.atomic():
            if wait == "qr":
                type(qr).objects.select_for_update().get(pk=qr.pk)
            else:
                InventoryAsset.objects.select_for_update().get(pk=lab.asset.pk)
            api = start(lambda: asset_http(lab))
            pending = blocked_by(api, backend_pid(), qr_lock if wait == "qr" else asset_lock)
            assert pending.params
            if change == "permission":
                MakerspaceRole.objects.filter(pk=role.pk).update(granted_actions=["view_inventory"])
            elif change == "inactive":
                User.objects.filter(pk=lab.actor.pk).update(is_active=False)
            else:
                User.objects.filter(pk=lab.actor.pk).update(access_status="suspended")
        committed = state()
        response = api.finish()
    # Revocation before the fresh scoped asset lookup is hidden by its queryset;
    # revocation during the final asset wait is refused by require_action (403).
    assert response.status_code == (404 if change == "permission" and wait == "qr" else 403), response.data
    assert response.data
    assert state() == committed
    assert_no_domain_write(api.statements)


@pytest.mark.parametrize("denial", ["foreign-role", "foreign-origin", "member-session"])
def test_wrong_tenant_role_or_submission_obeys_global_http_policy(lab, denial):
    headers = {}
    if denial == "foreign-role":
        lab.api = jwt_client(staff(lab.other))
    elif denial == "foreign-origin":
        membership(lab.actor, lab.other)
        headers["HTTP_ORIGIN"] = f"https://{lab.other.frontend_domain}"
    else:
        from apps.accounts.tokens import SpaceWorksRefreshToken
        token = SpaceWorksRefreshToken.for_user(lab.actor)
        token["surface"] = "member"
        lab.api.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    before = state()
    response = asset_http(lab, **headers)
    assert response.status_code == (404 if denial == "foreign-role" else 403), response.data
    assert response.data
    assert state() == before
