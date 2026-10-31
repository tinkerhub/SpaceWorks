"""Portable projection omits source purge authority and target creation resets it."""

from types import SimpleNamespace
import uuid

import pytest
from django.utils import timezone

from apps.data_export.archive import project_row
from apps.data_export.datasets import DATASETS
from apps.data_export.types import Fidelity
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.target_creation import create_target_makerspace

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("legacy_carried_intent", [False, True])
def test_real_portable_makerspace_projection_and_target_creation_clear_source_purge_intent(
    legacy_carried_intent,
):
    source = Makerspace.objects.create(name="Source purge intent", slug="source-purge-intent")
    started = timezone.now()
    Makerspace.objects.filter(pk=source.pk).update(archived_at=started, purge_started_at=started)
    source.refresh_from_db()
    projected = project_row(DATASETS[(Fidelity.PORTABLE, "makerspace/config.csv")], source, set())
    assert source.purge_started_at == started
    assert "purge_started_at" not in projected
    if legacy_carried_intent:
        # The target projection also owns this field if an older source carried it.
        projected["purge_started_at"] = started.isoformat()
    archive = SimpleNamespace(rows=lambda label: iter([projected]))
    target = create_target_makerspace(
        archive, SimpleNamespace(pk=uuid.uuid4()),
        target_identity={"name": "Imported target", "slug": "imported-target"},
    )
    target.refresh_from_db()
    assert target.purge_started_at is None
    assert target.name == "Imported target"
    source.refresh_from_db()
    assert source.purge_started_at == started
