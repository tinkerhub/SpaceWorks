"""Queue allocation policy is a read-only staff response contract."""

import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.admin_api.serializers_machine_service import (
    MachineServiceRequestSerializer, ServiceStartSerializer,
)
from apps.machines.models import ServiceQueue
from apps.machines.service_workflow import submit
from tests.return_helpers import authenticated_client, make_member, make_space, make_user
from tests.test_machine_service_api import action_url, list_url, make_machine, request_row


pytestmark = pytest.mark.django_db


def queued_request(space, machine_type, index, policy):
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=machine_type, name=f"Allocation queue {index}",
        allocation_policy=policy,
    )
    requester = make_user(f"allocation-requester-{index}")
    return submit(
        queue, requester, requester_name="Maker", contact_email=requester.email,
        contact_phone="123", title=f"Queued job {index}",
    )


@pytest.mark.parametrize("policy", ["staff_select", "first_idle"])
def test_staff_list_detail_and_accept_return_actual_queue_policy(policy):
    space = make_space("allocation-staff-response")
    actor = make_member("allocation-staff-manager", space)
    machine = make_machine(space)
    row = queued_request(space, machine.machine_type, 0, policy)
    client = authenticated_client(actor)

    listed = client.get(list_url(space))
    detail = client.get(reverse("admin-machine-service-request-detail", args=[row.pk]))
    accepted = client.post(action_url(row, "accept"), {"estimated_minutes": 10}, format="json")

    assert listed.status_code == detail.status_code == accepted.status_code == 200
    assert [(item["id"], item["allocation_policy"]) for item in listed.data] == [(row.pk, policy)]
    for response in (detail, accepted):
        assert response.data["id"] == row.pk
        assert response.data["allocation_policy"] == policy
        assert response.data["queue_id"] == row.queue_id
    assert accepted.data["status"] == "accepted"


def test_legacy_bucket_responses_fall_back_to_staff_select():
    space = make_space("allocation-legacy")
    actor = make_member("allocation-legacy-manager", space)
    row = request_row(space)
    assert row.bucket_id is not None and row.queue_id is None
    client = authenticated_client(actor)

    listed = client.get(list_url(space))
    detail = client.get(reverse("admin-machine-service-request-detail", args=[row.pk]))
    accepted = client.post(action_url(row, "accept"), {}, format="json")

    assert listed.status_code == detail.status_code == accepted.status_code == 200
    assert [(item["id"], item["allocation_policy"]) for item in listed.data] == [(row.pk, "staff_select")]
    for response in (detail, accepted):
        assert response.data["queue_id"] is None
        assert response.data["allocation_policy"] == "staff_select"


def test_policy_is_read_only_and_dropped_from_validated_input():
    output = MachineServiceRequestSerializer(data={"allocation_policy": "first_idle"})
    assert output.fields["allocation_policy"].read_only is True
    assert output.is_valid(), output.errors
    assert output.validated_data == {}

    start = ServiceStartSerializer(data={"machine_id": None, "allocation_policy": "first_idle"})
    assert start.is_valid(), start.errors
    assert start.validated_data == {"machine_id": None}


def test_staff_list_eager_loads_distinct_queue_policies_without_row_query_growth():
    space = make_space("allocation-eager")
    actor = make_member("allocation-eager-manager", space)
    machine = make_machine(space)
    client = authenticated_client(actor)
    expected = {}

    def add_rows(start, stop):
        for index in range(start, stop):
            policy = "first_idle" if index % 2 else "staff_select"
            row = queued_request(space, machine.machine_type, index, policy)
            expected[row.pk] = policy

    def measure():
        # Warm authorization and mapped-PII caches at each size, outside measurement.
        warm = client.get(list_url(space))
        assert warm.status_code == 200, warm.data
        with CaptureQueriesContext(connection) as captured:
            response = client.get(list_url(space))
            assert response.status_code == 200, response.data
            assert {item["id"]: item["allocation_policy"] for item in response.data} == expected
        queue_reads = sum(
            bool(re.search(r'\bFROM\s+"' + ServiceQueue._meta.db_table + r'"', query["sql"], re.I))
            for query in captured
        )
        return len(captured), queue_reads

    add_rows(0, 2)
    few_total, few_queue_reads = measure()
    add_rows(2, 12)
    many_total, many_queue_reads = measure()

    # Allow constant RBAC/cache overhead, but ten extra queues must not add ten reads.
    assert many_total <= few_total + 2
    assert many_queue_reads <= few_queue_reads + 1
    assert many_queue_reads <= 1
