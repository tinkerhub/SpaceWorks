"""Defensive cleanup of explicitly injected legacy/fault claim-presence states."""
import json

import pytest
from django.db import connection, transaction

from apps.accounts.claim_tokens import ClaimAccessToken
from apps.accounts.models_claim import MemberClaimCode
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from tests.box_parent_safety.pg_helpers import blocked_by, workers
from tests.qr_http_ownership_safety.assertions import all_rows, dml, statements
from tests.qr_http_ownership_safety.auth_setup import AUTH_MODELS, claim_session, freeze
from tests.qr_http_ownership_safety.cases import prepared
from tests.qr_http_ownership_safety.p_observations import identity, source_locks
from tests.qr_http_ownership_safety.p_protocol import full_dispatch
from tests.qr_source_safety.state_helpers import state

from .observations import Checkpoint, NProof, exclusive_n, source_statement, wait_raw_n
from .opaque import opaque
from .conftest import membership

pytestmark = pytest.mark.django_db(transaction=True)


def invalid_response(response):
    assert response.status_code == 401, response.content
    assert response.json()["detail"] == "Claim session is no longer active."


@pytest.mark.parametrize("invalid", ["revoked", "expired-row"])
@pytest.mark.parametrize("gate", ["quiesced", "opaque"])
def test_legacy_fault_cleanup_defers_401_without_any_auth_domain_or_audit_write(
    closure_lab, invalid, gate,
):
    session = claim_session(closure_lab, invalid)
    case = prepared(closure_lab, "qr-boxes", session.client)
    freeze(closure_lab) if gate == "quiesced" else opaque(closure_lab.home)
    before, auth = state(), all_rows(*AUTH_MODELS)
    with statements() as sql:
        response = case.call()
    invalid_response(response)
    assert state() == before and all_rows(*AUTH_MODELS) == auth
    assert not [row for row in sql if dml(row["sql"])], sql
    assert any('"accounts_memberclaimcode"' in row["sql"] for row in sql)


@pytest.mark.parametrize("invalid", ["revoked", "expired-row"])
def test_cancel_actual_legacy_cleanup_n_wait_defers_401_without_dml(
    closure_lab, invalid, record_property,
):
    session = claim_session(closure_lab, invalid)
    case = prepared(closure_lab, "qr-boxes", session.client)
    before, auth = state(), all_rows(*AUTH_MODELS)
    with workers() as start:
        blocker = start(lambda: exclusive_n(closure_lab.home.pk), pause=source_statement)
        blocker.paused()
        baseline = {identity(row) for row in source_locks()}
        request = start(case.call)
        owned_pid = wait_raw_n(closure_lab.home.pk, blocker.pid, baseline, record_property)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_cancel_backend(%s)", [owned_pid])
            assert cursor.fetchone()[0] is True
        invalid_response(request.finish())
        assert not [s for s in request.statements if dml(s.sql)]
        # If cleanup tried to reconnect/reacquire, this held exclusive N would
        # keep the request blocked instead of allowing the required generic 401.
        blocker.finish()
        record_property("cancelled_cleanup_full_SQL", json.dumps([vars(s) for s in request.statements], default=str))
    assert state() == before and all_rows(*AUTH_MODELS) == auth


def test_legacy_cleanup_uses_database_owner_not_forged_token_or_request_tenant(
    closure_lab, settings, record_property,
):
    session = claim_session(closure_lab, "revoked")
    raw = session.client._credentials["HTTP_AUTHORIZATION"].split(" ", 1)[1]
    token = ClaimAccessToken(raw)
    token["claim_makerspace_id"] = closure_lab.other.pk
    session.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}",
                               HTTP_X_MAKERSPACE_ID=str(closure_lab.other.pk))
    case = prepared(closure_lab, "qr-boxes", session.client)
    case.data["makerspace_id"] = closure_lab.other.pk
    # Foreign refusal must not leak into the owning claim's repair.
    from .state import frozen

    frozen(closure_lab.other, closure_lab.root)
    before = all_rows(*AUTH_MODELS)
    response, sql = full_dispatch(settings, case, "presence_presencesession", record_property,
        cleanup=True, cleanup_makerspace_id=closure_lab.home.pk)
    invalid_response(response)
    session.presence.refresh_from_db()
    assert session.presence.ended_at is not None
    after = all_rows(*AUTH_MODELS)
    expected = dict(before)
    expected["presence.presencesession"] = [{**before["presence.presencesession"][0],
        "ended_at": session.presence.ended_at, "ended_by_id": None, "end_reason": "claim_revoked"}]
    assert after == expected
    event = AuditLog.objects.filter(action="presence.ended_claim_revoked").get()
    assert (event.makerspace_id, event.actor_id, event.meta) == (
        closure_lab.home.pk, None, {"claim_session_id": str(session.claim.session_id)})
    assert all('"presence_presencesession"' in row["sql"] or '"audit_auditlog"' in row["sql"]
               for row in sql if dml(row["sql"]))


def test_legacy_fault_claim_provenance_changed_during_claim_row_wait_defers_without_foreign_write(
    closure_lab, record_property,
):
    session = claim_session(closure_lab, "revoked")
    case = prepared(closure_lab, "qr-boxes", session.client)
    foreign = membership(closure_lab.other, session.member)
    winner = Checkpoint()
    proof = NProof([closure_lab.home.pk], record_property)
    before, auth = state(), all_rows(*AUTH_MODELS)

    def fault_winner():
        with transaction.atomic():
            MemberClaimCode.objects.select_for_update(of=("self",)).get(pk=session.claim.pk)
            winner.stop()
            # Explicit corruption/fault injection, not canonical claim history.
            MemberClaimCode.objects.filter(pk=session.claim.pk).update(membership=foreign)

    def claim_lock(statement):
        return 'FROM "accounts_memberclaimcode"' in statement.sql and "FOR UPDATE" in statement.sql

    with workers() as start:
        try:
            holder = start(fault_winner)
            winner.wait(holder)
            request = start(case.call)
            blocked_by(request, holder.pid, claim_lock)
            proof.observe("cleanup_before_locked_provenance_repeat")
            assert not [row for row in source_locks() if row["objid"] == closure_lab.other.pk]
            winner.release.set()
            holder.finish()
            invalid_response(request.finish())
            assert not [s for s in request.statements if dml(s.sql)]
        finally:
            winner.release.set()
    proof.released()
    expected = dict(auth)
    expected["accounts.memberclaimcode"] = [
        {**row, "membership_id": foreign.pk} if row["id"] == session.claim.pk else row
        for row in auth["accounts.memberclaimcode"]]
    assert all_rows(*AUTH_MODELS) == expected
    assert state() == before
