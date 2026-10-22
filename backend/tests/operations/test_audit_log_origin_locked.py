"""The staff audit log on an origin-locked (single-tenant) site.

`admin-audit-logs` is a query-scoped route: on a tenant origin it is reachable only with a
`?makerspace=` hint naming that origin's makerspace. The console's audit panel therefore
has to send the active makerspace, or production's staff site answers 403.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.services import record
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(
        name=slug, slug=slug, frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )


@pytest.fixture
def setup():
    space = _space("audit-origin-home")
    other = Makerspace.objects.create(name="audit-origin-other", slug="audit-origin-other")
    manager = User.objects.create_user(
        username="audit-origin-sm", email="audit-origin-sm@example.test",
        role=User.Role.SPACE_MANAGER, access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(makerspace=space, user=manager, role=MakerspaceMembership.Role.SPACE_MANAGER)
    record(manager, "makerspace.settings_updated", makerspace=space, target=space)
    record(None, "makerspace.settings_updated", makerspace=other, target=other)
    client = APIClient()
    client.force_authenticate(manager)
    return client, space, {"HTTP_ORIGIN": f"https://{space.frontend_domain}"}


def test_unhinted_audit_list_is_refused_on_a_tenant_origin(setup):
    client, _space_row, origin = setup
    assert client.get(reverse("admin-audit-logs"), **origin).status_code == 403


def test_makerspace_hinted_audit_list_works_and_holds_only_that_space(setup):
    client, space, origin = setup
    response = client.get(f"{reverse('admin-audit-logs')}?makerspace={space.id}", **origin)
    assert response.status_code == 200, response.data
    assert [row["target_id"] for row in response.data["results"]] == [str(space.pk)]
