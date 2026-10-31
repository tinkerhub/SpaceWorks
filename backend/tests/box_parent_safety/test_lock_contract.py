"""Maker NK compatibility and stable multi-Maker native collector admission."""
import pytest
from django.contrib.admin.models import DELETION, LogEntry
from django.db import connection

from apps.boxes.models import Box
from tests.qr_target_safety_helpers import native_client
from tests.box_parent_safety.http_helpers import (
    assert_deleted, audit_delta, audit_ids, box, deletion, lab,
)
from tests.box_parent_safety.pg_helpers import (
    assert_maker_mode, blocked_by, maker_lock, workers,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("mode", ["single", "bulk"])
def test_native_delete_nk_allows_unrelated_maker_fk_key_share(lab, mode):
    parent = box(lab.home, "NK parent")
    with workers() as start:
        delete = start(deletion(lab.client, [parent], mode), pause=maker_lock)
        delete.paused()
        locks = [s for s in delete.statements if maker_lock(s)]
        assert len(locks) == 1
        assert_maker_mode(locks[0], "FOR NO KEY UPDATE")

        def unrelated_fk():
            # Actual insertion + immediate FK check, not a mocked lock or a try-lock.
            # The parent has no relationship to this unrelated surviving Box.
            from django.db import transaction
            with transaction.atomic():
                obj = box(lab.home, "Unrelated FK writer")
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                return obj.pk

        fk = start(unrelated_fk)
        # Must finish/commit while the actual native delete is still paused.
        fk_id = fk.finish()
        assert delete.thread.is_alive() and not delete.release.is_set()
        assert Box.objects.filter(pk=fk_id, makerspace=lab.home).exists()
        assert delete.finish().status_code == 302
    assert not Box.objects.filter(pk=parent.pk).exists()
    assert Box.objects.get(pk=fk_id).parent_id is None


def test_opposite_order_multi_maker_bulk_locks_sorted_and_audits_only_survivors(lab):
    objects = [box(lab.home, "A selected"), box(lab.other, "Z selected")]
    children = [box(obj.makerspace, "Surviving child", obj) for obj in objects]
    ids = sorted(obj.makerspace_id for obj in objects)
    before, logs = audit_ids(), set(LogEntry.objects.values_list("pk", flat=True))
    with workers() as start:
        first = start(deletion(lab.client, objects, "bulk", ordering="1"), pause=maker_lock)
        first.paused()
        second = start(deletion(native_client(lab.actor), list(reversed(objects)), "bulk", ordering="-1"))
        assert_maker_mode(blocked_by(second, first.pid), "FOR NO KEY UPDATE")
        assert first.finish().status_code == 302
        assert second.finish().status_code == 302
    for worker in (first, second):
        locks = [s for s in worker.statements if maker_lock(s)]
        assert len(locks) == 2, locks
        assert [s.params for s in locks] == [(pk,) for pk in ids]
        for statement in locks:
            assert statement.completed
            assert_maker_mode(statement, "FOR NO KEY UPDATE")
    assert not Box.objects.filter(pk__in=[obj.pk for obj in objects]).exists()
    for child in children:
        child.refresh_from_db()
        assert child.parent_id is None
    rows = audit_delta(before)
    assert len(rows) == 2  # second queryset's pre-lock objects must not be audited again
    for obj in objects:
        assert_deleted(next(row for row in rows if row.target_id == str(obj.pk)), lab.actor, obj)
    # Native attempts are intentionally logged before delete_queryset's transaction.
    attempts = list(LogEntry.objects.exclude(pk__in=logs))
    assert len(attempts) == 4
    for obj in objects:
        matching = [row for row in attempts if row.object_id == str(obj.pk)]
        assert len(matching) == 2
        assert all(row.action_flag == DELETION and row.user_id == lab.actor.pk for row in matching)
