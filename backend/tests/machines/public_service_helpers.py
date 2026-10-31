"""Real published machines and requesters for public type-intake regression tests."""
from copy import deepcopy
from io import BytesIO
from unittest.mock import Mock

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.machines import service_storage
from apps.machines.models import Machine, MachineType
from apps.machines.printer_capabilities import PRINTER_CONFIG
from tests.return_helpers import authenticated_client, make_space, make_user


@pytest.fixture
def service_lab():
    space = make_space("typed-service")
    space.enabled_modules = ["machines", "machine_service", "printing"]
    space.public_inventory_enabled = True
    space.save(update_fields=["enabled_modules", "public_inventory_enabled"])
    generic = MachineType.objects.create(makerspace=space, slug="router", name="Router")
    printer, _ = MachineType.objects.get_or_create(
        makerspace=None, slug="3d_printer", defaults={
            "name": "3D Printer", "is_builtin": True,
            "managing_action": "manage_printing", "capability_config": deepcopy(PRINTER_CONFIG),
        },
    )
    for kind in (generic, printer):
        Machine.objects.create(makerspace=space, machine_type=kind, name=kind.name,
                               is_public=True, type_payload={"model": "P1S"} if kind == printer else {})
    actor = make_user("typed-maker", display_name="Ada Maker", phone="1234567890",
                      access_status=User.AccessStatus.ACTIVE)
    return space, actor, authenticated_client(actor), generic, printer


def endpoint(space, action="submit"):
    names = {"submit": "public-machine-service-request-submit", "types": "public-machine-service-types",
             "upload": "public-machine-service-upload"}
    return reverse(names[action], args=[space.slug])


def post_request(lab, kind=None, **changes):
    space, _, client, generic, _ = lab
    return client.post(endpoint(space), {"machine_type_id": (kind or generic).pk,
                       "title": "Project enclosure", **changes}, format="json")


@pytest.fixture
def object_io(monkeypatch, settings):
    """Only the object-store network boundary is mocked; validators and DB stay real."""
    settings.STORAGE_PRESIGN_METHOD = "post"
    objects = {}
    storage = Mock()
    from tests.atomic_publication.store import error

    def get(**kwargs):
        if kwargs["Key"] not in objects:
            raise error()
        data, mime = objects[kwargs["Key"]]
        return {"Body": BytesIO(data), "ContentType": mime}

    def put(**kwargs):
        assert kwargs["IfNoneMatch"] == "*"
        if kwargs["Key"] in objects:
            raise error("PreconditionFailed", 412)
        objects[kwargs["Key"]] = (kwargs["Body"].read(), kwargs["ContentType"])
        return {}

    def remove(**kwargs):
        for item in kwargs["Delete"]["Objects"]:
            objects.pop(item["Key"], None)
        return {}

    storage.get_object.side_effect = get
    storage.put_object.side_effect = put
    storage.get_bucket_versioning.return_value = {"Status": "Enabled"}
    storage.list_object_versions.side_effect = lambda **kw: {
        "IsTruncated": False, "Versions": [
            {"Key": key, "VersionId": "snapshot-v1"} for key in objects if key.startswith(kw["Prefix"])
        ],
    }
    storage.delete_objects.side_effect = remove
    storage.delete_object.side_effect = AssertionError("No bare delete fallback")
    storage.copy_object.side_effect = AssertionError("No unconditional COPY fallback")
    storage.head_object.side_effect = lambda **kw: {"ContentLength": len(objects[kw["Key"]][0])}
    public = Mock()
    public.generate_presigned_post.return_value = {"url": "https://objects.example/upload", "fields": {}}
    monkeypatch.setattr(service_storage, "_client", lambda: storage)
    monkeypatch.setattr(service_storage, "_public_client", lambda: public)
    return objects, storage, public
