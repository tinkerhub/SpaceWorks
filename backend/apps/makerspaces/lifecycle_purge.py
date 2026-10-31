from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q

from apps.audit import services as audit


def purge(makerspace, actor):
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from apps.makerspaces import purge_storage
    from apps.makerspaces.purge_cleanup import synchronous_cleanup
    from apps.makerspaces.purge_intent import (
        PurgePending, commit_intent, load_intent, require_actor, require_purgeable,
    )
    from apps.makerspaces.purge_locks import assert_recovery_allowed, purge_boundary
    from apps.makerspaces.purge_object_closure import freeze_closure

    require_actor(actor)
    with purge_boundary(makerspace.pk, all_tenants=True) as verify_boundary:
        from django.contrib.auth import get_user_model

        actor = get_user_model().objects.get(pk=actor.pk)
        require_actor(actor)
        frozen = makerspace.__class__.objects.get(pk=makerspace.pk)
        require_purgeable(frozen)
        if frozen.slug != makerspace.slug:
            raise ValidationError("Makerspace slug changed; confirm the current slug before purge.")
        s3 = purge_storage.client()
        # Refuse known unsupported version listing before committing irreversible intent.
        for kind in ("private", "public_image"):
            purge_storage.list_versions(s3, purge_storage.bucket_name(kind), f"evidence/{makerspace.pk}/")
        frozen, intent = commit_intent(makerspace.pk, actor, expected_slug=makerspace.slug)
        not_before = parse_datetime(intent["not_before"])
        if timezone.now() < not_before:
            raise PurgePending(not_before)
        assert_recovery_allowed(frozen.pk)
        load_intent(frozen)
        verify_boundary()
        from apps.makerspaces.module_purge_handoff import collect_handoff, invalidate_handoff

        module_receipts, module_keys = collect_handoff(frozen, s3, verify_boundary)
        closure, prefixes = freeze_closure(frozen, s3, verify_boundary, extra_keys=module_keys)
        from apps.makerspaces.purge_receipts import prepare_receipt
        from apps.makerspaces.purge_import_archives import delete_import_archives

        receipt = prepare_receipt(frozen, intent, closure, prefixes)
        # The host/source boundary freezes publication across these phases. Keep
        # storage and filesystem I/O outside application transactions and row locks.
        purge_storage.delete_and_verify(s3, closure, verify_boundary)
        delete_import_archives(frozen)
        verify_boundary()
        receipt.last_verified_at = timezone.now()
        with synchronous_cleanup(frozen.pk, verify=verify_boundary), transaction.atomic(durable=True):
            locked = makerspace.__class__.objects.select_for_update().get(pk=makerspace.pk)
            require_purgeable(locked)
            assert_recovery_allowed(locked.pk)
            if (locked.slug != frozen.slug
                    or locked.purge_started_at != frozen.purge_started_at
                    or load_intent(locked) != intent):
                raise ValidationError("Purge authority changed; graph deletion is refused.")
            verify_boundary()
            meta = {**_audit_meta(locked), "purge_started_at": intent["purge_started_at"],
                    "receipt_id": str(receipt.pk)}
            invalidate_handoff(locked, module_receipts)
            _delete_object_graph(locked)
            receipt.graph_purged_at = timezone.now()
            receipt.save(force_insert=True)
            audit.record(actor, "makerspace.purged", meta=meta)
        return receipt


def _audit_meta(makerspace):
    return {
        "makerspace_id": makerspace.pk,
        "name": makerspace.name,
        "slug": makerspace.slug,
    }


def _delete_object_graph(makerspace):
    from apps.backup.models import RestoreRollbackObject
    from apps.apiclients.models import ApiClient, ApiKeyRequest
    from apps.accounts.models_devices import (
        DeviceAttestationChallenge,
        DeviceGrant,
        DeviceRefreshFamily,
        DeviceRefreshToken,
        NativeAppRegistration,
    )
    from apps.audit.models import (
        AuditBatch,
        AuditBatchLeaf,
        AuditLog,
        AuditSigningKey,
        AuditSigningKeyRotation,
        AuditSigningKeyRotationEvent,
    )
    from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
    from apps.evidence.models import EvidencePhoto, EvidenceRetentionPolicy
    from apps.events.models import (
        Event,
        EventAttendanceCertificate,
        EventCheckInEvent,
        EventCheckInStationCredential,
        EventCollaborator,
        EventFeedbackResponse,
        EventFeedbackSurvey,
        EventOrganizer,
        EventRegistration,
        EventSeries,
        EventSeriesCollaborator,
    )
    from apps.hardware_requests.models import HardwareRequest
    from apps.hardware_requests.models import PublicToolLoan, RequesterAccountability
    from apps.hardware_requests.models import ReturnEvent
    from apps.hardware_requests.asset_link_models import HardwareRequestItemAsset
    from apps.integrations.models import EmailTemplate, MachineTypeEmailTemplate
    from apps.inventory.models import Category, InventoryAsset, InventoryProduct
    from apps.makerspaces.models import MakerspaceMembership
    from apps.operations.models import InventoryAdjustment, QrPrintBatch
    from apps.operations.models import StocktakeSession, StockTransfer
    from apps.organizations.models import OrganizationMakerspace
    from apps.machines.models import Machine, MachineType, MakerspaceMachineTypePricing
    from apps.machines.service_lifecycle import delete_for_makerspace
    from apps.payments.models import Payment, ProcessedStripeEvent
    from apps.tenant_migration.models import ExternalTenantReference, TenantImportJob

    with connection.cursor() as cursor:
        # Transaction-local trigger suppression resets on commit, rollback or disconnect.
        if settings.MANAGED_POSTGRES:
            cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        else:
            cursor.execute("SET LOCAL session_replication_role = 'replica'")

        QrPrintBatch.objects.filter(makerspace=makerspace).delete()
        StockTransfer.objects.filter(
            Q(makerspace=makerspace)
            | Q(source_makerspace=makerspace)
            | Q(destination_makerspace=makerspace)
            | Q(source_container__makerspace=makerspace)
            | Q(destination_container__makerspace=makerspace)
            | Q(lines__product__makerspace=makerspace)
            | Q(lines__asset__makerspace=makerspace)
        ).distinct().delete()
        StocktakeSession.objects.filter(makerspace=makerspace).delete()
        InventoryAdjustment.objects.filter(makerspace=makerspace).delete()
        # Organizations are platform-level and may be shared by other tenants. Remove
        # only this tenant's through rows; never traverse from the organization side.
        OrganizationMakerspace.objects.filter(makerspace=makerspace).delete()

        delete_for_makerspace(makerspace, cursor)

        HardwareRequestItemAsset.objects.filter(request_item__request__makerspace=makerspace).delete()
        BoxScan.objects.filter(makerspace=makerspace).delete()
        QrScanEvent.objects.filter(makerspace=makerspace).delete()
        PublicToolLoan.objects.filter(makerspace=makerspace).delete()
        RequesterAccountability.objects.filter(makerspace=makerspace).delete()
        ReturnEvent.objects.filter(makerspace=makerspace).delete()
        HardwareRequest.objects.filter(makerspace=makerspace).delete()
        EvidencePhoto.objects.filter(makerspace=makerspace).delete()
        EvidenceRetentionPolicy.objects.filter(makerspace=makerspace).delete()
        QrCode.objects.filter(makerspace=makerspace).delete()

        # Machines + their maintenance/children/consumables cascade from the Machine
        # delete (triggers suspended above). Do this BEFORE InventoryProduct because
        # MachineConsumable.product is PROTECT; and clear the makerspace-scoped custom
        # MachineType (PROTECT makerspace FK) before makerspace.delete().
        Machine.objects.filter(makerspace=makerspace).delete()
        MakerspaceMachineTypePricing.objects.filter(makerspace=makerspace).delete()
        MachineType.objects.filter(makerspace=makerspace).delete()

        InventoryAsset.objects.filter(makerspace=makerspace).delete()
        InventoryProduct.objects.filter(makerspace=makerspace).delete()
        Category.objects.filter(makerspace=makerspace).delete()
        Box.objects.filter(makerspace=makerspace).delete()

        EmailTemplate.objects.filter(makerspace=makerspace).delete()
        MachineTypeEmailTemplate.objects.filter(makerspace=makerspace).delete()
        ApiClient.objects.filter(makerspace=makerspace).delete()
        ApiKeyRequest.objects.filter(makerspace=makerspace).delete()

        # Native app registrations are makerspace-scoped, but DeviceGrant.registration and
        # DeviceAttestationChallenge.registration are PROTECT, so letting the makerspace
        # CASCADE into them raises ProtectedError and the whole purge fails -- the same
        # shape as MachineConsumable.product below. Clear the dependent authentication
        # rows first. Grants are deliberately destroyed: they are authority to act inside
        # a space that no longer exists.
        registrations = NativeAppRegistration.objects.filter(makerspace=makerspace)
        DeviceRefreshToken.objects.filter(
            family__grant__registration__in=registrations
        ).delete()
        DeviceRefreshFamily.objects.filter(
            grant__registration__in=registrations
        ).delete()
        DeviceGrant.objects.filter(registration__in=registrations).delete()
        DeviceAttestationChallenge.objects.filter(
            registration__in=registrations
        ).delete()
        registrations.delete()
        MakerspaceMembership.objects.filter(makerspace=makerspace).delete()
        # AuditBatchLeaf.audit_log PROTECTs the audit rows deleted just below, and the
        # batch FK PROTECTs the makerspace itself, so both must go first. Attestation is
        # deployment-local state about rows that are being destroyed anyway.
        AuditBatchLeaf.objects.filter(batch__makerspace=makerspace).delete()
        AuditBatch.objects.filter(makerspace=makerspace).delete()
        AuditSigningKeyRotationEvent.objects.filter(
            rotation__makerspace=makerspace
        ).delete()
        # Break the row-local pending claim before deleting immutable transitions.
        AuditSigningKey.objects.filter(makerspace=makerspace).update(
            pending_rotation=None
        )
        AuditSigningKeyRotation.objects.filter(makerspace=makerspace).delete()
        AuditLog.objects.filter(makerspace=makerspace).delete()
        Payment.objects.filter(makerspace=makerspace).delete()
        ProcessedStripeEvent.objects.filter(makerspace=makerspace).delete()
        # An elsewhere-hosted registration can reference this space's waiver. Clear all
        # three evidence fields or PROTECT would raise ProtectedError in the final cascade.
        EventRegistration.objects.filter(host_waiver__makerspace=makerspace).update(
            host_waiver=None, host_waiver_accepted_at=None,
            host_waiver_version_accepted=None,
        )
        # Organizer attribution is owned by the hosted event, never by whichever
        # makerspaces happen to be linked to its deployment-global organization.
        EventOrganizer.objects.filter(event__makerspace=makerspace).delete()
        EventAttendanceCertificate.objects.filter(
            registration__event__makerspace=makerspace
        ).delete()
        EventFeedbackResponse.objects.filter(
            survey__event__makerspace=makerspace
        ).delete()
        EventFeedbackSurvey.objects.filter(event__makerspace=makerspace).delete()
        EventCheckInStationCredential.objects.filter(
            event__makerspace=makerspace
        ).delete()
        EventCheckInEvent.objects.filter(makerspace=makerspace).delete()
        # Registrations otherwise survive until the final makerspace cascade. Delete
        # hosted rows explicitly so any PROTECT FK they gain cannot fail that cascade;
        # collaborator provenance must not remove another host's registration.
        EventRegistration.objects.filter(event__makerspace=makerspace).delete()
        EventCollaborator.objects.filter(
            source_series_collaboration__makerspace=makerspace
        ).exclude(event__makerspace=makerspace).delete()
        EventSeriesCollaborator.objects.filter(makerspace=makerspace).delete()
        Event.objects.filter(makerspace=makerspace).delete()
        EventSeries.objects.filter(makerspace=makerspace).delete()
        # Encryption key rows carry a PROTECT FK + a no-delete ORM guard/trigger, so
        # raw-delete them inside this authorized purge context (session_replication_role
        # =replica self-host, or app.allow_immutable_delete GUC managed) before the
        # parent delete; otherwise the PROTECT FK would block teardown once a makerspace
        # has ever had scoped-PII encryption enabled.
        cursor.execute(
            "DELETE FROM encryption_makerspaceencryptionkey WHERE makerspace_id = %s",
            [makerspace.id],
        )
        cursor.execute(
            "DELETE FROM encryption_piimakerspacewritefence WHERE makerspace_id = %s",
            [makerspace.id],
        )
        RestoreRollbackObject.objects.filter(makerspace=makerspace).delete()
        # TenantImportJob deliberately uses SET_NULL so an ordinary tenant deletion is
        # possible. Purge must delete the jobs first or that safety valve would strand
        # target-side identity decisions after their tenant disappeared.
        TenantImportJob.objects.filter(target_makerspace=makerspace).delete()
        # Generic provenance has no FK to the source/anchor rows it describes, so
        # delete it explicitly rather than relying on the makerspace CASCADE.
        ExternalTenantReference.objects.filter(makerspace=makerspace).delete()
        makerspace.delete()
