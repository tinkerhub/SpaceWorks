"""Small domain setup scoped to these tests; all storage/lifecycle code stays real."""
from django.db import connection

from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.machines.models import Machine, MachineType, ServiceRequestFile
from apps.machines.service_workflow import submit
from apps.makerspaces import limits
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import make_member, make_space
from tests.atomic_publication.store import Store


def setup_machine(slug, monkeypatch):
    DeploymentDatabaseIdentity.objects.get_or_create(pk=1)
    space = make_space(slug)
    space.resource_limit_overrides = {"storage": 100000}
    space.save(update_fields=["resource_limit_overrides"])
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    actor = make_member(f"{slug}-manager", space)
    kind = MachineType.objects.create(makerspace=space, slug="laser", name="Laser")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser")
    return space, actor, machine


def service_file(slug, monkeypatch):
    space, actor, machine = setup_machine(slug, monkeypatch)
    row = submit(machine, actor, title="Repair", requester_name="Member",
                 contact_email=actor.email, contact_phone="123")
    file = ServiceRequestFile.objects.create(
        machine=machine, kind="attachment", object_key=f"machine/{space.pk}/{machine.pk}/service/upload",
        content_type="application/pdf", original_filename="repair.pdf", owner_user_id=actor.pk,
        file_policy_name="documents", file_policy_version=1,
    )
    return space, actor, machine, row, file


def outside_atomic():
    assert connection.in_atomic_block is False, "S3 called while application transaction held"


def bind_store(monkeypatch, *modules):
    store = Store(boundary=outside_atomic)
    for module in modules:
        monkeypatch.setattr(module, "_client", lambda: store)
    return store
