"""EVID-S02: both real PG winner orders of policy UPDATE and claim Maker NK."""
from datetime import timedelta

import pytest
from django.db import connection

from apps.evidence.models import EvidenceObjectRetentionState
from apps.evidence.retention_policy import update_policy
from apps.evidence.services_retention import _claim
from tests.evidence.safety_pg_helpers import policy_claim_race
from tests.evidence.safety_retention_helpers import (
    expiry_events, metadata, photo, safety_lab, usage,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("policy_first", [True, False], ids=["policy-wins", "claim-wins"])
def test_policy_update_and_claim_serialize_without_deadlock(monkeypatch, settings, policy_first):
    lab = safety_lab(monkeypatch, settings)
    evidence = photo(lab, charged=True)
    update_policy(lab.space, lab.actor, 30)  # race an actual UPDATE, not first INSERT
    assert not connection.in_atomic_block  # fixtures are visible to both sessions
    before = metadata(evidence)
    charged = usage(lab)
    calls = list(lab.store.calls)

    def policy():
        return update_policy(lab.space, lab.actor, 90)

    def claim():
        return _claim(evidence.pk, now=lab.now)

    def pause_after(sql):
        if policy_first:
            return sql.startswith('UPDATE "evidence_evidenceretentionpolicy"')
        return 'FROM "makerspaces_makerspace"' in sql and "FOR NO KEY UPDATE" in sql

    first, second, pids, captured, waited = policy_claim_race(
        policy if policy_first else claim, claim if policy_first else policy,
        pause_after=pause_after,
        waiter_clause="FOR NO KEY UPDATE" if policy_first else "FOR UPDATE",
    )

    assert len(set(pids.values())) == 2
    assert all(captured[name] for name in ("first", "second"))
    actual_claim = second if policy_first else first
    actual_policy = first if policy_first else second
    assert actual_policy["effective_days"] == 90
    policy_sql = captured["first" if policy_first else "second"]
    assert any(sql.startswith('UPDATE "evidence_evidenceretentionpolicy"') for sql, _ in policy_sql)
    claim_sql = captured["second" if policy_first else "first"]
    assert any('FROM "makerspaces_makerspace"' in sql and "FOR NO KEY UPDATE" in sql
               for sql, _ in claim_sql)
    assert waited in [" ".join(sql.split()) for sql, _ in captured["second"]]
    if policy_first:
        assert actual_claim is None
        assert not EvidenceObjectRetentionState.objects.filter(evidence=evidence).exists()
    else:
        assert actual_claim.policy_days == 30
        assert actual_claim.cutoff == lab.now - timedelta(days=30)
        state = EvidenceObjectRetentionState.objects.get(evidence=evidence)
        assert state.status == "expiring" and state.claim_token == actual_claim.token
    assert metadata(evidence) == before
    assert usage(lab) == charged and not expiry_events(evidence).exists()
    assert lab.store.calls == calls
