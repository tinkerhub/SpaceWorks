"""Resolve one upstream check-in entry to a stable local principal.

Minting a `User` from an UNAUTHENTICATED public roster is a real widening of
`walk_in_services.create_person_record`, whose docstring describes a front-desk form
held by staff with `ISSUE_DIRECT_LOAN`. Three bounds keep it proportionate:

1. Only an entry that already passed the full eligibility gate reaches here.
2. Resolution is idempotent per (makerspace, mid), so repeat submissions reuse one
   row rather than minting.
3. The upstream roster is the ceiling on how many principals can ever exist -- a bot
   cannot invent people, only replay ones who are physically checked in.

The principal is a WALK-IN record (`is_walk_in=True`, unusable password). That marker
already blocks every credential-recovery path, and `transition_services` already
handles such a record later claiming a real account, so nothing new is invented here.
"""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.checkin.errors import denied
from apps.encryption.blind_index import active_generation, exact_hash

MODEL_LABEL = "checkin.CheckinIdentity"
FIELD_NAME = "mid"


def mid_hash(mid, *, makerspace_id, generation):
    """Domain-separated deterministic hash of the upstream mid.

    Uses the shared `exact_hash` primitive rather than a bespoke one so the mid is
    keyed, generation-scoped and makerspace-scoped exactly like every other exact
    index in the system. Scoping by makerspace means the same person at two
    makerspaces produces two unrelated hashes, so one tenant's rows cannot be
    correlated against another's.
    """
    return exact_hash(
        str(mid),
        generation=generation.generation,
        makerspace_id=makerspace_id,
        model_label=MODEL_LABEL,
        field_name=FIELD_NAME,
    )


def resolve_principal(makerspace, entry):
    """The `CheckinIdentity` for this roster entry, creating it if needed.

    Returns the identity row. The caller reads `.user` for the principal.

    **Two lookup paths, because the keyed one needs a key.** With scoped-PII
    encryption ON, `mid` is an envelope on disk and cannot be queried, so lookup goes
    through the keyed `mid_exact_hash`. With it OFF -- which `ScopedPiiModelMixin.save`
    itself supports, and which a simple self-host may legitimately run -- there is no
    search-key generation at all, so `mid` is plaintext and is queried directly.
    Requiring a key we do not have would turn every submission into a 503 on a
    deployment that has simply not configured KMS.

    A conditional unique constraint covers each path, so neither is a race window.
    """
    generation = _generation()
    digest = (
        mid_hash(entry.mid, makerspace_id=makerspace.id, generation=generation)
        if generation is not None
        else None
    )

    existing = _find(makerspace, entry, digest, generation)
    if existing is not None:
        _refuse_unusable(existing)
        _refresh_display_name(existing, entry)
        _touch_last_seen(existing)
        return existing

    try:
        with transaction.atomic():
            return _create(makerspace, entry, digest, generation)
    except IntegrityError:
        # Two concurrent submissions from the same person race here. The unique
        # constraint is the arbiter rather than a lock, because the losing side has
        # nothing to undo -- it simply reads the row the winner wrote.
        existing = _find(makerspace, entry, digest, generation)
        if existing is None:
            raise
        _refuse_unusable(existing)
        _refresh_display_name(existing, entry)
        _touch_last_seen(existing)
        return existing


def _generation():
    """The active search-key generation, or None when encryption is off."""
    if not settings.PII_ENCRYPTION_ENABLED:
        return None
    return active_generation()


def _find(makerspace, entry, digest, generation):
    from apps.checkin.models import CheckinIdentity

    queryset = CheckinIdentity.objects.select_related("user").filter(makerspace=makerspace)
    if generation is None:
        queryset = queryset.filter(mid=str(entry.mid), mid_exact_hash__isnull=True)
    else:
        queryset = queryset.filter(
            mid_exact_hash=digest, mid_hash_generation=generation
        )
    return queryset.first()


def _create(makerspace, entry, digest, generation):
    from apps.checkin.models import CheckinIdentity
    from apps.makerspaces.walk_in_services import create_person_record

    # No email and no phone: the roster carries neither, and inventing a placeholder
    # address would make the record look contactable when it is not.
    user = create_person_record(display_name=entry.name, email="", phone="")
    identity = CheckinIdentity(
        makerspace=makerspace,
        user=user,
        mid=str(entry.mid),
        mid_exact_hash=digest,
        mid_hash_generation=generation,
    )
    identity.save()
    return identity


def _refuse_unusable(identity):
    """Keep a stable principal's accountability restrictions effective."""
    user = identity.user
    if not user.is_active or user.access_status != User.AccessStatus.ACTIVE:
        raise denied(
            "checkin_access_restricted",
            "Your makerspace access is restricted. Contact makerspace staff.",
        )


def _refresh_display_name(identity, entry):
    """Keep the principal recognisable when someone is renamed upstream.

    Written only on an actual change so a repeat submission is a pure read.
    """
    name = (entry.name or "").strip()[:200]
    if name and identity.user.display_name != name:
        identity.user.display_name = name
        identity.user.save(update_fields=["display_name"])


def _touch_last_seen(identity):
    from apps.checkin.models import CheckinIdentity

    last_seen_at = timezone.now()
    # Do not use identity.save(): CheckinIdentity inherits ScopedPiiModelMixin, so
    # save() enters the mapped-write path and its write fence. A roster verification
    # during a rollback fence must not fail over this non-PII timestamp update.
    CheckinIdentity.objects.filter(pk=identity.pk).update(last_seen_at=last_seen_at)
    identity.last_seen_at = last_seen_at
