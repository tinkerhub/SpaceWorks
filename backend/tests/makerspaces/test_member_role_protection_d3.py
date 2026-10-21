"""The protected Member role is fixed: no rename, no re-slug, no actions (D3).

Its slug is how invitations, referrals and open joins find the community role, and
"grants no actions" is what makes an invitation a community one. Renaming it or giving
it actions would quietly turn every member into staff.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceRole


pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    space = Makerspace.objects.create(name="Member role", slug="d3-member-role")
    superadmin = User.objects.create_user(
        username="d3-member-role-admin", email="d3-member-role-admin@example.test",
        role=User.Role.SUPERADMIN, is_staff=True, is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(superadmin)
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    return client, f"/api/v1/admin/makerspaces/{space.pk}/roles/{role.pk}", role


@pytest.mark.parametrize(
    "payload",
    [{"name": "Community"}, {"granted_actions": ["view_inventory"]}],
)
def test_member_role_cannot_be_renamed_or_granted_actions(setup, payload):
    client, url, role = setup

    response = client.patch(url, payload, format="json")

    role.refresh_from_db()
    assert response.status_code == 409, response.data
    assert response.data["code"] == "role_conflict"
    assert (role.name, role.slug, role.granted_actions) == ("Member", "member", [])


def test_member_role_accepts_a_no_op_echo_of_its_current_values(setup):
    client, url, role = setup

    response = client.patch(url, {"name": "Member", "granted_actions": []}, format="json")

    assert response.status_code == 200, response.data
