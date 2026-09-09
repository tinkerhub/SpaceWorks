"""The checked-in request policy stays tenant-bound and fail-closed."""

import pytest

from apps.makerspaces.models import Makerspace
from apps.makerspaces.request_access import (
    ACCOUNTS,
    ANYONE,
    CHECKED_IN,
    MEMBERS,
    MODE_ANYONE,
    MODE_CHECKED_IN,
    MODE_DISABLED,
    RequestAccessConflict,
    canonical_mode,
    effective_policy,
    policy_for,
    set_request_access,
)

pytestmark = pytest.mark.django_db

CORE_PLUS = [
    "public_inventory",
    "request_workflow",
    "staff_admin",
    "scanner",
    "evidence_uploads",
    "qr_management",
]


def _space(slug, *, modules=CORE_PLUS, mode=MODE_DISABLED, checkin_space_id=None):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=list(modules),
        public_request_mode=mode,
        checkin_space_id=checkin_space_id,
    )


def test_checked_in_is_its_own_policy():
    space = _space("ra-ci", mode=MODE_CHECKED_IN, checkin_space_id=1)
    assert effective_policy(space) == CHECKED_IN


@pytest.mark.parametrize("space_id", [0, -1])
def test_non_positive_checked_in_binding_reads_as_closed(space_id):
    """0069 permits every non-null integer, so request-time derivation must defend
    rows written by raw SQL, an old restore, or another writer behind the service."""
    space = _space(
        f"ra-ci-unusable-{abs(space_id)}",
        mode=MODE_CHECKED_IN,
        checkin_space_id=space_id,
    )

    assert effective_policy(space) == ACCOUNTS


def test_missing_checked_in_binding_reads_as_closed():
    from types import SimpleNamespace

    space = SimpleNamespace(
        enabled_modules=CORE_PLUS,
        public_request_mode=MODE_CHECKED_IN,
        checkin_space_id=None,
    )

    assert effective_policy(space) == ACCOUNTS


def test_membership_forces_checked_in_off_like_every_other_open_mode():
    space = _space(
        "ra-ci-member",
        modules=[*CORE_PLUS, "membership"],
        mode=MODE_CHECKED_IN,
        checkin_space_id=1,
    )

    space.refresh_from_db()
    assert space.public_request_mode == MODE_DISABLED
    assert effective_policy(space) == MEMBERS


@pytest.mark.parametrize("space_id", [0, -1])
def test_checked_in_refuses_a_non_positive_space_binding(settings, space_id):
    settings.CHECKIN_API_URL = "https://checkin.example.test/roster"
    space = _space(f"ra-ci-refuse-{abs(space_id)}", checkin_space_id=space_id)

    with pytest.raises(RequestAccessConflict, match="space id"):
        set_request_access(space, MODE_CHECKED_IN)

    space.refresh_from_db()
    assert space.public_request_mode == MODE_DISABLED


def test_checked_in_requires_an_upstream_space_binding(settings):
    """The roster endpoint is deployment-global and carries no tenant. Without a
    binding, two makerspaces on one deployment would admit exactly the same people."""
    settings.CHECKIN_API_URL = "https://checkin.example.test/roster"
    space = _space("ra-ci-unbound")

    with pytest.raises(RequestAccessConflict):
        set_request_access(space, MODE_CHECKED_IN)

    space.refresh_from_db()
    assert space.public_request_mode == MODE_DISABLED


def test_checked_in_requires_a_configured_upstream_url(settings):
    settings.CHECKIN_API_URL = ""
    space = _space("ra-ci-no-url", checkin_space_id=1)

    with pytest.raises(RequestAccessConflict, match="CHECKIN_API_URL"):
        set_request_access(space, MODE_CHECKED_IN)

    space.refresh_from_db()
    assert space.public_request_mode == MODE_DISABLED


def test_binding_then_opening_checked_in_succeeds(settings):
    settings.CHECKIN_API_URL = "https://checkin.example.test/roster"
    space = _space("ra-ci-bound", checkin_space_id=1)

    assert set_request_access(space, MODE_CHECKED_IN) == CHECKED_IN


def test_moving_between_open_modes_replaces_rather_than_accumulates(settings):
    """The whole reason this is one stored mode and not two booleans: `anyone` is
    strictly weaker than `checked_in`, so a row holding both would silently make the
    check-in gate decorative. Selecting one must clear the other."""
    settings.CHECKIN_API_URL = "https://checkin.example.test/roster"
    space = _space("ra-ci-swap", mode=MODE_ANYONE, checkin_space_id=1)

    assert set_request_access(space, MODE_CHECKED_IN) == CHECKED_IN
    space.refresh_from_db()
    assert space.public_request_mode == MODE_CHECKED_IN

    assert set_request_access(space, MODE_ANYONE) == ANYONE
    space.refresh_from_db()
    assert space.public_request_mode == MODE_ANYONE


def test_an_unrecognised_mode_reads_as_closed():
    """Defence in depth for a value the constraint cannot catch.

    The database refuses an unknown mode outright, so this cannot be tested by
    writing one -- `test_the_database_refuses_an_unknown_mode_outright` proves that.
    It is tested at the function level instead, because the derivation must still
    fail CLOSED for a row that reaches Python without passing the constraint: a dump
    restored with constraints deferred, or a fixture loaded into a table created
    before the constraint existed.
    """
    assert canonical_mode("from_the_future") == MODE_DISABLED
    assert canonical_mode(None) == MODE_DISABLED
    assert canonical_mode("") == MODE_DISABLED
    assert policy_for(CORE_PLUS, "from_the_future") == ACCOUNTS
    # And it must not accidentally read as the strongest open mode either.
    assert policy_for(CORE_PLUS, "from_the_future") != ANYONE


def test_set_request_access_refuses_an_unknown_mode():
    space = _space("ra-ci-badmode")

    with pytest.raises(RequestAccessConflict):
        set_request_access(space, "from_the_future")


def test_the_database_refuses_an_unknown_mode_outright():
    from django.db import IntegrityError, transaction

    space = _space("ra-ci-constraint")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Makerspace.objects.filter(pk=space.pk).update(public_request_mode="nope")


def test_the_database_refuses_checked_in_without_a_space_binding():
    from django.db import IntegrityError, transaction

    space = _space("ra-ci-binding-constraint")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Makerspace.objects.filter(pk=space.pk).update(
                public_request_mode=MODE_CHECKED_IN
            )
