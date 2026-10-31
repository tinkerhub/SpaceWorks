from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.core.exceptions import ValidationError
from apps.tenant_migration.gate_runtime import (
    _exclusive_boundary_connection, assert_boundary_held, fanout_tenant_write,
)
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.backup.not_restored import TenantNotRestored
from apps.makerspaces.module_purge_state import assert_no_inprogress

from apps.bookings.models import BookableSpace
from apps.data_export import storage as export_storage
from apps.data_export.models import DataExportJob
from apps.events.models import Event, EventAttendanceCertificate, EventSeries
from apps.evidence import storage as evidence_storage
from apps.evidence.models import EvidenceObjectRetentionState, EvidencePhoto
from apps.evidence.quota import proven_charge_bytes
from apps.document_storage_quota import proven_document_charge
from apps.inventory import public_image_storage
from apps.inventory.models import InventoryProduct
from apps.machines import storage as machine_storage
from apps.machines.models import Machine, MachineDocument, ServiceRequestFile
from apps.maintenance import storage as maintenance_storage
from apps.maintenance.models import MaintenanceLogDocument
from apps.makerspaces.models import MemberProfile, MemberProject
from apps.makerspaces.servability import servable_queryset
from apps.procurement import storage as procurement_storage
from apps.procurement.models import ToBuyReceipt
from apps.warranty import storage as warranty_storage
from apps.warranty.models import WarrantyDocument
from apps.backup.models import DeploymentRecoveryState, RestoreRollbackObject


class StorageReadError(Exception):
    pass


class Command(BaseCommand):
    help = "Recompute per-makerspace managed object-storage usage from canonical records."

    def add_arguments(self, parser):
        parser.add_argument("makerspace", nargs="?", help="Optional makerspace slug or numeric ID.")

    def handle(self, *args, **options):
        selector = options["makerspace"]
        makerspaces = servable_queryset()
        if selector:
            lookup = Q(slug=selector)
            if selector.isdigit():
                lookup |= Q(pk=int(selector))
            makerspaces = makerspaces.filter(lookup)
            if not makerspaces.exists():
                raise CommandError(f"Makerspace {selector!r} was not found.")
        for makerspace in makerspaces.order_by("pk"):
            counts = {}
            with fanout_tenant_write(
                makerspace.pk, operation="recompute_storage", counts=counts, exclusive=True,
            ) as allowed:
                if not allowed:
                    self.stdout.write(self.style.WARNING(f"{makerspace.slug}: source closed; usage unchanged."))
                    continue
                try:
                    assert_no_inprogress([makerspace.pk])
                except ValidationError:
                    self.stdout.write(self.style.WARNING(f"{makerspace.slug}: module purge pending; usage unchanged."))
                    continue
                try:
                    self._recompute(makerspace)
                except (SourceMigrationGateClosed, TenantNotRestored, ValidationError) as exc:
                    self.stdout.write(self.style.WARNING(f"{makerspace.slug}: reconciliation refused; usage unchanged: {exc}"))

    def _recompute(self, makerspace):
        # Reload after draining writers: the loop's instance can hold old image keys.
        makerspace = self._admit(makerspace.pk)
        try:
            values = {
                "evidence": self._sum_evidence(makerspace),
                "print_files": self._sum(ServiceRequestFile.objects.filter(makerspace=makerspace).values_list("object_key", "size_bytes"), machine_storage.object_size, True),
                "public_images": self._sum(((key, None) for key in self._public_image_keys(makerspace)), public_image_storage.object_size),
                "machine_documents": self._sum(((key, None) for key in MachineDocument.objects.filter(machine__makerspace=makerspace).values_list("object_key", flat=True)), machine_storage.object_size),
                "warranty_documents": self._sum_documents(WarrantyDocument.objects.filter(warranty__makerspace=makerspace).select_related("warranty"), makerspace.pk, warranty_storage.object_size),
                "procurement_receipts": self._sum_documents(ToBuyReceipt.objects.filter(to_buy_item__makerspace=makerspace).select_related("to_buy_item"), makerspace.pk, procurement_storage.object_size),
                # Charged on upload by `maintenance/services_documents.py` and collected by
                # both the makerspace purge and the `maintenance` module purge plan, but
                # absent here -- so this command, which is the AUTHORITATIVE reconciler,
                # wrote a total omitting every maintenance document and silently lowered a
                # space's recorded usage. Reached through the log's machine; the rows carry
                # `size_bytes`, so a HEAD that cannot see the object falls back to it.
                "maintenance_documents": self._sum(MaintenanceLogDocument.objects.filter(log__machine__makerspace=makerspace).values_list("object_key", "size_bytes"), maintenance_storage.object_size, True),
                "data_exports": self._sum(
                    DataExportJob.objects.filter(
                        makerspace=makerspace,
                        status=DataExportJob.Status.AVAILABLE,
                    ).values_list("object_key", "accounted_size_bytes"),
                    export_storage.object_size,
                    True,
                ),
                "restore_rollback_objects": sum(
                    RestoreRollbackObject.objects.filter(makerspace=makerspace)
                    .values_list("size_bytes", flat=True)
                ),
                # Activation charges the immutable rendered size. Revocation keeps
                # those bytes; a revoked render that never activated has no charge.
                "event_certificates": sum(
                    EventAttendanceCertificate.objects.filter(
                        registration__event__makerspace=makerspace,
                        status__in=(
                            EventAttendanceCertificate.Status.ACTIVE,
                            EventAttendanceCertificate.Status.REVOKED,
                        ),
                        rendered_at__isnull=False,
                        size_bytes__isnull=False,
                    ).values_list("size_bytes", flat=True)
                ),
            }
        except StorageReadError as exc:
            self.stdout.write(self.style.WARNING(f"{makerspace.slug}: usage left unchanged due to storage read error for {exc}."))
            return
        total = sum(values.values())
        self._commit(makerspace.pk, total)
        self.stdout.write(self.style.SUCCESS(f"{makerspace.slug}: total={total} bytes"))

    @staticmethod
    def _admit(makerspace_id):
        assert_boundary_held(makerspace_id)
        assert_no_inprogress([makerspace_id])
        if not DeploymentRecoveryState.objects.filter(
            pk=1, mode=DeploymentRecoveryState.Mode.NORMAL,
        ).exists():
            raise ValidationError("Deployment recovery state refuses storage reconciliation.")
        makerspace = servable_queryset().filter(pk=makerspace_id).first()
        if makerspace is None:
            raise SourceMigrationGateClosed("This makerspace is no longer servable.")
        return makerspace

    def _commit(self, makerspace_id, total):
        self._admit(makerspace_id)
        lock_connection = _exclusive_boundary_connection(makerspace_id)
        # The setter and transaction advisory lock MUST share this backend. An
        # ORM update on the application connection would reopen a lock-loss gap.
        with lock_connection.cursor() as cursor:
            cursor.execute(
                """UPDATE makerspaces_makerspace SET storage_bytes_used = %s
                   WHERE id = %s AND EXISTS (
                       SELECT 1 FROM backup_deploymentrecoverystate
                       WHERE id = 1 AND mode = 'normal'
                   )""",
                [total, makerspace_id],
            )
            if cursor.rowcount != 1:
                raise CommandError("Storage counter admission changed; fresh rescan required.")
        try:
            lock_connection.commit()
        except Exception as exc:
            raise CommandError(
                "Storage counter commit outcome uncertain; fresh rescan required."
            ) from exc

    @staticmethod
    def _sum_evidence(makerspace):
        total = 0
        photos = EvidencePhoto.objects.filter(makerspace=makerspace).exclude(
            object_retention_state__status=EvidenceObjectRetentionState.Status.EXPIRED
        ).select_related("upload_finalization")
        for photo in photos.iterator():
            try:
                observed = evidence_storage.object_size(photo.object_key)
            except Exception as exc:
                raise StorageReadError(photo.object_key) from exc
            charged = proven_charge_bytes(photo, getattr(photo, "upload_finalization", None))
            # Preserve a proven debit until terminal expiry can credit it, even if
            # HEAD sees missing/different bytes. Declared photo size is untrusted.
            total += charged or observed or 0
        return total

    @staticmethod
    def _sum_documents(rows, makerspace_id, object_size):
        total = 0
        for document in rows.iterator():
            if not document.object_key:
                continue
            try:
                observed = object_size(document.object_key)
            except Exception as exc:
                raise StorageReadError(document.object_key) from exc
            charge = proven_document_charge(document, makerspace_id=makerspace_id)
            # An unreleased local debit survives hidden versions / changed HEAD.
            # Legacy rows still contribute only their observed object size.
            total += charge.size_bytes if charge is not None else (observed or 0)
        return total

    @staticmethod
    def _sum(rows, object_size, fallback=False):
        total = 0
        for key, recorded in rows:
            if not key:
                continue
            try:
                observed = object_size(key)
            except Exception as exc:
                raise StorageReadError(key) from exc
            total += observed if observed is not None else ((recorded or 0) if fallback else 0)
        return total

    @staticmethod
    def _public_image_keys(makerspace):
        keys = {makerspace.logo_key, makerspace.cover_image_key}
        keys.update(InventoryProduct.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        keys.update(Machine.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        keys.update(Event.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        # An occurrence may inherit its series key: the shared set counts it once.
        keys.update(EventSeries.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        # BookableSpace images are charged on upload and collected by lifecycle purge,
        # but were missing here, so the reconciler wrote a total that omitted them and
        # silently lowered a space's recorded usage. apps/bookings/storage.py is a thin
        # wrapper over public_image_storage, so these live in the same bucket.
        keys.update(BookableSpace.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        # Member avatars and project images, reached through the membership: the profile
        # carries no makerspace column, being hung off MakerspaceMembership.
        keys.update(
            MemberProfile.objects.filter(membership__makerspace=makerspace).values_list(
                "avatar_key", flat=True
            )
        )
        keys.update(
            MemberProject.objects.filter(
                profile__membership__makerspace=makerspace
            ).values_list("image_key", flat=True)
        )
        return {key for key in keys if key}
