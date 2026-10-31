"""Scalar profile writes compose; project-list presence still owns storage."""
import pytest
from django.db import transaction
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.audit.models import AuditLog
from apps.evidence.storage import StorageUnavailable
from apps.makerspaces import profile_services
from apps.makerspaces.models import MemberProfile
from tests.metadata_boundaries.helpers import (
    assert_caller_rollback, no_storage, profile_case, snapshot,
)

pytestmark = pytest.mark.django_db


def test_scalar_update_preserves_existing_images_projects_and_private_audit(no_storage):
    case = profile_case()
    original_projects = list(case.profile.projects.values())
    with transaction.atomic():
        profile_services.save_profile(case.membership, {
            "headline": "Learning lathes", "bio": "Private audit content",
            "is_visible": True, "show_attended_events": True,
            "avatar_key": "member/forged.png", "image_key": "items/forged.png",
        })
        case.profile.refresh_from_db(); case.space.refresh_from_db()
        assert case.profile.headline == "Learning lathes"
        assert case.profile.avatar_key == f"member/{case.space.pk}/avatar.png"
        assert list(case.profile.projects.values()) == original_projects
        assert case.space.storage_bytes_used == 231
        audit = AuditLog.objects.get(makerspace=case.space, action="member.profile_updated")
        assert audit.meta["projects_before"] == audit.meta["projects_after"] == 1
        assert audit.meta["visibility_changed"] is True
        assert audit.meta["attended_events_changed"] is True
        assert set(audit.meta["fields"]) == {"headline", "bio", "is_visible", "show_attended_events"}
        assert "Private audit content" not in str(audit.meta)
        assert case.profile.avatar_key not in str(audit.meta)


@pytest.mark.parametrize("existing", [False, True])
def test_caller_rollback_undoes_profile_creation_flags_and_audit(existing, no_storage):
    case = profile_case(f"profile-rollback-{existing}")
    if not existing:
        # Use a second membership, avoiding any image-bearing cascade in setup.
        from tests.return_helpers import make_member
        from apps.makerspaces.models import MakerspaceMembership

        actor = make_member("profile-new-member", case.space)
        case.membership = MakerspaceMembership.objects.get(user=actor, makerspace=case.space)
    def check(profile):
        assert profile.headline == "Rolled back"
        assert MemberProfile.objects.filter(membership=case.membership).exists()
        assert AuditLog.objects.filter(makerspace=case.space, action="member.profile_updated").exists()
    assert_caller_rollback(case.space, lambda: profile_services.save_profile(
        case.membership, {"headline": "Rolled back", "show_attended_events": True},
    ), check)


@pytest.mark.parametrize("projects", [[], "unchanged"])
def test_project_key_presence_refuses_outer_atomic_before_storage(projects, no_storage):
    case = profile_case("profile-project-presence")
    rows = [{"id": case.project.pk, "title": case.project.title, "links": []}] if projects == "unchanged" else projects
    original = snapshot(case.space)
    with transaction.atomic(), pytest.raises(StorageUnavailable):
        profile_services.save_profile(case.membership, {"projects": rows, "headline": "Rejected"})
    assert snapshot(case.space) == original


def test_read_uses_latest_consent_flag_without_creating_or_writing_rows(no_storage):
    case = profile_case("profile-read-flags")
    case.space.enabled_modules = [*case.space.enabled_modules, "events"]
    case.space.save(update_fields=["enabled_modules"])
    # Warm the reverse cache, then update through a separately locked instance.
    assert case.membership.profile.show_attended_events is False
    with transaction.atomic():
        profile_services.save_profile(case.membership, {"show_attended_events": True})
    original = snapshot(case.space)
    with CaptureQueriesContext(connection) as queries:
        payload = profile_services.read_profile(case.membership)
    assert "recent_attended_events" in payload["activity"]
    assert snapshot(case.space) == original
    assert all(not row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries)


def test_read_missing_profile_returns_defaults_without_get_writes(no_storage):
    case = profile_case("profile-missing-read")
    from tests.return_helpers import make_member
    from apps.makerspaces.models import MakerspaceMembership

    actor = make_member("profile-missing-reader", case.space)
    membership = MakerspaceMembership.objects.get(user=actor, makerspace=case.space)
    original = snapshot(case.space)
    with CaptureQueriesContext(connection) as queries:
        payload = profile_services.read_profile(membership, include_activity=False)
    assert payload["is_visible"] is False and payload["projects"] == []
    assert not MemberProfile.objects.filter(membership=membership).exists()
    assert snapshot(case.space) == original
    assert all(not row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries)
