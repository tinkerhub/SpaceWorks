"""Actual HTTP delete/child writer races, in both PostgreSQL winning orders."""
import pytest
from django.contrib.admin.models import DELETION, LogEntry

from apps.boxes.models import Box, QrCode
from tests.qr_target_safety_helpers import native_client, snapshot
from tests.box_parent_safety.http_helpers import (
    CREATORS, EVENTS, WRITERS, assert_deleted, audit_delta, audit_ids, box,
    deletion, lab, success, vanished_parent, writer,
)
from tests.box_parent_safety.pg_helpers import (
    assert_maker_mode, blocked_by, maker_lock, workers,
)

pytestmark = pytest.mark.django_db(transaction=True)


def writer_clause(kind):
    return "FOR UPDATE" if kind in {"container-create", "patch", "move"} else "FOR NO KEY UPDATE"


@pytest.mark.parametrize("mode", ["single", "bulk"])
@pytest.mark.parametrize("kind", WRITERS)
@pytest.mark.parametrize("winner", ["delete", "writer"])
def test_parent_delete_serializes_actual_child_writers(lab, mode, kind, winner, record_property):
    parent = box(lab.home, "Race parent")
    child = None if kind in CREATORS else box(lab.home, "Existing child")
    child_before = None if child is None else Box.objects.values().get(pk=child.pk)
    write = writer(lab, kind, parent, child)
    delete = deletion(native_client(lab.actor), [parent], mode)
    before, attempts = audit_ids(), set(LogEntry.objects.values_list("pk", flat=True))
    operations = {"delete": delete, "writer": write}
    loser = "writer" if winner == "delete" else "delete"
    with workers() as start:
        first = start(operations[winner], pause=maker_lock)
        first.paused()
        first_lock = next(s for s in first.statements if maker_lock(s))
        assert_maker_mode(first_lock, "FOR NO KEY UPDATE" if winner == "delete" else writer_clause(kind))
        second = start(operations[loser])
        pending = blocked_by(second, first.pid)
        assert_maker_mode(pending, "FOR NO KEY UPDATE" if loser == "delete" else writer_clause(kind))
        record_property("maker_wait", repr({"winner_pid": first.pid, "waiter_pid": second.pid,
                                           "sql": pending.sql, "params": pending.params}))
        first_response, second_response = first.finish(), second.finish()
    responses = {winner: first_response, loser: second_response}
    assert responses["delete"].status_code == 302
    assert not Box.objects.filter(pk=parent.pk).exists()
    rows = audit_delta(before)
    deleted = [row for row in rows if row.action == "control.object_deleted"]
    assert len(deleted) == 1
    assert_deleted(deleted[0], lab.actor, parent)
    if winner == "delete":
        vanished_parent(kind, responses["writer"])
        assert len(rows) == 1
        if child is None:
            assert not Box.objects.filter(label="Race child").exists()
        else:
            assert Box.objects.values().get(pk=child.pk) == child_before
    else:
        assert responses["writer"].status_code == success(kind)
        child = Box.objects.get(makerspace=lab.home, label="Race child")
        assert child.parent_id is None  # actual Collector discovered even a newly committed child
        assert len(rows) == 2
        written = [row for row in rows if row.action == EVENTS[kind]]
        assert len(written) == 1
        assert (written[0].target_type, written[0].target_id, written[0].makerspace_id) == (
            "boxes.box", str(child.pk), lab.home.pk,
        )
        assert written[0].actor_id == (lab.actor.pk if kind.startswith("native") else lab.api_actor.pk)
        expected_meta = ({"fields": ["label", "parent"]} if kind == "patch" else
                         {"model": "boxes.box", "changed_fields": ["label", "parent"], "detail": {}}
                         if kind == "native-edit" else {})
        assert written[0].meta == expected_meta
        deleter = first if winner == "delete" else second
        updates = [i for i, s in enumerate(deleter.statements)
                   if s.sql.startswith('UPDATE "boxes_box"') and '"parent_id" = NULL' in s.sql]
        deletes = [i for i, s in enumerate(deleter.statements) if s.sql.startswith('DELETE FROM "boxes_box"')]
        assert updates and deletes and max(updates) < min(deletes)
        if kind in CREATORS:
            qr = QrCode.objects.get(makerspace=lab.home, target_type="box", target_id=child.pk)
            assert qr.payload == child.code and qr.status == "active"
    # No phantom QR may be inserted for a refused new child.
    assert not QrCode.objects.filter(target_type="box").exclude(
        target_id__in=Box.objects.values("pk"),
    ).exists()
    logs = list(LogEntry.objects.exclude(pk__in=attempts))
    deletion_logs = [row for row in logs if row.action_flag == DELETION]
    assert len(deletion_logs) == 1
    assert deletion_logs[0].object_id == str(parent.pk)
    assert deletion_logs[0].user_id == lab.actor.pk
    assert len(logs) == 1 + int(winner == "writer" and kind.startswith("native"))


@pytest.mark.parametrize("mode", ["single", "bulk"])
@pytest.mark.parametrize("kind", ["patch", "move", "native-edit"])
def test_omitted_parent_uses_committed_collector_set_null(lab, mode, kind):
    parent = box(lab.home, "Omitted parent")
    child = box(lab.home, "Original child", parent)
    write = writer(lab, kind, parent, child, explicit=False, label="Sparse rename")
    before = audit_ids()
    with workers() as start:
        delete = start(deletion(native_client(lab.actor), [parent], mode), pause=maker_lock)
        delete.paused()
        update = start(write)
        assert_maker_mode(blocked_by(update, delete.pid), writer_clause(kind))
        assert delete.finish().status_code == 302
        assert update.finish().status_code == success(kind)
    child.refresh_from_db()
    assert child.parent_id is None and child.label == "Sparse rename"
    rows = audit_delta(before)
    assert len(rows) == 2
    assert {row.action for row in rows} == {"control.object_deleted", EVENTS[kind]}


@pytest.mark.parametrize("mode", ["single", "bulk"])
@pytest.mark.parametrize("kind", ["patch", "move", "native-edit"])
def test_target_disappearance_never_resurrects_or_emits_update_audit(lab, mode, kind):
    target = box(lab.home, "Vanishing target")
    parent = box(lab.home, "Surviving parent")
    write = writer(lab, kind, parent, target)
    parent_before = Box.objects.values().get(pk=parent.pk)
    before = audit_ids()
    with workers() as start:
        delete = start(deletion(native_client(lab.actor), [target], mode), pause=maker_lock)
        delete.paused()
        update = start(write)
        blocked_by(update, delete.pid)
        assert delete.finish().status_code == 302
        response = update.finish()
    assert response.status_code == (200 if kind == "native-edit" else 404)
    if kind == "native-edit":
        assert "no longer exists" in str(response.context["adminform"].form.non_field_errors())
    else:
        assert response.data
    assert not Box.objects.filter(pk=target.pk).exists()
    assert not Box.objects.filter(label="Race child").exists()
    assert Box.objects.values().get(pk=parent.pk) == parent_before
    rows = audit_delta(before)
    assert len(rows) == 1
    assert_deleted(rows[0], lab.actor, target)


@pytest.mark.parametrize("kind", WRITERS)
def test_all_parent_writers_refuse_cross_maker_parent_without_writes(lab, kind):
    parent = box(lab.other, "Foreign parent")
    child = None if kind in CREATORS else box(lab.home, "Unchanged home child")
    request = writer(lab, kind, parent, child)
    before = snapshot()
    vanished_parent(kind, request())
    assert snapshot() == before
