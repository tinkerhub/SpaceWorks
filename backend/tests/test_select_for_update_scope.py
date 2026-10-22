"""M10: workflow locks take FOR UPDATE on their own row only, never on joined rows.

Without `of=("self",)` Postgres also locks every select_related row (makerspace,
requester, machine type) FOR UPDATE, which blocks every concurrent insert that references
them through a foreign key for the whole workflow transaction.
"""
import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.workflow_utils import locked_request
from apps.machines.service_workflow_helpers import _locked_request, _locked_submission_target
from tests.return_helpers import make_space, make_user
from tests.test_machine_service_workflow import machine, request

pytestmark = pytest.mark.django_db


def _lock_clauses(run):
    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        run()
    return [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]


def test_locked_request_locks_only_the_request_row():
    space = make_space("lock-scope-request")
    requester = make_user("lock-scope-requester")
    hardware_request = HardwareRequest.objects.create(
        makerspace=space, requester=requester, requester_username=requester.username
    )

    clauses = _lock_clauses(lambda: locked_request(hardware_request))

    assert len(clauses) == 1
    assert clauses[0].endswith('FOR UPDATE OF "hardware_requests_hardwarerequest"')


def test_machine_service_locks_only_their_own_rows():
    space = make_space("lock-scope-machine")
    target = machine(space)
    service_request = request(space, target=target)

    clauses = _lock_clauses(lambda: (_locked_submission_target(target), _locked_request(service_request)))

    assert len(clauses) == 2
    assert clauses[0].endswith('FOR UPDATE OF "machines_machine"')
    assert clauses[1].endswith('FOR UPDATE OF "machines_machineservicerequest"')
