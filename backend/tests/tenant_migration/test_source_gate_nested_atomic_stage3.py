"""A service transaction retains its own shared gate lock across nested phases."""

from unittest.mock import Mock

import pytest
from django.db import connections, transaction

from apps.tenant_migration import gate_locks
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor, make_space
from tests.tenant_migration.test_source_gate_locks import _try_xact_lock

pytestmark = pytest.mark.django_db(transaction=True)


def test_nested_atomic_boundary_reuses_owner_and_holds_lock_until_outer_commit(monkeypatch):
    space = make_space("nested-atomic-continuity")
    secondary = connections["default"].copy()
    new_connection = Mock(side_effect=AssertionError("nested transaction opened a fresh gate backend"))
    monkeypatch.setattr(gate_locks, "_new_lock_connection", new_connection)
    try:
        with transaction.atomic():
            with boundary_tenant_write(space.pk):
                with transaction.atomic(), boundary_tenant_write(space.pk):
                    assert _try_xact_lock(secondary, "exclusive", space.pk) is False
                assert _try_xact_lock(secondary, "exclusive", space.pk) is False
            assert _try_xact_lock(secondary, "exclusive", space.pk) is False
        assert _try_xact_lock(secondary, "exclusive", space.pk) is True
        new_connection.assert_not_called()
    finally:
        secondary.close()


@pytest.mark.parametrize("expired", [False, True])
def test_existing_atomic_owner_still_refuses_closed_gate_before_dispatch(expired):
    space = make_space("closed-atomic-boundary")
    close_gate(space, make_actor(), expired=expired)
    dispatch = Mock()
    with transaction.atomic():
        with pytest.raises(SourceMigrationGateClosed):
            with boundary_tenant_write(space.pk):
                dispatch()
    dispatch.assert_not_called()
