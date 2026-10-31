"""Authorization/origin denial must not disclose a foreign migration gate."""
import pytest
from django.db import connection

from tests.qr_source_safety.http_helpers import (
    API_WRITERS, closure_lab, prepared,
)
from tests.qr_source_safety.state_helpers import state
from tests.qr_target_safety_helpers import jwt_client, membership, staff
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", API_WRITERS)
@pytest.mark.parametrize("denial", ["wrong-origin", "foreign-member", "unscoped", "no-actions"])
def test_scope_and_auth_precede_foreign_gate_state(closure_lab, kind, denial):
    lab = closure_lab
    # Cross-Maker actions need an actor who would otherwise have both authorities.
    client = lab.root_api if "cross" in kind else lab.api
    if denial == "wrong-origin":
        membership(lab.actor, lab.other)
        client.defaults["HTTP_ORIGIN"] = f"https://{lab.other.frontend_domain}"
    else:
        actor = staff(lab.other) if denial == "foreign-member" else staff(lab.home, "member")
        if denial == "unscoped":
            actor.makerspace_memberships.all().delete()
        client = jwt_client(actor)
    case = prepared(lab, kind, api=client)
    # generation_request takes lab.api; use the actual selected denial client too.
    if kind == "api-generate":
        lab.api = client
        from tests.qr_source_safety.http_helpers import generation_request
        case.call = generation_request(lab, case.obj)
    for tenant in (lab.home, lab.other):
        close_gate(tenant, lab.root)
    before, sql = state(), []

    def capture(execute, query, params, many, context):
        sql.append(query)
        return execute(query, params, many, context)

    with connection.execute_wrapper(capture):
        response = case.call()
    expected = 403 if denial == "wrong-origin" else 404
    assert response.status_code == expected, getattr(response, "data", response.content)
    assert not any('FROM "tenant_migration_sourcemigrationgate"' in query for query in sql)
    assert state() == before
