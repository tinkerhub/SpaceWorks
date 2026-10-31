"""The real command preserves proven bytes until ordinary deletion settles them."""
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from apps.audit.models import AuditLog
from tests.document_safety.helpers import accepted_body, lab, usage
from tests.document_quota.helpers import delete, legacy_row, releases, upload
from tests.document_quota.version_store import VersionStore

pytestmark = pytest.mark.django_db(transaction=True)


def recompute(case):
    assert connection.get_autocommit() and not connection.in_atomic_block
    output = StringIO()
    call_command("recompute_storage", case.home.slug, stdout=output)
    return output.getvalue()


def bind_version_store(case, monkeypatch):
    store = VersionStore(page_size=1)
    case.store = store
    monkeypatch.setattr(case.module, "_client", lambda: store)
    monkeypatch.setattr(case.module, "_public_client", lambda: store)
    store.boundary = lambda: outside_transaction()
    return store


def outside_transaction():
    assert not connection.in_atomic_block, "Provider I/O under application SQL locks"


@pytest.mark.parametrize("kind", ["receipt", "asset"])
@pytest.mark.parametrize("observed", ["delete-marker", "latest-missing", "smaller", "larger"])
def test_command_then_actual_delete_preserves_unrelated_real_debit(
    kind, observed, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    store = bind_version_store(case, monkeypatch)
    row, charge, body = upload(case)
    neighbor, neighbor_charge, neighbor_body = upload(case, variant=True)
    assert usage(case) == len(body) + len(neighbor_body)
    if observed == "delete-marker":
        store.mark_deleted(row.object_key)  # Hidden retained DATA + latest marker.
    elif observed == "latest-missing":
        store.objects.pop(row.object_key)  # HEAD 404; listing still sees retained data.
    else:
        store.seed(row.object_key, b"x" if observed == "smaller" else b"x" * (len(body) + 999))
    assert store.versions[row.object_key]
    immutable_audit = list(AuditLog.objects.order_by("pk").values())
    assert f"total={len(body) + len(neighbor_body)} bytes" in recompute(case)
    assert usage(case) == len(body) + len(neighbor_body)
    assert list(AuditLog.objects.order_by("pk").values()) == immutable_audit
    assert delete(case, row).status_code == 204
    assert not store.versions.get(row.object_key) and not store.markers.get(row.object_key)
    assert usage(case) == len(neighbor_body)
    release = releases(case).get()
    assert release.meta["bytes"] == len(body)
    assert release.meta["charge_event_uuid"] == str(charge.event_uuid)
    assert case.model.objects.filter(pk=neighbor.pk).exists()
    assert store.objects[neighbor.object_key][0] == neighbor_body
    assert not releases(case).filter(meta__charge_event_uuid=str(neighbor_charge.event_uuid)).exists()
    assert f"total={len(neighbor_body)} bytes" in recompute(case)
    assert usage(case) == len(neighbor_body)


@pytest.mark.parametrize("kind", ["receipt", "asset"])
@pytest.mark.parametrize("observed", [None, b"x", b"legacy observed bytes"])
def test_legacy_head_only_reconciliation_never_mints_a_refundable_charge(
    kind, observed, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    row = legacy_row(case)
    if observed is not None:
        case.store.seed(row.object_key, observed)
    # The warranty fixture deliberately declares 99999 bytes; HEAD alone counts.
    expected = len(observed) if observed is not None else 0
    assert f"total={expected} bytes" in recompute(case)
    assert usage(case) == expected
    assert delete(case, row).status_code == 204
    assert usage(case) == expected and not releases(case).exists()
    assert "total=0 bytes" in recompute(case)
    assert usage(case) == 0
