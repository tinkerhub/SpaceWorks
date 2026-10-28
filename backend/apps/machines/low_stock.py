"""Fail-safe automatic procurement for kernel consumable pools."""

import logging
import zlib

from django.db import connection, transaction

from apps.audit import services as audit
from apps.procurement.models import ToBuyItem
from apps.separability.registry import runtime_active

logger = logging.getLogger(__name__)
OPEN_STATUSES = (ToBuyItem.Status.REQUESTED, ToBuyItem.Status.APPROVED, ToBuyItem.Status.ORDERED)


def maybe_flag_low_stock(actor, pool):
    """Create at most one open restock item once a pool reaches its threshold."""
    try:
        if not getattr(pool, "pk", None):
            return None
        # A live cross-app workflow hook, so it is runtime rather than retention: a
        # deployment that has tombstoned procurement offers no screen on which this
        # row could ever be seen or actioned, and writing it would grow a table
        # nothing reads. Existing rows are untouched -- this only declines to add.
        if not runtime_active("procurement"):
            return None
        from apps.machines.models import MachineConsumablePool
        with transaction.atomic():
            locked = MachineConsumablePool.objects.select_for_update(of=("self",)).select_related(
                "machine"
            ).get(pk=pool.pk)
            threshold = locked.low_threshold_grams
            if threshold is None or threshold <= 0 or not locked.is_active or locked.remaining_grams > threshold:
                return None
            machine_type_id = locked.machine_type_id or (locked.machine.machine_type_id if locked.machine_id is not None else None)
            noun = _restock_noun(locked, machine_type_id)
            name = f"{noun} restock: {locked.material} {locked.color}".strip()
            name_key = zlib.crc32(name.encode("utf-8"))
            if name_key >= 2 ** 31:
                name_key -= 2 ** 32
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [locked.makerspace_id, name_key])
            if ToBuyItem.objects.filter(source_pool=locked, kind=ToBuyItem.Kind.PRINTING, status__in=OPEN_STATUSES).exists():
                return None
            created_by = actor if getattr(actor, "is_authenticated", False) else None
            item = ToBuyItem.objects.create(
                makerspace=locked.makerspace,
                # Every machine consumable restocks through the printing stream: it is the
                # one MANAGE_MACHINES reaches and narrows by machine type. HARDWARE would show
                # vinyl or resin to inventory staff and hide it from the machine's own team.
                kind=ToBuyItem.Kind.PRINTING,
                machine_type_id=machine_type_id,
                name=name,
                quantity=1,
                source_pool=locked,
                created_by=created_by,
                status=ToBuyItem.Status.REQUESTED,
            )
            audit.record(created_by, "procurement.low_stock_flagged", makerspace=locked.makerspace, target=item, meta={"pool_id": locked.pk, "remaining": str(locked.remaining_grams), "threshold": str(threshold), "to_buy_item_id": item.pk})
            return item
    except Exception:
        logger.exception("Failed to flag low-stock machine consumable pool %s", getattr(pool, "pk", None))
        return None


# Built-in types whose stock has a well-known name.
_RESTOCK_NOUNS = {"3d_printer": "Filament", "resin_printer": "Resin"}


def _restock_noun(pool, machine_type_id):
    """What the restock item calls the stock: from the pool's type, else its unit.

    An unscoped gram pool is the historical shared filament pool.
    """
    from apps.machines.models import MachineType
    machine_type = MachineType.objects.filter(pk=machine_type_id).first() if machine_type_id else None
    if machine_type is None:
        return "Filament" if pool.unit == "grams" else "Consumable"
    if machine_type.makerspace_id is None and machine_type.slug in _RESTOCK_NOUNS:
        return _RESTOCK_NOUNS[machine_type.slug]
    return machine_type.name
