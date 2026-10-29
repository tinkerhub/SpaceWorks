"""Typed proposals create/reuse real queues and preserve identity without assignment."""
import pytest

from apps.audit.models import AuditLog
from apps.machines.models import Machine, MachineServiceRequest, ServiceQueue
from tests.machines.public_service_helpers import endpoint, post_request, service_lab
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("printer", [False, True])
def test_first_typed_submission_creates_pending_unassigned_job_and_audit(service_lab, printer):
    space, actor, _, generic, printer_type = service_lab
    kind = printer_type if printer else generic
    assert not actor.makerspace_memberships.exists()
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    response = post_request(service_lab, kind, description="Cut from plywood", source_link="https://example.org/project")
    assert response.status_code == 201, response.data
    assert set(response.data) == {"public_token", "status"}
    row = MachineServiceRequest.objects.get(public_token=response.data["public_token"])
    assert row.status == response.data["status"] == "pending"
    assert row.queue.machine_type_id == kind.pk and row.queue.makerspace_id == space.pk
    assert row.bucket_id is None and row.assigned_machine_id is None
    assert row.requester_id == row.member_id == actor.pk
    assert (row.requester_name, row.contact_email, row.contact_phone) == (actor.display_name, actor.email, actor.phone)
    assert row.description == "Cut from plywood" and row.source_link == "https://example.org/project"
    if printer:
        assert row.capability_payload["no_filament_preference"] is True
        assert row.capability_payload["quantity"] == 1
        assert row.capability_payload["requested_material"] in kind.capability_config["accepted_materials"]
        assert row.capability_payload["requested_color"] in kind.capability_config["accepted_colours"]
    else:
        assert row.capability_payload == {}
    events = AuditLog.objects.filter(makerspace=space)
    for action, target in [("machine_service.public_queue_created", row.queue), ("machine_service.submitted", row)]:
        event = events.get(action=action)
        assert event.actor_id == actor.pk and event.target_id == str(target.pk)


@pytest.mark.parametrize("state", ["running", "reserved"])
def test_busy_published_machine_still_accepts_a_type_proposal(service_lab, state):
    space, _, _, generic, _ = service_lab
    Machine.objects.filter(makerspace=space, machine_type=generic).update(status=state)
    assert post_request(service_lab).status_code == 201
    assert MachineServiceRequest.objects.get(makerspace=space).assigned_machine_id is None


def test_existing_active_queue_used_without_changing_operator_configuration(service_lab):
    space, _, _, generic, _ = service_lab
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=generic, name="Configured", capacity=3,
                                        allocation_policy="first_idle", description="Keep this")
    assert post_request(service_lab).status_code == 201
    queue.refresh_from_db()
    assert MachineServiceRequest.objects.get(makerspace=space).queue_id == queue.pk
    assert (queue.name, queue.capacity, queue.allocation_policy, queue.description) == ("Configured", 3, "first_idle", "Keep this")
    assert not AuditLog.objects.filter(makerspace=space, action="machine_service.public_queue_created").exists()


@pytest.mark.parametrize("collision", [False, True])
def test_setup_conflict_does_not_reactivate_or_overwrite_a_queue(service_lab, collision):
    space, _, _, generic, printer = service_lab
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=printer if collision else generic,
        name=f"Public Requests - type {generic.pk}" if collision else "Paused", is_active=collision,
        description="Staff settings", capacity=2,
    )
    before = AuditLog.objects.count()
    response = post_request(service_lab)
    assert response.status_code == 409, response.data
    queue.refresh_from_db()
    assert queue.is_active == collision and queue.description == "Staff settings" and queue.capacity == 2
    assert ServiceQueue.objects.filter(makerspace=space).count() == 1
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize("payload", [
    {}, {"machine_type_id": None}, {"machine_type_id": 0},
    {"capability_payload": {}}, {"project_brief": "Printer only"}, {"preferred_settings": {}},
    {"material": "PLA"}, {"color": "Blue"}, {"quantity": 1},
    {"consumable_pool_id": None}, {"estimated_filament_grams": 1},
    {"source_link": "not a URL"}, {"title": ""}, {"file_ids": [999999]},
])
def test_invalid_generic_payload_has_no_partial_queue_request_or_audit(service_lab, payload):
    space, _, client, generic, _ = service_lab
    body = {"title": "Panel", "machine_type_id": generic.pk, **payload}
    if not payload:
        body.pop("machine_type_id")
    before = AuditLog.objects.count()
    response = client.post(endpoint(space), body, format="json")
    assert response.status_code == 400, response.data
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
    assert AuditLog.objects.count() == before


def test_exactly_one_id_and_foreign_type_cannot_select_a_tenant(service_lab):
    space, _, client, generic, _ = service_lab
    machine = Machine.objects.get(makerspace=space, machine_type=generic)
    assert post_request(service_lab, machine_id=machine.pk).status_code == 400
    other = make_space("typed-foreign")
    other.enabled_modules = space.enabled_modules
    other.save(update_fields=["enabled_modules"])
    from apps.machines.models import MachineType
    foreign = MachineType.objects.create(makerspace=other, slug="foreign", name="Foreign")
    Machine.objects.create(makerspace=other, machine_type=foreign, name="Foreign", is_public=True)
    assert post_request(service_lab, foreign).status_code == 404
    assert client.post(endpoint(other), {"machine_id": machine.pk, "title": "Cross tenant"}, format="json").status_code == 404
    assert not MachineServiceRequest.objects.exists() and not ServiceQueue.objects.exists()


@pytest.mark.parametrize("fields", [
    {"material": "Unobtainium"}, {"color": "Invisible"}, {"quantity": 0},
    {"estimated_filament_grams": -1}, {"preferred_settings": "use supports"},
    {"capability_payload": {"requested_material": "PLA"}}, {"consumable_pool_id": 999999},
])
def test_invalid_printer_fields_cannot_create_a_queue(service_lab, fields):
    space, _, _, _, printer = service_lab
    response = post_request(service_lab, printer, **fields)
    assert response.status_code == 400, response.data
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_printing_module_gate_covers_typed_and_legacy_machine_id(service_lab, legacy):
    space, _, client, _, printer = service_lab
    machine = Machine.objects.get(makerspace=space, machine_type=printer)
    space.enabled_modules.remove("printing")
    space.save(update_fields=["enabled_modules"])
    body = {"title": "Part", "machine_id" if legacy else "machine_type_id": machine.pk if legacy else printer.pk}
    response = client.post(endpoint(space), body, format="json")
    assert response.status_code == (400 if legacy else 404)
    assert not MachineServiceRequest.objects.exists() and not ServiceQueue.objects.exists()


def test_honeypot_returns_decoy_without_queue_request_or_audit(service_lab):
    before = AuditLog.objects.count()
    response = post_request(service_lab, website="https://bot.invalid", file_ids=[999999])
    assert response.status_code == 201 and response.data["status"] == "pending"
    assert not MachineServiceRequest.objects.exists() and not ServiceQueue.objects.exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize("gate", ["machines", "machine_service", "public_inventory_enabled"])
def test_typed_submit_requires_the_public_service_surface_before_queue_setup(service_lab, gate):
    space = service_lab[0]
    if gate == "public_inventory_enabled":
        space.public_inventory_enabled = False
    else:
        space.enabled_modules.remove(gate)
        if gate == "machine_service":
            space.enabled_modules.remove("printing")
    space.save()
    response = post_request(service_lab)
    assert response.status_code == (400 if gate == "machine_service" else 404), response.data
    assert not ServiceQueue.objects.filter(makerspace=space).exists()
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
