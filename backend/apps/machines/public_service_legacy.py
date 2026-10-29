"""Compatibility for callers that still select a specific machine."""
from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.encryption.write_fence import assert_mapped_write_allowed
from apps.machines import service_workflow
from apps.machines.models import Machine
from apps.machines.printer_capabilities import is_printer_type
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


@transaction.atomic
def submit_legacy_machine(makerspace, machine_id, data, actor):
    assert_mapped_write_allowed(makerspace.pk)
    space = Makerspace.objects.select_for_update(no_key=True).get(pk=makerspace.pk)
    require_module(space, "machine_service")
    machine = get_object_or_404(
        Machine.objects.select_for_update(of=("self",)).select_related("machine_type").filter(makerspace=space, is_active=True),
        pk=machine_id,
    )
    if is_printer_type(machine.machine_type):
        require_module(space, "printing")
    return service_workflow.submit(
        machine, actor, member=actor, actor=actor,
        requester_name=actor.display_name, contact_email=actor.email,
        contact_phone=actor.phone, title=data["title"],
        description=data.get("description", ""), source_link=data.get("source_link", ""),
        capability_payload=data.get("capability_payload"),
    )
