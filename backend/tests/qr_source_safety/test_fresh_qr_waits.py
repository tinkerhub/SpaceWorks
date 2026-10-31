"""A stale admitted identity is never saved/deleted/scanned after real SQL waits."""
import pytest
from django.contrib.admin.models import DELETION, LogEntry
from django.db import transaction

from apps.boxes.models import QrCode
from tests.box_parent_safety.pg_helpers import blocked_by, workers
from tests.qr_source_safety.http_helpers import closure_lab, prepared
from tests.qr_source_safety.pg_helpers import (
    assert_shared, atomic_request, exclusive, source_wait, table_lock,
)
from tests.qr_source_safety.race_helpers import (
    backend_pid, change_qr, expected_qr_denial, replacement,
)
from tests.qr_source_safety.state_helpers import state

pytestmark = pytest.mark.django_db(transaction=True)
NATIVE = ("native-edit", "native-single", "native-bulk", "native-revoke", "native-rebind")
MUTATIONS = ("moved", "deleted", "retargeted")


@pytest.mark.parametrize("kind", ["api-scan", "api-resolve", *NATIVE])
@pytest.mark.parametrize("mutation", MUTATIONS)
def test_qr_identity_fresh_after_observed_source_n_wait(closure_lab, kind, mutation):
    lab = closure_lab
    case = prepared(lab, kind)
    dest = replacement(lab, mutation)
    with workers() as start:
        with exclusive(lab.home.pk) as owner:
            pending = start(atomic_request(case.call))
            source_wait(pending, owner, lab.home.pk)
            change_qr(lab, case, mutation, dest)
            before = state()
        response = pending.finish()
    assert response.status_code == expected_qr_denial(kind, mutation)
    # Native moved/vanished identities must use Django Http404, never DRF Conflict.
    assert state() == before


@pytest.mark.parametrize("kind", ["api-scan", "api-resolve", "api-revoke", "api-rebind", *NATIVE])
@pytest.mark.parametrize("mutation", MUTATIONS)
def test_qr_identity_fresh_after_actual_qr_row_wait(closure_lab, kind, mutation):
    lab = closure_lab
    case = prepared(lab, kind)
    dest = replacement(lab, mutation)
    attempts = set(LogEntry.objects.values_list("pk", flat=True))
    with workers() as start:
        with transaction.atomic():
            QrCode.objects.select_for_update().get(pk=case.qr.pk)
            owner = backend_pid()
            pending = start(atomic_request(case.call))
            blocked_by(pending, owner, table_lock(QrCode._meta.db_table))
            assert_shared(pending.pid, lab.home.pk)
            change_qr(lab, case, mutation, dest)
            before = state(attempts=kind != "native-bulk")
        response = pending.finish()
    assert response.status_code == expected_qr_denial(kind, mutation)
    assert state(attempts=kind != "native-bulk") == before
    rows = list(LogEntry.objects.exclude(pk__in=attempts))
    if kind == "native-bulk":
        # delete_selected logs before delete_queryset's atomic refusal. The outer
        # client dispatch renders Http404, so the diagnostic attempt can commit.
        assert len(rows) == 1
        assert (rows[0].object_id, rows[0].action_flag) == (str(case.qr.pk), DELETION)
    else:
        assert rows == []
