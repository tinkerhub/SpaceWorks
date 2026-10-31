"""Real N waits create deterministic winners before fresh locked policy checks."""
import json

import pytest
from django.db import connection

from apps.accounts.models import User
from apps.accounts.models_social import SocialIdentity
from tests.box_parent_safety.pg_helpers import workers
from tests.qr_http_ownership_safety.p_observations import identity, source_locks

from .callers import assert_retry, oidc_call, prepare
from .conftest import membership
from .observations import exclusive_n, row_lock, source_statement, wait_raw_n
from .state import domain, tenant_and_transition_audits

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["native", "oidc"])
def test_sorted_all_status_admission_holds_lower_n_while_waiting_higher_before_rows(
    claim_lab, kind, monkeypatch, record_property,
):
    call = prepare(claim_lab, kind, monkeypatch)
    lower, higher = sorted(space.pk for space in claim_lab.spaces)
    with workers() as start:
        blocker = start(lambda: exclusive_n(higher), pause=source_statement)
        blocker.paused()
        baseline = {identity(row) for row in source_locks()}
        request = start(call)
        wait_raw_n(higher, blocker.pid, baseline, record_property)
        rows = source_locks()
        granted_lower = [row for row in rows if row["objid"] == lower
                         and row["granted"] and row["mode"] == "ShareLock"
                         and identity(row) not in baseline]
        assert len(granted_lower) == 1, rows
        assert not [s for s in request.statements if row_lock(s.sql)]
        record_property("sorted_N_admission", json.dumps(rows, default=str))
        blocker.finish()
        response = request.finish()
    assert response.status_code == (302 if kind == "native" else 200), response.content


@pytest.mark.parametrize("kind", ["native", "oidc"])
def test_new_lower_membership_committed_during_n_wait_requires_fresh_retry(
    claim_lab, kind, monkeypatch, record_property,
):
    call = prepare(claim_lab, kind, monkeypatch)
    key = claim_lab.spaces[0].pk
    assert claim_lab.lower_space.pk < key
    with workers() as start:
        blocker = start(lambda: exclusive_n(key), pause=source_statement)
        blocker.paused()
        baseline = {identity(row) for row in source_locks()}
        request = start(call)
        wait_raw_n(key, blocker.pid, baseline, record_property)
        # A committed FK insertion wins while admission is blocked, before User
        # FOR UPDATE can serialize it. This is real membership history, not a mock.
        membership(claim_lab.lower_space, claim_lab.user)
        before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc")
        lower_blocker = start(lambda: exclusive_n(claim_lab.lower_space.pk), pause=source_statement)
        lower_blocker.paused()
        blocker.finish()
        response = request.finish()
        assert_retry(response, kind)
        if kind == "oidc":
            assert response.json()["code"] == "identity_scope_changed"
        record_property("scope_growth_full_SQL", json.dumps([vars(s) for s in request.statements], default=str))
        assert not [s for s in request.statements if "pg_advisory_xact_lock_shared" in s.sql
                    and s.params == (734310, claim_lab.lower_space.pk)]
        # Returning while this real lower exclusive is STILL held proves the
        # growth refusal did not try to acquire a new lower raw/shared N.
        lower_blocker.finish()
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc") == audits


@pytest.mark.parametrize("change", ["deactivated", "demoted", "suspended", "must-change"])
def test_native_rechecks_real_acting_admin_after_n_wait_before_target_mutation(
    claim_lab, change, monkeypatch, record_property,
):
    call = prepare(claim_lab, "native", monkeypatch)
    key = claim_lab.spaces[0].pk
    with workers() as start:
        blocker = start(lambda: exclusive_n(key), pause=source_statement)
        blocker.paused()
        baseline = {identity(row) for row in source_locks()}
        request = start(call)
        wait_raw_n(key, blocker.pid, baseline, record_property)
        updates = {"deactivated": {"is_active": False}, "demoted": {"is_superuser": False},
                   "suspended": {"access_status": User.AccessStatus.SUSPENDED},
                   "must-change": {"must_change_password": True}}[change]
        User.objects.filter(pk=claim_lab.actor.pk).update(**updates)
        before, audits = domain(), tenant_and_transition_audits()
        blocker.finish()
        response = request.finish()
    assert response.status_code == 403, response.content
    assert domain() == before
    assert tenant_and_transition_audits() == audits


@pytest.mark.parametrize("winner", ["target-email", "provider-subject", "membership-revoked"])
def test_oidc_locked_repeat_refuses_actual_identity_winner_after_n_wait(
    claim_lab, winner, monkeypatch, record_property,
):
    prepared = oidc_call(claim_lab, monkeypatch)
    key = claim_lab.spaces[0].pk
    with workers() as start:
        blocker = start(lambda: exclusive_n(key), pause=source_statement)
        blocker.paused()
        baseline = {identity(row) for row in source_locks()}
        request = start(prepared.call)
        wait_raw_n(key, blocker.pid, baseline, record_property)
        if winner == "target-email":
            User.objects.filter(pk=claim_lab.user.pk).update(email="changed@example.test")
        elif winner == "provider-subject":
            SocialIdentity.objects.create(user=claim_lab.actor,
                provider=prepared.provider.provider_key, provider_sub=prepared.claims["sub"])
        else:
            type(claim_lab.memberships[0]).objects.filter(pk=claim_lab.memberships[0].pk).update(status="revoked")
        before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=True)
        blocker.finish()
        response = request.finish()
    assert_retry(response, "oidc")
    assert response.json()["code"] == "identity_conflict"
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=True) == audits


@pytest.mark.parametrize("kind", ["native", "oidc"])
def test_cancel_actual_owned_n_wait_yields_retry_without_reconnect_or_domain_writes(
    claim_lab, kind, monkeypatch, record_property,
):
    call = prepare(claim_lab, kind, monkeypatch)
    before, audits = domain(), tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc")
    key = claim_lab.spaces[0].pk
    with workers() as start:
        blocker = start(lambda: exclusive_n(key), pause=source_statement)
        blocker.paused()
        baseline = {identity(row) for row in source_locks()}
        request = start(call)
        owned_pid = wait_raw_n(key, blocker.pid, baseline, record_property)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_cancel_backend(%s)", [owned_pid])
            assert cursor.fetchone()[0] is True
        response = request.finish()
        assert_retry(response, kind, oidc_status=503)
        # The exclusive owner remains held until AFTER the request returns. A
        # reconnect/reacquire would still be queued and fail the bounded watchdog.
        assert not [row for row in source_locks() if row["objid"] == key
                    and row["mode"] == "ShareLock" and identity(row) not in baseline]
        blocker.finish()
    assert domain() == before
    assert tenant_and_transition_audits(allow_oidc_metadata=kind == "oidc") == audits
