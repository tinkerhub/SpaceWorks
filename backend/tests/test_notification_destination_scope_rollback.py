"""A destination write rejected for an unknown scope target must persist nothing.

The 400 used to be returned from INSIDE the atomic block, after `destination.save()`,
so the block exited normally and committed: POST left an unscoped room (which receives
every alert) with no audit entry, and PUT kept the field edits it had just refused.
"""

import pytest

from apps.audit.models import AuditLog
from apps.integrations.models_destinations import NotificationDestination
from apps.machines.models import MachineType
from tests.test_notification_admin_api import (  # noqa: F401 -- autouse fixture
    client_for,
    destinations_url,
    make_space,
    make_user,
    public_webhook_dns,
)

pytestmark = pytest.mark.django_db


def _foreign_type(slug):
    other = make_space(f"{slug}-other")
    return MachineType.objects.create(makerspace=other, name="Foreign", slug=f"{slug}-ft")


def test_post_with_unknown_scope_target_persists_nothing():
    space = make_space("dest-rollback-post")
    client = client_for(make_user("dest-rollback-post-manager", space))
    foreign = _foreign_type("dest-rollback-post")

    response = client.post(
        destinations_url(space),
        {
            "channel": "slack",
            "label": "Should not exist",
            "webhook_url": "https://hooks.example/a",
            "scope": {"machine_type_ids": [foreign.pk]},
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data == {"detail": "Unknown scope target.", "unknown": [foreign.pk]}
    assert not NotificationDestination.objects.filter(makerspace=space).exists()
    assert not AuditLog.objects.filter(action="notification.destination_created").exists()


def test_put_with_unknown_scope_target_changes_nothing():
    space = make_space("dest-rollback-put")
    client = client_for(make_user("dest-rollback-put-manager", space))
    foreign = _foreign_type("dest-rollback-put")
    created = client.post(
        destinations_url(space),
        {"channel": "slack", "label": "Original", "webhook_url": "https://hooks.example/a"},
        format="json",
    )
    assert created.status_code == 201
    before = NotificationDestination.objects.get(pk=created.data["id"])

    response = client.put(
        f"{destinations_url(space)}/{before.pk}",
        {
            "channel": "slack",
            "label": "Renamed",
            "is_active": False,
            "webhook_url": "https://hooks.example/b",
            "scope": {"machine_type_ids": [foreign.pk]},
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["unknown"] == [foreign.pk]
    after = NotificationDestination.objects.get(pk=before.pk)
    assert (after.label, after.is_active) == ("Original", True)
    assert after.get_webhook_url() == "https://hooks.example/a"
    assert not after.machine_type_scopes.exists()
    assert not AuditLog.objects.filter(action="notification.destination_updated").exists()
