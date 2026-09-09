"""P2: one stable principal per upstream check-in identity.

The property under test is that a checked-in person is a REAL person to the rest of
the system -- separately holdable, separately returnable, separately restrictable --
because the shared anonymous sentinel is none of those things.
"""

from datetime import datetime, timedelta, timezone

import pytest

from apps.checkin.client import CheckinEntry
from apps.checkin.identity import resolve_principal
from apps.checkin.models import CheckinIdentity
from apps.makerspaces.models import Makerspace
from tests.encryption.conftest import enabled_encryption

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)

CORE_PLUS = ["public_inventory", "request_workflow", "staff_admin", "scanner",
             "evidence_uploads", "qr_management"]


def _space(slug):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=list(CORE_PLUS), checkin_space_id=1
    )


def _entry(mid=443, name="Ada Example", project="Metrocard"):
    return CheckinEntry(
        mid=mid,
        name=name,
        avatar="",
        purpose="Working on a project",
        project_name=project,
        check_in_time=NOW - timedelta(hours=1),
        check_out_time=NOW + timedelta(hours=1),
        space_id=1,
    )


def test_resolving_twice_reuses_one_principal():
    """Otherwise every submission mints a new person and nobody has a history."""
    space = _space("ci-idem")

    first = resolve_principal(space, _entry())
    second = resolve_principal(space, _entry())

    assert first.pk == second.pk
    assert first.user_id == second.user_id
    assert CheckinIdentity.objects.filter(makerspace=space).count() == 1


def test_two_people_get_two_principals():
    space = _space("ci-two")

    a = resolve_principal(space, _entry(mid=1, name="Ada Example"))
    b = resolve_principal(space, _entry(mid=2, name="Bee Sample"))

    assert a.user_id != b.user_id


def test_identical_names_on_different_mids_stay_separate():
    """Names are not identity -- the mid is. Two people who share a display name must
    not share a loan history."""
    space = _space("ci-samename")

    a = resolve_principal(space, _entry(mid=1, name="Ada Example"))
    b = resolve_principal(space, _entry(mid=2, name="Ada Example"))

    assert a.user_id != b.user_id


def test_the_principal_is_a_walk_in_record_with_no_usable_password():
    space = _space("ci-walkin")

    identity = resolve_principal(space, _entry())

    assert identity.user.is_walk_in is True
    assert identity.user.has_usable_password() is False
    assert identity.user.email == ""


def test_no_membership_row_is_created():
    """The check-in gate only runs with the membership module OFF. Inventing a
    tenant-binding membership would contradict the operator's configuration."""
    from apps.makerspaces.models import MakerspaceMembership

    space = _space("ci-nomember")
    identity = resolve_principal(space, _entry())

    assert not MakerspaceMembership.objects.filter(user=identity.user).exists()


def test_the_same_person_at_two_makerspaces_gets_two_hashes():
    """Hashes are makerspace-scoped, so one tenant's rows cannot be correlated
    against another's. Only meaningful with encryption ON -- that is the mode that
    produces hashes at all."""
    with enabled_encryption():
        a = _space("ci-tenant-a")
        b = _space("ci-tenant-b")

        first = resolve_principal(a, _entry(mid=99))
        second = resolve_principal(b, _entry(mid=99))

        assert first.mid_exact_hash is not None
        assert bytes(first.mid_exact_hash) != bytes(second.mid_exact_hash)


def test_the_raw_mid_is_recoverable():
    """A one-way hash alone would make an overdue borrower unidentifiable the moment
    they check out and leave the roster."""
    space = _space("ci-recover")
    identity = resolve_principal(space, _entry(mid=4242))

    identity.refresh_from_db()
    assert identity.mid == "4242"


def test_the_stored_mid_is_not_plaintext_when_encryption_is_on():
    """The mapped field must be an envelope on disk, not the bare id."""
    from django.db import connection

    with enabled_encryption():
        space = _space("ci-envelope")
        resolve_principal(space, _entry(mid=987654))

        with connection.cursor() as cursor:
            cursor.execute("SELECT mid FROM checkin_checkinidentity")
            stored = cursor.fetchone()[0]
        assert "987654" not in str(stored)


def test_the_plaintext_path_still_resolves_one_principal_with_encryption_off():
    """A self-host that never configured KMS must still be able to use the gate.
    There is no search-key generation in that mode, so lookup falls back to the
    plaintext mid -- and must still be idempotent, or one person's loan history
    would split across two principals."""
    space = _space("ci-plain")

    first = resolve_principal(space, _entry(mid=555))
    second = resolve_principal(space, _entry(mid=555))

    assert first.pk == second.pk
    assert first.mid_exact_hash is None
    assert CheckinIdentity.objects.filter(makerspace=space).count() == 1


def test_encryption_on_and_off_do_not_collide_on_one_row():
    """The two conditional unique constraints must not overlap: a hashed row and a
    plaintext row are distinguished by `mid_exact_hash IS NULL`."""
    space = _space("ci-mixed")
    plain = resolve_principal(space, _entry(mid=321))

    with enabled_encryption():
        hashed = resolve_principal(space, _entry(mid=321))

    # Different lookup keys, so this legitimately produces two rows. Pinned so the
    # behaviour is a decision on record rather than a surprise during a key rollout.
    assert plain.pk != hashed.pk
    assert plain.mid_exact_hash is None
    assert hashed.mid_exact_hash is not None


def test_a_renamed_person_keeps_one_principal_and_gets_the_new_name():
    space = _space("ci-rename")
    first = resolve_principal(space, _entry(mid=7, name="Ada Example"))

    second = resolve_principal(space, _entry(mid=7, name="Ada Newname"))

    assert first.user_id == second.user_id
    second.user.refresh_from_db()
    assert second.user.display_name == "Ada Newname"


def test_the_principal_is_not_the_anonymous_sentinel():
    """The whole point. `anonymous_requester_ids()` excludes the sentinel from
    top-borrowers and accountability; a per-person principal must fall outside that
    set so reports and restriction work with no change to either."""
    from apps.makerspaces.anonymous_requesters import anonymous_requester_ids

    space = _space("ci-not-sentinel")
    identity = resolve_principal(space, _entry())

    assert identity.user_id not in anonymous_requester_ids()


def test_a_checked_in_principal_can_be_restricted():
    """The sentinel must never be restricted, because that would restrict every
    future account-less requester at once. A per-person principal has no such
    problem, and accountability depends on it."""
    from apps.accounts.principal_guards import refuse_anonymous_requester_access_mutation

    space = _space("ci-restrict")
    identity = resolve_principal(space, _entry())

    # Must NOT raise -- this is the guard that protects the sentinel.
    refuse_anonymous_requester_access_mutation(identity.user)
