"""Dedicated Origin middleware retains its raw N; central origin still fans out."""
import json

import pytest

from apps.makerspaces.models import Makerspace
from tests.box_parent_safety.pg_helpers import workers

from .callers import assert_retry, oidc_call
from .observations import NProof, TransitionProbe, exclusive_n, row_lock, source_statement
from .state import domain, tenant_and_transition_audits

pytestmark = pytest.mark.django_db(transaction=True)


def dedicated_origin(space):
    space.frontend_domain = "claim.example.test"
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space.save(update_fields=["frontend_domain", "frontend_domain_status", "updated_at"])
    return "https://claim.example.test"


@pytest.mark.parametrize("claim_lab", [1], indirect=True)
def test_real_dedicated_origin_raw_prehold_can_transition_unchanged_single_maker(
    claim_lab, monkeypatch, record_property,
):
    origin = dedicated_origin(claim_lab.spaces[0])
    prepared = oidc_call(claim_lab, monkeypatch, origin=origin)
    key = claim_lab.spaces[0].pk
    proof, probe = NProof([key], record_property), TransitionProbe()
    with workers() as start, probe:
        request = start(probe.run(prepared.call))
        probe.before_rows.wait(request)
        proof.observe("dedicated_raw_N_before_identity_rows")
        exclusive = start(lambda: exclusive_n(key))
        proof.queued(exclusive, key)
        probe.before_rows.release.set()
        probe.audit.wait(request)
        proof.observe("dedicated_raw_N_actual_audit_INSERT")
        proof.queued(exclusive, key)
        probe.audit.release.set()
        probe.commit.wait(request)
        proof.observe("dedicated_raw_N_outer_commit")
        proof.queued(exclusive, key)
        probe.commit.release.set()
        response = request.finish()
        assert exclusive.finish() == "exclusive N acquired"
    proof.released()
    assert response.status_code == 200, response.content
    assert response.json()["outcome"] == "transitioned"
    claim_lab.user.refresh_from_db()
    claim_lab.credentials[0].presence.refresh_from_db()
    assert claim_lab.user.is_walk_in is False
    assert claim_lab.credentials[0].presence.ended_at is not None
    record_property("dedicated_origin_full_SQL", json.dumps(probe.sql, default=str))


def test_dedicated_higher_origin_with_new_lower_target_scope_returns_friendly_retry(
    claim_lab, monkeypatch,
):
    origin = dedicated_origin(claim_lab.spaces[1])
    prepared = oidc_call(claim_lab, monkeypatch, origin=origin)
    before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=True)
    with workers() as start:
        blocker = start(lambda: exclusive_n(claim_lab.spaces[0].pk), pause=source_statement)
        blocker.paused()
        request = start(prepared.call)
        response = request.finish()
        # It returns while lower N remains exclusive: no lower acquisition can
        # hide behind a fast acquire/release or an incomplete SQL capture.
        blocker.finish()
    assert_retry(response, "oidc", oidc_status=503)
    assert response.json()["code"] == "tenant_migration_gate_unavailable"
    assert not [statement for statement in request.statements if row_lock(statement.sql)]
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=True) == audits
