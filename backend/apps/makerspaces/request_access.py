"""Who may submit a borrow request — the single answer, in one place.

Four effective policies, DERIVED rather than stored. Only ``public_request_mode`` is
a column; the rest falls out of whether the ``membership`` module is installed:

===========  ====================  ============================================
`membership` `public_request_mode` who may submit
===========  ====================  ============================================
on           (any)                 ``members``    — an active MakerspaceMembership
off          ``checked_in``        ``checked_in`` — active member, or verified
                                   against the upstream check-in roster
off          ``anyone``            ``anyone``     — no account at all
off          ``disabled``          ``accounts``   — any active authenticated account
===========  ====================  ============================================

**Why one stored mode and not one boolean per option.** This module previously held a
single ``anonymous_requests_enabled`` boolean. Adding check-in as a second boolean
would have made "both on" representable, and the two disagree: ``anyone`` is strictly
weaker, so a row carrying both would quietly make the check-in gate decorative while
the console showed it as on. A single mode makes that state unrepresentable rather
than merely forbidden — there is no pair of writes that can produce it.

Membership always wins, and wins by FORCING rather than refusing. `RequestSubmitView`
takes its account-less branches *before* it reaches any membership guard, so a row
carrying both membership and an open mode would let a stranger walk straight past the
membership requirement the operator had just switched on. Enforced at three depths so
no write path can reconstruct the state:

1. ``Makerspace.save()`` calls :func:`reconcile_mode` — the row cannot be persisted
   in the impossible state by ANY caller (module install/uninstall, profile
   application, the ``/control/`` capability matrix, ``setup_instance``, ``seed_demo``,
   a plain ``obj.save()``).
2. :func:`set_request_access` is the only *deliberate* writer and takes the row lock,
   so a concurrent membership install cannot land between its check and its save.
3. :func:`effective_policy` re-derives at request time, so a row written by raw SQL or
   restored from an old backup still fails closed. A mode string this module does not
   recognise reads as ``disabled`` — the closed direction.

Refusing a membership install because of an unrelated public-access mode would block a
legitimate module change from the console and the setup tick list, so that path forces
and audits the before/after policy. Only the deliberate writer refuses.
"""

MEMBERSHIP_MODULE = "membership"

# Effective policies (derived; what callers branch on).
MEMBERS = "members"
ACCOUNTS = "accounts"
CHECKED_IN = "checked_in"
ANYONE = "anyone"

# Stored modes (the column).
MODE_DISABLED = "disabled"
MODE_CHECKED_IN = "checked_in"
MODE_ANYONE = "anyone"
MODES = (MODE_DISABLED, MODE_CHECKED_IN, MODE_ANYONE)

MODE_CHOICES = (
    (MODE_DISABLED, "An account is required"),
    (MODE_CHECKED_IN, "Anyone checked in upstream and working on a project"),
    (MODE_ANYONE, "Anyone, no account needed"),
)

POLICY_LABELS = {
    MEMBERS: "active members of this makerspace",
    ACCOUNTS: "anyone with a signed-in account",
    CHECKED_IN: "anyone checked in upstream and working on a project",
    ANYONE: "anyone, no account needed",
}

# What each policy is reached by asking for, for the CLI and installer.
POLICY_FOR_MODE = {
    MODE_DISABLED: ACCOUNTS,
    MODE_CHECKED_IN: CHECKED_IN,
    MODE_ANYONE: ANYONE,
}


def membership_installed(enabled_modules) -> bool:
    """Pure predicate over the stored key list.

    Deliberately NOT ``platform.module_enabled``: that also asks whether the deployment
    still ships the app, and this is the fail-closed direction. A tenant that asked for
    membership must not have strangers admitted just because the app is tombstoned, and
    the model layer cannot import ``platform`` anyway (``platform`` imports the models).
    """
    return MEMBERSHIP_MODULE in set(enabled_modules or [])


def canonical_mode(mode) -> str:
    """A recognised mode, or ``disabled``.

    An unknown string — raw SQL, a restored backup written by a newer version, a typo
    in a fixture — must never read as an OPEN mode. Falling back to ``disabled`` keeps
    the unknown-value direction closed.
    """
    return mode if mode in MODES else MODE_DISABLED


def reconcile_mode(enabled_modules, public_request_mode) -> str:
    """The resulting stored mode. Membership wins."""
    mode = canonical_mode(public_request_mode)
    if membership_installed(enabled_modules):
        return MODE_DISABLED
    return mode


def policy_for(enabled_modules, public_request_mode) -> str:
    mode = reconcile_mode(enabled_modules, public_request_mode)
    if membership_installed(enabled_modules):
        return MEMBERS
    return POLICY_FOR_MODE[mode]


def _usable_checkin_space_id(space_id) -> bool:
    """Keep the deliberate writer and request-time fail-close on one definition."""
    return space_id is not None and space_id > 0


def effective_policy(makerspace) -> str:
    """Who may submit to this makerspace right now."""
    if (
        makerspace.public_request_mode == MODE_CHECKED_IN
        and not _usable_checkin_space_id(makerspace.checkin_space_id)
    ):
        # The deployment-global roster cannot be tenant-scoped without a positive
        # binding, so an unusable value collapses like an unrecognised stored mode.
        return policy_for(makerspace.enabled_modules, MODE_DISABLED)
    return policy_for(makerspace.enabled_modules, makerspace.public_request_mode)


def anonymous_requests_allowed(makerspace) -> bool:
    """Request-time check. Re-derived rather than trusting the column alone."""
    return effective_policy(makerspace) == ANYONE


def checkin_requests_allowed(makerspace) -> bool:
    """Request-time check for the upstream-check-in gate."""
    return effective_policy(makerspace) == CHECKED_IN


def account_required(makerspace) -> bool:
    """True when a caller must hold an account to submit at all."""
    return effective_policy(makerspace) in (MEMBERS, ACCOUNTS)


class RequestAccessConflict(Exception):
    """An open mode was asked for in a configuration that cannot serve it."""


def set_request_access(makerspace, mode, *, actor=None):
    """The ONE deliberate writer. Returns the effective policy AFTER the write.

    Raises :class:`RequestAccessConflict` when asked to open account-less submission on
    a makerspace that has `membership` installed, or to select ``checked_in`` without
    a configured upstream URL and space binding. An explicit operator request is
    refused loudly rather than silently downgraded — the opposite of the module-install
    path, which forces, because there the operator was asking about modules rather than
    about this mode.
    """
    from django.conf import settings
    from django.db import transaction

    from apps.audit import services as audit
    from apps.makerspaces.models import Makerspace

    wanted = canonical_mode(mode)
    if wanted != mode:
        raise RequestAccessConflict(f"Unknown request-access mode: {mode!r}.")

    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        before = effective_policy(locked)
        if wanted != MODE_DISABLED and membership_installed(locked.enabled_modules):
            raise RequestAccessConflict(
                "The membership module is installed, so borrow requests require an "
                "account. Uninstall `membership` first, or leave public requests off."
            )
        if wanted == MODE_CHECKED_IN and not settings.CHECKIN_API_URL.strip():
            # A blank URL makes every lookup and submission return 503, so the
            # deliberate writer must not advertise an unusable checked-in policy.
            raise RequestAccessConflict(
                "Configure CHECKIN_API_URL before selecting `checked_in`."
            )
        if wanted == MODE_CHECKED_IN and not _usable_checkin_space_id(
            locked.checkin_space_id
        ):
            # A non-positive binding cannot identify an upstream tenant, and a second
            # makerspace on the same deployment would admit the same people.
            raise RequestAccessConflict(
                "Set a positive upstream check-in space id before selecting `checked_in`."
            )
        if locked.public_request_mode != wanted:
            locked.public_request_mode = wanted
            locked.save(update_fields=["public_request_mode"])
        after = effective_policy(locked)
        if before != after:
            audit.record(
                actor,
                "makerspace.request_access_changed",
                makerspace=locked,
                target=locked,
                meta={"before": before, "after": after},
            )
    makerspace.refresh_from_db(fields=["public_request_mode"])
    return after
