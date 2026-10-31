"""Byte-first module intent, final atomic graph settlement, explicit late cleanup."""

import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.audit import services as audit

from . import purge_storage
from .models import Makerspace, ModulePurgeReceipt
from .module_purge_accounting import freeze_charges, settle
from .module_purge_graph import snapshot
from .module_purge_namespaces import clauses, enumerate_closure
from .module_purge_receipt_authority import validate_receipt
from .module_purge_references import assert_unreferenced
from .module_purge_state import current_authority, require_source
from .purge_cleanup import synchronous_cleanup
from .purge_intent import require_actor, storage_origins
from .purge_locks import assert_recovery_allowed, purge_boundary


def prepare_intent(space, plan, actor, s3, verify):
    require_source(space)
    state = assert_recovery_allowed(space.pk)
    digest, sites, bindings, facts = snapshot(space, plan)
    exact = set()
    for label, pk, field, kind, key in sites:
        # Final/staging closure is exact, including explicitly typed legacy keys.
        if key.startswith("staging/"):
            raise ValidationError("An accepted module holder names a staging key.")
        exact.update({(kind, key), (kind, f"staging/{key}")})
    receipt = ModulePurgeReceipt(
        source_makerspace_id=space.pk, source_public_code=space.public_code,
        source_created_at=space.created_at, module_key=plan.key,
        auth_generation=state.auth_generation, storage_origins=storage_origins(),
        exact_keys=[list(pair) for pair in sorted(exact)], namespace_clauses=clauses(plan.key, space.pk),
        holder_sites=sites, rollback_bindings=bindings, charge_obligations=[],
        graph_digest=digest, intent_created_at=timezone.now(),
    )
    validate_receipt(receipt)
    closure = enumerate_closure(receipt, s3, verify)
    assert_unreferenced(closure, sites)
    # Prove strict listing of exact legacy keys before intent too, without deletion.
    for kind, key in sorted(closure):
        verify()
        purge_storage.list_versions(s3, purge_storage.bucket_name(kind), key)
    receipt.charge_obligations = freeze_charges(sites, facts, bindings, s3, verify)
    validate_receipt(receipt)
    with transaction.atomic(durable=True):
        locked = Makerspace._base_manager.select_for_update().get(pk=space.pk)
        current_authority(receipt, space=locked)
        verify()
        if snapshot(locked, plan)[0] != receipt.graph_digest:
            raise ValidationError("Module graph changed before intent; nothing was purged.")
        receipt.save(force_insert=True)
        audit.record(actor, "makerspace.module_purge_started", meta=_meta(receipt))
    return receipt


def execute_cleanup(receipt, actor, verify):
    """Caller retains the OUTER all-tenant exclusive proof across every phase."""
    from .module_purge import _purge
    from .module_purge_plans import BY_KEY

    validate_receipt(receipt)
    if connection.in_atomic_block:
        raise ValidationError("Module byte cleanup requires a non-transactional caller.")
    try:
        space = current_authority(receipt)
        pending = receipt.graph_purged_at is None
        plan = BY_KEY[receipt.module_key]
        if pending and snapshot(space, plan)[0] != receipt.graph_digest:
            raise ValidationError("Frozen module graph changed; cleanup authority cannot be rebound.")
        s3 = purge_storage.client()
        closure = enumerate_closure(receipt, s3, verify)
        assert_unreferenced(closure, receipt.holder_sites if pending else ())
        verify()
        current_authority(receipt)
        purge_storage.delete_and_verify(s3, closure, verify)
        # Re-enumerate the positive namespaces too: report late arrivals as
        # unconfirmed instead of claiming a permanently empty bucket.
        late = enumerate_closure(receipt, s3, verify)
        for kind, key in sorted(late):
            verify()
            if any(row["Key"] == key for row in purge_storage.list_versions(s3, purge_storage.bucket_name(kind), key)):
                raise ValidationError("A late object arrived; retry cleanup from the retained receipt.")
        counts = {}
        with synchronous_cleanup(space.pk, verify=verify), transaction.atomic(durable=True):
            locked = Makerspace._base_manager.select_for_update().get(pk=space.pk)
            fresh = ModulePurgeReceipt.objects.select_for_update().get(pk=receipt.pk)
            current_authority(fresh, space=locked)
            if fresh.graph_purged_at != receipt.graph_purged_at:
                raise ValidationError("Module graph checkpoint changed; retry from current authority.")
            verify()
            if pending:
                if snapshot(locked, plan)[0] != fresh.graph_digest:
                    raise ValidationError("Frozen module graph changed; final graph commit refused.")
                with connection.cursor() as cursor:
                    from django.conf import settings

                    if settings.MANAGED_POSTGRES:
                        cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
                    else:
                        cursor.execute("SET LOCAL session_replication_role = 'replica'")
                    counts = _purge(locked, plan, cursor, verify=verify)
                settle(locked, fresh, verify=verify)
                fresh.graph_purged_at = timezone.now()
            fresh.last_attempt_at = fresh.last_verified_at = timezone.now()
            fresh.last_error_code = ""
            fresh.save(update_fields=["graph_purged_at", "last_attempt_at", "last_verified_at", "last_error_code"])
            audit.record(actor, "makerspace.module_purged" if pending else "makerspace.module_purge_receipt_checked",
                         target=fresh, meta={**_meta(fresh), "counts": counts, "verified": True})
        return fresh, counts
    except Exception:
        _record_failure(receipt, actor)
        raise


def retry_cleanup(receipt_id, actor):
    require_actor(actor)
    if not isinstance(receipt_id, uuid.UUID):
        raise ValidationError("A canonical receipt UUID is required.")
    receipt = ModulePurgeReceipt.objects.get(pk=receipt_id)
    validate_receipt(receipt)
    with purge_boundary(receipt.source_makerspace_id, all_tenants=True) as verify:
        actor = get_user_model().objects.get(pk=actor.pk)
        require_actor(actor)
        receipt.refresh_from_db()
        space = current_authority(receipt)
        # This new service is the web retry surface. The CLI retains its separate
        # explicit operator contract through purge_module, without a boolean bypass.
        if not space.superadmin_access_enabled:
            raise ValidationError("Hidden tenant custody refuses web module cleanup.")
        from apps.accounts import rbac

        if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, space.pk):
            raise ValidationError("Current tenant authority refuses module cleanup.")
        return execute_cleanup(receipt, actor, verify)[0]


def _record_failure(receipt, actor):
    with transaction.atomic():
        current = ModulePurgeReceipt.objects.select_for_update().get(pk=receipt.pk)
        current.last_attempt_at = timezone.now()
        current.last_error_code = "cleanup_unconfirmed"
        current.save(update_fields=["last_attempt_at", "last_error_code"])
        audit.record(actor, "makerspace.module_purge_receipt_checked", target=current,
                     meta={**_meta(current), "verified": False, "last_error_code": "cleanup_unconfirmed"})


def _meta(receipt):
    return {"receipt_id": str(receipt.pk), "makerspace_id": receipt.source_makerspace_id,
            "module": receipt.module_key}
