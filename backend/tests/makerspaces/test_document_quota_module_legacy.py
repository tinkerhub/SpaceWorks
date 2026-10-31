"""Old canonical pending authority remains usable without inventing receipt credit."""
import hashlib
import json

import pytest

from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_graph import graph_rows, holder_sites, rollback_bindings, snapshot
from apps.makerspaces.module_purge_plans import BY_KEY
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import PurgeStorageRefused
from tests.document_safety.helpers import cap, usage
from tests.makerspaces.document_quota_module_support import (
    disable_procurement, document_module_case, local_document_identity, module_store, releases,
)
from tests.makerspaces.module_cleanup_support import H, module_receipt, seed_versions

pytestmark = pytest.mark.django_db(transaction=True)


def test_previous_snapshot_pending_receipt_keeps_old_digest_through_failure_and_retry(document_module_case):
    case = document_module_case
    cap(case, 1000000, used=1000)
    key = f"procurement/{case.home.pk}/{case.target.pk}/receipts/{H}.pdf"
    native = case.model.objects.create(to_buy_item=case.target, object_key=key)
    seed_versions(case.store, "private", key)
    disable_procurement(case)
    plan = BY_KEY["procurement"]
    rows = graph_rows(case.home, plan)
    sites = holder_sites(rows)
    bindings = rollback_bindings(case.home, "procurement")
    # Previous canonical serializer, independently reproduced: procurement had no facts.
    previous_payload = {
        "rows": {label: sorted(str(pk) for pk in ids) for label, ids in sorted(rows.items())},
        "sites": sorted(sites), "rollback": bindings, "charge_facts": [], "provenance": [],
    }
    old_digest = hashlib.sha256(json.dumps(
        previous_payload, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    # Construct an actual OLD pending immutable receipt with that frozen payload.
    old = module_receipt(
        case.home, "procurement", graph_digest=old_digest, holder_sites=sites,
        rollback_bindings=bindings,
        exact_keys=[["private", value] for value in sorted({key, f"staging/{key}"})],
    )
    assert snapshot(case.home, plan)[0] == old_digest
    case.store.failure = "storage"
    with pytest.raises(PurgeStorageRefused):
        purge_module(case.home, "procurement", case.superadmin)
    retained = ModulePurgeReceipt.objects.get(pk=old.pk)
    assert retained.graph_digest == old_digest and retained.charge_obligations == []
    assert retained.graph_purged_at is None and retained.last_error_code == "cleanup_unconfirmed"
    assert ModulePurgeReceipt.objects.count() == 1
    assert case.model.objects.filter(pk=native.pk).exists()
    assert usage(case) == 1000 and not releases(case).exists()
    case.store.failure = None
    completed = retry_cleanup(old.pk, case.superadmin)
    assert completed.pk == old.pk and completed.graph_digest == old_digest
    assert completed.graph_purged_at and completed.charge_obligations == []
    assert not case.model.objects.filter(pk=native.pk).exists() and not case.store.objects
    assert usage(case) == 1000 and not releases(case).exists()
    retry_cleanup(old.pk, case.superadmin)
    assert usage(case) == 1000 and not releases(case).exists()
