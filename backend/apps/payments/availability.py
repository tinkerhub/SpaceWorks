from django.db import transaction

from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.payments.resolution import resolve_payment_source


def online_payments_enabled(makerspace, domain):
    """Whether this makerspace may accept online payments for a domain.

    Every clause here is an additive AND, never a replacement, so turning any one of
    them on can never make an unconfigured space start charging:

    * the `payments` MODULE ships the surfaces at all (phase 3),
    * `payments.enabled` is the space manager's master switch in front of them (A6),
    * the per-domain feature says which domains may charge,
    * and credentials must actually resolve.

    Uninstalling the module stops new charges without touching stored credentials or
    any existing Payment row -- and it deliberately does NOT reach the webhook, which
    settles a real charge regardless, because money already taken must never be
    stranded by a toggle.
    """
    return (
        module_enabled(makerspace, "payments")
        and feature_enabled(makerspace, "payments.enabled")
        and feature_enabled(makerspace, f"payments.{domain}")
        and resolve_payment_source(makerspace) is not None
    )


def new_charges_allowed_locked(makerspace):
    """Whether a NEW Payment row may be raised, re-checked under the makerspace lock.

    Only creation is gated. Settling, waiving, paying or reading a charge that already
    exists stays open with the module off (see `docs/INVARIANTS.md`), because a retained
    charge must stay payable and settleable. Call it inside the creating transaction so
    a concurrent uninstall serializes against the insert, the same rule as
    `guards.require_module_locked`.
    """
    from apps.makerspaces.models import Makerspace

    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        return module_enabled(locked, "payments")
