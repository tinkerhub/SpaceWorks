"""Explicit cleanup only: inert receipts never schedule or replay deletion."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup.object_reference_capture import build_object_ownership_plan

from .models import Makerspace, PurgeReceipt
from .purge_intent import require_actor, storage_origins
from .purge_locks import assert_recovery_allowed, purge_boundary
from .purge_object_closure import STAGED_PRIVATE_MODELS, _aliases, _safe_key
from .purge_object_references import coordination_references
from .purge_receipt_authority import validate_receipt
from . import purge_storage


def prepare_receipt(space, intent, closure, prefixes):
    state = assert_recovery_allowed(space.pk)
    receipt = PurgeReceipt(
        source_makerspace_id=space.pk,
        source_purge_started_at=space.purge_started_at,
        auth_generation=state.auth_generation,
        storage_origins=intent["storage_origins"],
        exact_keys=[list(pair) for pair in sorted(closure)],
        namespace_prefixes=[list(pair) for pair in prefixes],
        graph_purged_at=timezone.now(),
    )
    validate_receipt(receipt)
    return receipt


def _require_current_authority(receipt):
    validate_receipt(receipt)
    state = assert_recovery_allowed()
    if receipt.invalidated_at is not None or receipt.auth_generation != state.auth_generation:
        raise ValidationError("This receipt was invalidated by recovery or belongs to another root generation.")
    if Makerspace._base_manager.filter(pk=receipt.source_makerspace_id).exists():
        raise ValidationError("The original makerspace ID exists; receipt cleanup is refused.")
    if receipt.storage_origins != storage_origins():
        raise ValidationError("Physical storage origins changed; receipt cleanup is refused.")


def _assert_unreferenced(closure):
    physical = {(purge_storage.bucket_name(kind), key) for kind, key in closure}
    plan = build_object_ownership_plan([])
    for ref in plan.references:
        staged = ref.site.split(":", 1)[0] in STAGED_PRIVATE_MODELS
        for kind, key in _aliases(ref.bucket_kind, ref.object_key, staged=staged):
            if (purge_storage.bucket_name(kind), key) in physical:
                raise ValidationError("A current domain or retained object reference prevents cleanup.")
    for ref in coordination_references():
        for kind, key in _aliases(ref.kind, ref.key, staged=ref.site.startswith("tenant_migration.TenantImportObject:")):
            if (purge_storage.bucket_name(kind), key) in physical:
                raise ValidationError("A current coordination reference prevents cleanup.")


def retry_cleanup(receipt_id, actor):
    require_actor(actor)
    receipt = PurgeReceipt.objects.get(pk=receipt_id)
    # Malformed/raw-restored authority must fail before its source ID becomes a
    # signed-int32 PostgreSQL advisory-lock key. Recheck fresh authority inside.
    validate_receipt(receipt)
    with purge_boundary(receipt.source_makerspace_id, all_tenants=True) as verify:
        from django.contrib.auth import get_user_model

        require_actor(get_user_model().objects.get(pk=actor.pk))
        receipt.refresh_from_db()
        try:
            _require_current_authority(receipt)
            closure = set(validate_receipt(receipt))
            s3 = purge_storage.client()
            for kind, prefix in receipt.namespace_prefixes:
                verify()
                closure.update((kind, _safe_key(row["Key"])) for row in
                               purge_storage.list_versions(s3, purge_storage.bucket_name(kind), prefix))
            # Validate the expanded late-upload closure BEFORE any deletion too.
            receipt.exact_keys, frozen_keys = [list(pair) for pair in sorted(closure)], receipt.exact_keys
            try:
                validate_receipt(receipt)
            finally:
                receipt.exact_keys = frozen_keys
            _assert_unreferenced(closure)
            verify()
            _require_current_authority(receipt)
            purge_storage.delete_and_verify(s3, closure, verify)
            verify()
        except Exception:
            _record_attempt(receipt, actor, verified=False)
            raise
        _record_attempt(receipt, actor, verified=True)
        return receipt


def _record_attempt(receipt, actor, *, verified):
    # Only safe status is mutable; the original locators survive every empty scan.
    now = timezone.now()
    with transaction.atomic():
        receipt.last_attempt_at = now
        receipt.last_error_code = "" if verified else "cleanup_unconfirmed"
        fields = ["last_attempt_at", "last_error_code"]
        if verified:
            receipt.last_verified_at = now
            fields.append("last_verified_at")
        receipt.save(update_fields=fields)
        audit.record(actor, "makerspace.purge_receipt_checked", target=receipt, meta={
            "receipt_id": str(receipt.pk), "verified": verified,
            "last_error_code": receipt.last_error_code,
        })
