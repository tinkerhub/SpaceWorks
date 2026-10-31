"""Every metadata entrypoint must enter its real persistent tenant fence."""
import pytest
from django.db import transaction

from apps.admin_api.bulk_import_apply import apply_import
from apps.admin_api.models import BulkImportJob
from apps.events import services_series
from apps.makerspaces import profile_services
from tests.events.test_series_inheritance_invariants import series_case
from tests.machines.public_service_helpers import service_lab
from tests.makerspaces.purge_test_support import purge_clock
from tests.metadata_boundaries.helpers import (
    bulk_case, fence, intake_case, no_storage, profile_case, snapshot,
)

WRITERS = ("profile", "typed-generic", "typed-printer", "legacy-printer", "series", "bulk")
pytestmark = pytest.mark.django_db


def writer_case(writer, service_lab):
    if writer == "profile":
        case = profile_case("profile-real-fence")
        return case.space, case.actor, lambda: profile_services.save_profile(case.membership, {"headline": "Forbidden"})
    if writer in ("typed-generic", "typed-printer", "legacy-printer"):
        case = intake_case(service_lab, writer, queue=writer == "legacy-printer")
        return case.space, case.actor, case.invoke
    if writer == "series":
        space, actor, series, _events = series_case("series-real-fence", published=False)
        return space, actor, lambda: services_series.update_series(series, actor=actor, title="Forbidden")
    case = bulk_case("bulk-real-fence")
    job = BulkImportJob.objects.create(makerspace=case.space, actor=case.actor, mode="apply")
    def progress(done, _total):
        BulkImportJob.objects.filter(pk=job.pk).update(processed_rows=done)
        pytest.fail("closed tenant reached preview's mutating progress callback")
    return case.space, case.actor, lambda: apply_import(case.actor, case.space, [{"name": "", "total_quantity": "bad"}], {}, progress_callback=progress)


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("state", ["frozen", "not-restored"])
def test_real_metadata_fences_deny_before_domain_audit_or_storage_writes(writer, state, service_lab, no_storage):
    space, actor, invoke = writer_case(writer, service_lab)
    expected = fence(space, actor, state)
    original = snapshot(space)
    with transaction.atomic(), pytest.raises(expected):
        invoke()
    assert snapshot(space) == original


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("writer", WRITERS)
def test_committed_real_purge_intent_denies_metadata_without_deleting_tenant(writer, service_lab, no_storage, purge_clock):
    space, actor, invoke = writer_case(writer, service_lab)
    expected = fence(space, actor, "purge-started")
    original = snapshot(space)
    with transaction.atomic(), pytest.raises(expected):
        invoke()
    assert snapshot(space) == original
