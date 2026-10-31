"""Stored SPA links, feature matrix and migration-state compatibility."""

from importlib import import_module
from urllib.parse import quote

import pytest
from django.db import migrations
from django.db.migrations.loader import MigrationLoader

from apps.integrations.models import (
    ChatTemplate, NotificationChannel, NotificationDeliveryLog, NotificationFeature,
    NotificationPreference, NotificationRecipient,
)
from apps.integrations.notification_catalog import default_state
from apps.notifications.models import Notification
from tests.own_requests.own_requests_support import (
    history_lab, providers, submit_hardware, submit_service,
)
from tests.return_helpers import authenticated_client, make_member

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("domain_status,type_slug", [
    ("", "laser"), ("pending", "laser"), ("verified", "laser"), ("verified", ""),
    ("", "laser café"),
])
def test_actual_staff_rows_link_to_existing_spa_routes(
    history_lab, django_capture_on_commit_callbacks, settings, domain_status, type_slug,
):
    # Managed deployments retain pending domains; self-host deliberately verifies them.
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    settings.INFRA_HOSTS = {"testserver"}
    lab = history_lab
    lab.space.frontend_domain = "own-console.example.test" if domain_status else ""
    lab.space.frontend_domain_status = domain_status
    lab.space.save(update_fields=["frontend_domain", "frontend_domain_status"])
    lab.space.refresh_from_db(fields=["frontend_domain", "frontend_domain_status"])
    assert lab.space.frontend_domain_status == domain_status
    lab.kind.slug = type_slug
    lab.kind.save(update_fields=["slug"])
    with django_capture_on_commit_callbacks(execute=True):
        submit_hardware(lab)
        submit_service(lab)
    prefix = "/admin" if domain_status == "verified" else f"/m/{quote(lab.space.slug, safe='')}/admin"
    segment = str(lab.kind.pk) + ("-" + quote(type_slug, safe="") if type_slug else "")
    assert Notification.objects.get(event="request.submitted").url_path == f"{prefix}/requests"
    assert Notification.objects.get(event="machine_service.submitted").url_path == f"{prefix}/machines/{segment}"


def test_new_feature_matrix_is_module_gated_and_preserves_explicit_false(history_lab):
    lab = history_lab
    manager = make_member("matrix-owner", lab.space)
    client = authenticated_client(manager)
    path = f"/api/v1/admin/makerspace/{lab.space.pk}/notification-rules"
    preference = NotificationPreference.objects.create(
        makerspace=lab.space, feature="machine_service", channel="telegram", enabled=False,
    )
    response = client.get(path)
    assert response.status_code == 200, response.data
    assert "machine_service" in {row["key"] for row in response.data["features"]}
    cell = next(row for row in response.data["preferences"]
                if row["feature"] == "machine_service" and row["channel"] == "telegram")
    assert cell == {"feature": "machine_service", "channel": "telegram", "enabled": False, "source": "override"}
    for channel in NotificationChannel:
        assert default_state("machine_service", channel) is (channel == "telegram")
    lab.space.enabled_modules.remove("machine_service")
    lab.space.save(update_fields=["enabled_modules"])
    response = client.get(path)
    assert response.status_code == 200
    assert "machine_service" not in {row["key"] for row in response.data["features"]}
    assert not any(row["feature"] == "machine_service" for row in response.data["preferences"])
    preference.refresh_from_db()
    assert preference.enabled is False


def test_choice_migration_only_alters_four_fields_and_matches_current_model_state():
    module = import_module("apps.integrations.migrations.0025_machine_service_notification_feature")
    migration = module.Migration("0025_machine_service_notification_feature", "integrations")
    assert migration.dependencies == [("integrations", "0024_machinetypeemailtemplate")]
    expected = {"notificationpreference", "notificationdeliverylog", "notificationrecipient", "chattemplate"}
    assert len(migration.operations) == 4
    assert all(type(operation) is migrations.AlterField for operation in migration.operations)
    assert {operation.model_name for operation in migration.operations} == expected
    assert all(operation.name == "feature" for operation in migration.operations)
    loader = MigrationLoader(None)
    state = loader.project_state([("integrations", "0025_machine_service_notification_feature")])
    for model in (NotificationPreference, NotificationDeliveryLog, NotificationRecipient, ChatTemplate):
        historical = state.apps.get_model("integrations", model.__name__)
        assert list(historical._meta.get_field("feature").choices) == NotificationFeature.choices
        assert model._meta.get_field("feature").deconstruct()[1:] == historical._meta.get_field("feature").deconstruct()[1:]
