"""Fresh database admission before reads and again before the authoritative SET."""
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.utils import timezone

from apps.backup.models import DeploymentRecoveryState
from apps.backup.not_restored import TenantNotRestored
from apps.makerspaces.management.commands.recompute_storage import Command
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import apply_profile
from apps.makerspaces.module_profiles import MINIMAL
from apps.makerspaces.purge_intent import commit_intent
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from tests.makerspaces.module_cleanup_support import module_receipt
from tests.makerspaces.storage_recompute_faults import instrument, updates
from tests.makerspaces.storage_recompute_support import (
    counter, image_request, locks, recompute, storage_case,
)
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)

REFUSALS = [
    "source-closed", "not-restored", "archived", "importing", "purge-intent",
    "module-purge", "recovery-missing", "target_import", "quiesced", "quarantined",
]


def change_admission(case, state):
    space = case.space
    if state == "source-closed":
        # Existing canonical, constraint-valid gate fixture, with real live owner.
        close_gate(space, case.actor)
    elif state == "not-restored":
        from tests.backup.test_not_restored_state_e7 import _component, _operation
        _component(_operation(makerspace_id=space.pk), space.pk)
    elif state in {"archived", "purge-intent"}:
        Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
        if state == "purge-intent":
            # Persist actual immutable intent plus its required audit proof.
            commit_intent(space.pk, case.actor, expected_slug=space.slug)
    elif state == "importing":
        Makerspace.objects.filter(pk=space.pk).update(lifecycle_state="importing")
    elif state == "module-purge":
        apply_profile(space, MINIMAL, case.actor)
        module_receipt(space)
    elif state == "recovery-missing":
        DeploymentRecoveryState.objects.filter(pk=1).delete()
    else:
        DeploymentRecoveryState.objects.filter(pk=1).update(mode=state)


@pytest.mark.parametrize("state", REFUSALS)
def test_fresh_admission_refuses_stale_selected_tenant_before_provider_or_counter(
    storage_case, monkeypatch, state,
):
    case = storage_case
    # A real existing image makes an accidental scan observable to provider transport.
    key, _size = case.staged()
    image_request(case.space, case.actor, key=key)
    Makerspace.objects.filter(pk=case.space.pk).update(storage_bytes_used=321)
    stale = Makerspace.objects.get(pk=case.space.pk)
    case.store.calls.clear()
    opened = instrument(monkeypatch)
    output = StringIO()
    command = Command(stdout=output)
    with boundary_tenant_write(case.space.pk, exclusive=True):
        # Inject a real committed admission-state change while preserving every
        # immutable identity/intent field. No admission/ownership function is mocked.
        change_admission(case, state)
        with pytest.raises((ValidationError, SourceMigrationGateClosed, TenantNotRestored)):
            command._recompute(stale)
    assert case.store.calls == [] and counter(case.space) == 321
    assert len(opened) == 1 and not updates(opened[0]) and opened[0].raw.closed
    assert "total=" not in output.getvalue() and locks(case.space.pk) == []


@pytest.mark.parametrize("state", ["source-closed", "archived", "module-purge", "quiesced"])
def test_fresh_final_admission_rejects_real_change_after_scan_before_set(
    storage_case, monkeypatch, state,
):
    case = storage_case
    key, _size = case.staged()
    image_request(case.space, case.actor, key=key)
    Makerspace.objects.filter(pk=case.space.pk).update(storage_bytes_used=321)
    changed = []
    head = case.store.head_object

    def drift_after_head(**params):
        result = head(**params)
        if not changed:
            change_admission(case, state)
            changed.append(True)
        return result

    monkeypatch.setattr(case.store, "head_object", drift_after_head)
    opened = instrument(monkeypatch)
    output = StringIO()
    recompute(case.space, output)
    assert changed == [True] and counter(case.space) == 321
    assert "reconciliation refused" in output.getvalue() and "total=" not in output.getvalue()
    assert len(opened) == 1 and not updates(opened[0]) and opened[0].raw.closed
    assert locks(case.space.pk) == []


@pytest.mark.parametrize("state", ["source-closed", "module-purge", "not-restored"])
def test_actual_command_retains_typed_closed_skip_and_module_warning(storage_case, state):
    case = storage_case
    Makerspace.objects.filter(pk=case.space.pk).update(storage_bytes_used=321)
    change_admission(case, state)
    output = StringIO()
    if state == "not-restored":
        with pytest.raises(CommandError, match="not found"):
            recompute(case.space, output)
    else:
        recompute(case.space, output)
        assert ("source closed" if state == "source-closed" else "module purge pending") in output.getvalue()
    assert case.store.calls == [] and counter(case.space) == 321
    assert "total=" not in output.getvalue() and locks(case.space.pk) == []
