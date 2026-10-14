"""The deleted updates app has no surfaces; its migration removes stored state."""

from importlib import import_module

import pytest
from django.apps import apps
from django.contrib import admin
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.urls import NoReverseMatch, reverse
from drf_spectacular.generators import SchemaGenerator

from apps.accounts.models import User
from apps.makerspaces import module_registry
from apps.makerspaces.module_profiles import PROFILES, profile_modules
from apps.separability.tombstones import SEPARABLE_APPS
from tests.return_helpers import authenticated_client, make_space, make_user


@pytest.mark.parametrize(
    "name", ["admin-platform-update-settings", "admin-platform-update-now"]
)
def test_retired_update_routes_cannot_be_reversed(name):
    with pytest.raises(NoReverseMatch):
        reverse(name)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/platform/update-settings",
        "/api/v1/admin/platform/update-settings/update-now",
    ],
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_retired_update_endpoints_return_404_even_for_an_active_superadmin(path, method):
    root = make_user(
        "updates-retired-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    client = authenticated_client(root)

    assert getattr(client, method)(path).status_code == 404


def test_only_the_retained_model_survives_for_one_release():
    # Kept solely so rollback and compound backups keep working; it has no surfaces.
    assert all(model._meta.app_label != "updates" for model in admin.site._registry)
    assert [model.__name__ for model in apps.get_app_config("updates").get_models()] == [
        "PlatformUpdateSettings"
    ]


def test_the_schema_contains_no_update_settings_paths():
    paths = SchemaGenerator().get_schema(request=None, public=True)["paths"]

    assert not any("update-settings" in path for path in paths)


def test_updates_is_no_longer_a_module():
    assert "updates" not in module_registry.BY_KEY
    assert "updates" not in SEPARABLE_APPS


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_no_install_profile_includes_updates(profile):
    assert "updates" not in profile_modules(profile)


@pytest.mark.django_db
def test_removal_migration_strips_the_key_but_keeps_rollback_state():
    """A failed deploy rolls back WITHOUT migrations, so the previous image must still find
    its `updates` migration recorded and its table present; only the module key goes."""
    migration = import_module(
        "apps.makerspaces.migrations.0070_remove_in_app_updates"
    )
    # Load the historical model without rewinding and replaying the migration graph.
    executor = MigrationExecutor(connection)
    historical_apps = executor.loader.project_state(migration.Migration.dependencies).apps
    space = make_space("updates-migration")
    unaffected = make_space("updates-migration-unaffected")
    type(space).objects.filter(pk=space.pk).update(
        enabled_modules=["backup", "updates", "payments", "updates"]
    )
    type(unaffected).objects.filter(pk=unaffected.pk).update(enabled_modules=["backup"])

    table = "updates_platformupdatesettings"
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {connection.ops.quote_name(table)} (id integer)")
    recorder = MigrationRecorder(connection)
    recorder.record_applied("updates", "0001_initial")

    for _ in range(2):  # idempotent
        with connection.schema_editor() as schema_editor:
            migration.remove_update_module_key(historical_apps, schema_editor)
        space.refresh_from_db()
        unaffected.refresh_from_db()
        assert space.enabled_modules == ["backup", "payments"]
        assert unaffected.enabled_modules == ["backup"]
        assert table in connection.introspection.table_names()
        assert recorder.migration_qs.filter(app="updates", name="0001_initial").exists()
