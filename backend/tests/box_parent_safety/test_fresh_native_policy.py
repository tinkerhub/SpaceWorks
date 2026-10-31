"""Native policy is re-read after the Maker wait, without expanding module policy."""
import pytest
from django.contrib.admin.models import DELETION, LogEntry
from django.db import connection, transaction

from apps.accounts.models import User
from apps.boxes.models import Box, QrCode
from apps.makerspaces.models import Makerspace
from tests.box_parent_safety.http_helpers import (
    audit_delta, audit_ids, box, deletion, lab, writer,
)
from tests.box_parent_safety.pg_helpers import assert_maker_mode, blocked_by, workers

pytestmark = pytest.mark.django_db(transaction=True)
OPERATIONS = ("add", "edit", "single", "bulk")


def native_operation(lab, operation):
    parent = box(lab.home, "Policy parent")
    child = box(lab.home, "Policy target")
    if operation in {"single", "bulk"}:
        request = deletion(lab.client, [child], operation)
    else:
        request = writer(lab, "native-create" if operation == "add" else "native-edit",
                         parent, None if operation == "add" else child)
    return request, parent, child


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("denial", ["inactive", "suspended", "non-superuser", "password-change", "hidden"])
def test_native_admission_refuses_fresh_policy_after_real_maker_wait(lab, operation, denial):
    request, parent, child = native_operation(lab, operation)
    before = {"boxes": list(Box.objects.order_by("pk").values()),
              "qr": list(QrCode.objects.order_by("pk").values())}
    audits, logs = audit_ids(), set(LogEntry.objects.values_list("pk", flat=True))
    with workers() as start:
        with transaction.atomic():
            Makerspace.objects.select_for_update().get(pk=lab.home.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                owner = cursor.fetchone()[0]
            pending = start(request)
            assert_maker_mode(blocked_by(pending, owner), "FOR NO KEY UPDATE")
            # The request already passed middleware/auth/form lookups. Commit a real
            # policy mutation while it is waiting; no cached request.user is patched.
            if denial == "hidden":
                Makerspace.objects.filter(pk=lab.home.pk).update(superadmin_access_enabled=False)
            else:
                field, value = {"inactive": ("is_active", False),
                                "suspended": ("access_status", "suspended"),
                                "non-superuser": ("is_superuser", False),
                                "password-change": ("must_change_password", True)}[denial]
                User.objects.filter(pk=lab.actor.pk).update(**{field: value})
        response = pending.finish()
    assert response.status_code == (200 if operation in {"add", "edit"} else 403)
    if operation in {"add", "edit"}:
        assert "cannot write a box" in str(response.context["adminform"].form.non_field_errors())
    assert list(Box.objects.order_by("pk").values()) == before["boxes"]
    assert list(QrCode.objects.order_by("pk").values()) == before["qr"]
    assert audit_delta(audits) == []
    attempts = list(LogEntry.objects.exclude(pk__in=logs))
    # Single delete logs inside Django's outer transaction; the 403 rolls it back.
    # Bulk delete_selected logs its attempt before the lifecycle wrapper is called.
    assert len(attempts) == int(operation == "bulk")
    if attempts:
        assert attempts[0].object_id == str(child.pk)
        assert attempts[0].action_flag == DELETION


@pytest.mark.parametrize("operation", OPERATIONS)
def test_native_creation_requires_module_but_edit_delete_gain_no_module_requirement(lab, operation):
    request, parent, child = native_operation(lab, operation)
    before = audit_ids()
    with workers() as start:
        with transaction.atomic():
            Makerspace.objects.select_for_update().get(pk=lab.home.pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                owner = cursor.fetchone()[0]
            pending = start(request)
            assert_maker_mode(blocked_by(pending, owner), "FOR NO KEY UPDATE")
            # Deliberate legacy/off configuration; do not call module-install, which
            # correctly refuses disabling a core module in ordinary operator flows.
            Makerspace.objects.filter(pk=lab.home.pk).update(enabled_modules=[])
        response = pending.finish()
    rows = audit_delta(before)
    if operation == "add":
        assert response.status_code == 200
        assert "qr_management" in str(response.context["adminform"].form.errors)
        assert not Box.objects.filter(label="Race child").exists()
        assert rows == []
    else:
        assert response.status_code == 302
        assert len(rows) == 1
        assert rows[0].action == ("control.object_updated" if operation == "edit" else "control.object_deleted")
        if operation == "edit":
            child.refresh_from_db()
            assert child.parent_id == parent.pk and child.label == "Race child"
        else:
            assert not Box.objects.filter(pk=child.pk).exists()
