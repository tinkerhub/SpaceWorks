import hashlib
import uuid

import pytest
from django.db import DatabaseError, models, transaction
from django.utils import timezone

from apps.backup.models import B1ReservationEntry
from apps.backup.compound_restore_state import install_manifest_enforcement
from tests.backup.x07_installation_test_helpers import prepared


DIGEST = "d" * 64


class CommitmentProbe(models.Model):
    id = models.BigAutoField(primary_key=True)
    left_token = models.TextField(null=True)
    right_token = models.TextField(null=True)
    uuid_token = models.UUIDField(null=True)
    active = models.BooleanField(default=True)

    class Meta:
        # Keep this unmanaged SQL probe outside installed app registries so the
        # production model/data-export drift guards do not discover test schema.
        app_label = "e7_test_models"
        managed = False
        db_table = "backup_e7_commitment_probe"


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def persist_active_reservation(fact, kind, *, makerspace_id=7001):
    """Rehydrate the signed fact/state that must drive database enforcement."""

    if kind != B1ReservationEntry.Kind.NUMERIC_RANGE:
        case = prepared([(kind, fact)], makerspace_id=makerspace_id)
        install_manifest_enforcement(inputs=case.inputs, manifest=case.manifest)
        return B1ReservationEntry.objects.get(operation_id=case.inputs.run_id)
    # Numeric-range rows are an older enforcement primitive, not a fact emitted
    # by the compound producer. Exercise its trigger without claiming a complete
    # manifest installation or advancing past STATE_REHYDRATED.
    operation_id, component_id = persist_restore_state(fact, makerspace_id=makerspace_id)
    identity = fact.get("constraint_identity") or fact.get("registry_identity")
    return B1ReservationEntry.objects.create(
        operation_id=operation_id,
        component_id=component_id,
        registry_identity=identity,
        kind=kind,
        definition_sha256=fact["definition_sha256"],
        safe_payload=fact,
        installed_at=timezone.now(),
        catalog_verified_at=timezone.now(),
    )


def persist_restore_state(fact, *, makerspace_id=7001, kind=None, reservation_salt=b"s" * 32):
    """Stop before installation; all expected facts/components already exist."""
    if kind is None:
        kind = {
            "b1-broad-unique-fence-v1": B1ReservationEntry.Kind.BROAD_FENCE,
            "b1-relationship-fence-v1": B1ReservationEntry.Kind.RELATIONSHIP_FENCE,
            "b1-object-namespace-fence-v1": B1ReservationEntry.Kind.OBJECT_NAMESPACE,
        }.get(fact.get("version"))
    ids = (
        [item["component_id"] for item in fact["component_commitments"]]
        if kind == B1ReservationEntry.Kind.COMMITMENT else fact["component_ids"]
    )
    components = [
        {"component_id": str(value), "makerspace_id": makerspace_id + index,
         "ciphertext_sha256": DIGEST}
        for index, value in enumerate(sorted(ids))
    ]
    case = prepared(
        [(kind, fact)] if kind else [], components=components, salt=reservation_salt,
    )
    return case.inputs.run_id, uuid.UUID(str(ids[0]))


def assert_database_rejects(write):
    """Require PostgreSQL, rather than caller validation, to reject a write."""

    try:
        with transaction.atomic():
            write()
    except DatabaseError:
        return
    pytest.fail("PostgreSQL accepted a write covered by an active E7 reservation")
