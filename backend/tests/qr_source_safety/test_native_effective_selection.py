"""Native bulk admission uses the filtered action selection frozen before waiting."""
import pytest

from apps.boxes.models import QrCode
from tests.qr_source_safety.http_helpers import bulk_request, closure_lab
from tests.qr_source_safety.pg_helpers import atomic_request, exclusive, source_select, source_wait, workers
from tests.qr_source_safety.state_helpers import audit_ids, audits_since, plain, state
from tests.qr_target_safety_helpers import qr_for, target
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("across", [False, True])
@pytest.mark.parametrize("action", ["delete_selected", "revoke_selected"])
def test_native_effective_filter_excludes_foreign_nonmatching_and_late_rows(closure_lab, across, action):
    lab = closure_lab
    first, second = [qr_for(lab.home, target(lab.home, "product"), "product") for _ in range(2)]
    nonmatching = qr_for(lab.home, target(lab.home, "asset"), "asset")
    foreign = qr_for(lab.other, target(lab.other, "product"), "product")
    close_gate(lab.other, lab.root)
    query = f"?makerspace__id__exact={lab.home.pk}&target_type__exact=product"
    request = bulk_request(lab.native, [first, foreign], query=query, across=across, action=action)
    selected = [first, second] if across else [first]
    audits = audit_ids()
    with workers() as start:
        with exclusive(lab.home.pk) as owner:
            pending = start(atomic_request(request))
            source_wait(pending, owner, lab.home.pk)
            # Matches the filter but arrived after the action selection was frozen.
            late = qr_for(lab.home, target(lab.home, "product"), "product")
            protected = [foreign, nonmatching, late, *([] if across else [second])]
            untouched = plain(list(QrCode.objects.filter(pk__in=[q.pk for q in protected])
                                   .order_by("pk").values()))
        response = pending.finish()
    assert response.status_code == 302
    assert not any(source_select(sql, lab.other.pk) for sql in pending.statements)
    assert plain(list(QrCode.objects.filter(pk__in=[q.pk for q in protected])
                      .order_by("pk").values())) == untouched
    rows = audits_since(audits)
    assert len(rows) == len(selected)
    assert {(row.action, row.target_id, row.makerspace_id) for row in rows} == {
        ("control.object_deleted" if action == "delete_selected" else "qr.revoked",
         str(qr.pk), lab.home.pk) for qr in selected}
    if action == "delete_selected":
        assert not QrCode.objects.filter(pk__in=[q.pk for q in selected]).exists()
    else:
        assert set(QrCode.objects.filter(pk__in=[q.pk for q in selected])
                   .values_list("status", flat=True)) == {"revoked"}


@pytest.mark.parametrize("across", [False, True])
def test_raw_post_ids_outside_effective_native_queryset_cannot_freeze_or_delete(closure_lab, across):
    lab = closure_lab
    own = qr_for(lab.home, target(lab.home, "product"), "product")
    foreign = qr_for(lab.other, target(lab.other, "product"), "product")
    close_gate(lab.other, lab.root)
    request = bulk_request(lab.native, [foreign], across=across,
                           query=f"?makerspace__id__exact={lab.home.pk}")
    before = state()
    response = request()
    assert response.status_code == 302
    foreign.refresh_from_db()
    assert foreign.status == "active"
    if across:
        assert not QrCode.objects.filter(pk=own.pk).exists()
    else:
        assert state() == before
