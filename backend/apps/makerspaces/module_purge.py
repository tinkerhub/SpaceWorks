"""Explicit CLI module purge: retained byte-first authority under exclusive source locks."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.makerspaces.module_purge_plans import BY_KEY, NOT_SEPARABLE, PLANS
from apps.makerspaces.module_registry import BY_KEY as MODULE_BY_KEY
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_purge_receipt_authority import validate_receipt
from apps.makerspaces.module_purge_state import require_source, validate_maker_id
from apps.makerspaces.purge_intent import require_actor
from apps.makerspaces.purge_locks import purge_boundary


def purgeable_modules():
    return [{"key": plan.key, "summary": plan.summary} for plan in PLANS]


def purge_module(makerspace, key, actor):
    """Return the durable receipt and graph counts; completed calls only clean bytes."""
    from . import purge_storage
    from .module_purge_receipts import execute_cleanup, prepare_intent

    require_actor(actor)
    validate_maker_id(makerspace.pk)
    _resolve(makerspace, key, actor)
    # Validate raw persisted authority before it can become a lock key.
    existing = ModulePurgeReceipt.objects.filter(
        source_makerspace_id=makerspace.pk, module_key=key, invalidated_at__isnull=True,
    ).first()
    if existing is not None:
        validate_receipt(existing)
    with purge_boundary(makerspace.pk, all_tenants=True) as verify:
        actor = get_user_model().objects.get(pk=actor.pk)
        require_actor(actor)
        space = Makerspace._base_manager.get(pk=makerspace.pk)
        if (space.public_code != makerspace.public_code or space.created_at != makerspace.created_at):
            raise ValidationError("The makerspace incarnation changed; module purge refused.")
        plan = _resolve(space, key, actor)
        require_source(space)
        receipt = ModulePurgeReceipt.objects.filter(
            source_makerspace_id=space.pk, module_key=key, invalidated_at__isnull=True,
        ).first()
        if receipt is None:
            receipt = prepare_intent(space, plan, actor, purge_storage.client(), verify)
        return execute_cleanup(receipt, actor, verify)


def _resolve(makerspace, key, actor):
    require_actor(actor)
    if not isinstance(key, str) or not 0 < len(key) <= 40:
        raise ValidationError("A bounded registered module key is required.")
    plan = BY_KEY.get(key)
    if plan is None:
        reason = NOT_SEPARABLE.get(key)
        if reason:
            raise ValidationError(f"{key} cannot be purged on its own. {reason}")
        if key in MODULE_BY_KEY:
            raise ValidationError(f"{key} stores no data of its own, so there is nothing to purge.")
        raise ValidationError(f"Unknown module {key!r}.")
    if key in (makerspace.enabled_modules or []):
        raise ValidationError(
            f"{key} is still installed. Uninstall it first -- purging is a separate, "
            "irreversible step."
        )
    return plan


def _purge(makerspace, plan, cursor, *, verify):
    counts = {}
    # Payments are deliberately NOT deleted here, by any plan. Switching a module off and
    # then purging its rows is not a reason to destroy the financial record of money that
    # really changed hands -- a receipt must stay visible and a pending charge payable. They
    # do become generic-keyed references to a vanished subject, which is why `Payment`
    # snapshots `subject_label` at creation and `clean()` tolerates a missing subject on an
    # otherwise-unchanged row. The whole-makerspace `lifecycle.purge` still deletes them:
    # `Payment.makerspace` is PROTECT, so they cannot outlive their makerspace.
    # Blind-index rows have no FK to their source row, so nothing else deletes them.
    # They hold keyed HMACs of PII: leaving them behind is a real leak, not untidiness.
    if plan.pii_labels:
        from apps.encryption.models import PiiBlindIndex

        deleted = PiiBlindIndex.objects.filter(
            makerspace=makerspace, model_label__in=plan.pii_labels
        ).delete()[0]
        if deleted:
            counts["pii_blind_index"] = deleted
    verify()
    outcome = (plan.delete(makerspace, cursor, guard=None) if plan.key in {"procurement", "membership"}
               else plan.delete(makerspace, cursor))
    counts.update(outcome)
    # Derived facts follow their source module during an explicit destructive purge.
    # Automatic retention never reaches this path; preserving rollups there is the
    # historical-report guarantee. A module purge is different: retaining its derived
    # tenant data would violate the operator's explicit deletion boundary.
    from apps.operations.models import ReportMetricRollup, ReportRollupCursor

    rollups = ReportMetricRollup.objects.filter(
        makerspace=makerspace, source_module=plan.key
    ).delete()[0]
    cursors = ReportRollupCursor.objects.filter(
        makerspace=makerspace, source_module=plan.key
    ).delete()[0]
    if rollups:
        counts["report_metric_rollups"] = rollups
    if cursors:
        counts["report_rollup_cursors"] = cursors
    # Read the attribute directly. Every collector returns a ``PurgeResult``, so a
    # ``getattr`` default would only ever hide a future collector that forgot to report
    # its labels -- and the symptom of that is provenance silently outliving the rows it
    # describes, which is exactly what this deletion exists to prevent.
    deleted = _delete_external_references(makerspace, outcome.model_labels)
    if deleted:
        counts["external_tenant_references"] = deleted
    return counts


def _delete_external_references(makerspace, target_model_labels):
    if not target_model_labels:
        return 0
    # Imported unguarded: a tombstone removes an app's *surfaces*, never its models --
    # the rows and migrations must stay -- so this package is always importable.
    from apps.tenant_migration.models import ExternalTenantReference

    return ExternalTenantReference.objects.filter(
        makerspace=makerspace,
        target_model_label__in=target_model_labels,
    ).delete()[0]
