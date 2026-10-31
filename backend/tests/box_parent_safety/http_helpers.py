"""Real native/admin and DRF requests, prepared before concurrency begins."""
from types import SimpleNamespace

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.boxes.models import Box
from tests.qr_target_safety_helpers import (
    configure, jwt_client, native_client, native_form, space, staff, superadmin,
)

WRITERS = ("qr-create", "container-create", "native-create", "patch", "move", "native-edit")
CREATORS = WRITERS[:3]
EVENTS = {"qr-create": "qr.box_created", "container-create": "container.created",
          "native-create": "qr.box_created", "patch": "container.updated",
          "move": "container.moved", "native-edit": "control.object_updated"}


@pytest.fixture
def lab(settings):
    configure(settings)
    home, other = space(), space()
    actor = superadmin()
    api_actor = staff(home)
    return SimpleNamespace(home=home, other=other, actor=actor,
                           api_actor=api_actor, client=native_client(actor),
                           api=jwt_client(api_actor))


def box(tenant, label, parent=None):
    return Box.objects.create(makerspace=tenant, label=label, parent=parent)


def deletion(client, objects, mode, *, ordering=None):
    if mode == "single":
        assert len(objects) == 1
        url, data = reverse("admin:boxes_box_delete", args=[objects[0].pk]), {"post": "yes"}
    else:
        url = reverse("admin:boxes_box_changelist")
        if ordering:
            url += f"?o={ordering}"
        data = {"action": "delete_selected", "select_across": "0", "post": "yes",
                ACTION_CHECKBOX_NAME: [str(obj.pk) for obj in objects]}
    return lambda: client.post(url, data)


def writer(lab, kind, parent, child=None, *, explicit=True, label="Race child"):
    """Native forms come from real GETs; API payloads use real serializers."""
    if kind.startswith("native"):
        changes = {"label": label}
        if child is None:
            changes.update(makerspace=lab.home.pk, is_active="on")
        if explicit:
            changes["parent"] = parent.pk
        url, data = native_form(lab.client, "boxes_box", child, **changes)
        if not explicit:
            data.pop("parent", None)
        return lambda: lab.client.post(url, data)
    data = {"label": label}
    if kind == "qr-create":
        url, method = reverse("qr-boxes"), lab.api.post
        data["makerspace_id"] = lab.home.pk
        if explicit:
            data["parent_id"] = parent.pk
    elif kind == "container-create":
        url, method = reverse("containers", args=[lab.home.pk]), lab.api.post
        if explicit:
            data["parent"] = parent.pk
    else:
        url = reverse("container-detail" if kind == "patch" else "container-move", args=[child.pk])
        method = lab.api.patch if kind == "patch" else lab.api.post
        if explicit:
            data["parent" if kind == "patch" else "parent_id"] = parent.pk
    return lambda: method(url, data, format="json")


def success(kind):
    return 302 if kind.startswith("native") else 201 if kind in CREATORS else 200


def vanished_parent(kind, response):
    expected = {"qr-create": 404, "container-create": 400, "native-create": 200,
                "patch": 400, "move": 404, "native-edit": 200}[kind]
    assert response.status_code == expected, getattr(response, "data", None)
    if kind.startswith("native"):
        assert "parent" in response.context["adminform"].form.errors
    else:
        assert response.data
        if expected == 400:
            assert "parent" in response.data


def audit_ids():
    return set(AuditLog.objects.values_list("pk", flat=True))


def audit_delta(before):
    return list(AuditLog.objects.exclude(pk__in=before).order_by("pk"))


def assert_deleted(row, actor, obj):
    assert (row.action, row.actor_id, row.makerspace_id, row.target_type, row.target_id,
            row.meta) == ("control.object_deleted", actor.pk, obj.makerspace_id,
                          "boxes.box", str(obj.pk), {"model": "boxes.box"})
