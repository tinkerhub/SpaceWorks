"""Two actual PostgreSQL issue/transition interleavings; no swallowed deadlocks."""
import json

import pytest

from apps.accounts.models import MemberClaimCode, User
from apps.accounts.services_claim import ClaimCodeIneligible, issue_claim_code
from apps.accounts.services_tokens import blacklist_device_family
from tests.box_parent_safety.pg_helpers import blocked_by, workers

from .callers import prepare
from .conftest import PASSWORD
from .observations import NProof

pytestmark = pytest.mark.django_db(transaction=True)


def target_user_lock(statement, user_id):
    return ('FROM "accounts_user"' in statement.sql and "FOR UPDATE" in statement.sql
            and user_id in statement.params)


def target_membership_lock(statement, membership_id):
    return ('FROM "makerspaces_makerspacemembership"' in statement.sql
            and "FOR UPDATE" in statement.sql and membership_id in statement.params)


def issuer(lab):
    # Separate actor avoids an unrelated audit FK dependency on the native actor.
    actor = User.objects.create_superuser(username="claim-order-issuer",
        email="issuer@example.test", password=PASSWORD)
    # Canonically revoke the native grant before issuing another physical code;
    # the target must again satisfy the real credential-free walk-in policy.
    blacklist_device_family(lab.family, revoke_grant=True)
    return lambda: issue_claim_code(actor=actor, makerspace_id=lab.spaces[0].pk,
                                    membership_id=lab.memberships[0].pk)


def test_actual_issue_membership_winner_precedes_oidc_user_lock_without_deadlock(
    claim_lab, monkeypatch, record_property,
):
    issue = issuer(claim_lab)
    call = prepare(claim_lab, "oidc", monkeypatch)
    predicate = lambda s: target_membership_lock(s, claim_lab.memberships[0].pk)
    proof = NProof([space.pk for space in claim_lab.spaces], record_property)
    with workers() as start:
        issuing = start(issue, pause=predicate)
        issuing.paused()
        transition = start(call)
        blocked_by(transition, issuing.pid, predicate)
        proof.observe("OIDC_waiting_target_membership_before_User")
        assert not [s for s in transition.statements if s.completed
                    and target_user_lock(s, claim_lab.user.pk)]
        physical = issuing.finish()
        response = transition.finish()
    assert response.status_code == 200, response.content
    claim_lab.user.refresh_from_db()
    physical.claim.refresh_from_db()
    assert claim_lab.user.is_walk_in is False
    assert physical.claim.consumed_at is None and physical.claim.revoked_at is not None
    assert not MemberClaimCode.objects.filter(membership__user=claim_lab.user, revoked_at__isnull=True).exists()
    proof.released()
    record_property("issue_OIDC_full_SQL", json.dumps({
        "issue": [vars(s) for s in issuing.statements],
        "oidc": [vars(s) for s in transition.statements]}, default=str))


def test_native_user_winner_claim_hook_locks_only_self_while_issuer_holds_membership(
    claim_lab, monkeypatch, record_property,
):
    issue = issuer(claim_lab)
    call = prepare(claim_lab, "native", monkeypatch)

    def issue_loser():
        try:
            issue()
        except ClaimCodeIneligible:
            return "credential-free policy refused after native winner"
        pytest.fail("The issuer must observe the committed account transition")

    user_predicate = lambda s: target_user_lock(s, claim_lab.user.pk)
    with workers() as start:
        transition = start(call, pause=user_predicate)
        transition.paused()
        issuing = start(issue_loser)
        blocked_by(issuing, transition.pid, user_predicate)
        # The issuer already owns target Membership and now waits for native User.
        assert any(s.completed and target_membership_lock(s, claim_lab.memberships[0].pk)
                   for s in issuing.statements)
        response = transition.finish()
        assert issuing.finish() == "credential-free policy refused after native winner"
    assert response.status_code == 302, response.content
    claim_lab.user.refresh_from_db()
    assert claim_lab.user.is_walk_in is False
    hook_sql = [s.sql for s in transition.statements if 'FROM "accounts_memberclaimcode"' in s.sql
                and 'JOIN "makerspaces_makerspacemembership"' in s.sql and "FOR UPDATE" in s.sql]
    assert hook_sql and all('FOR UPDATE OF "accounts_memberclaimcode"' in sql for sql in hook_sql)
    record_property("issue_native_full_SQL", json.dumps({
        "issue": [vars(s) for s in issuing.statements],
        "native": [vars(s) for s in transition.statements]}, default=str))
