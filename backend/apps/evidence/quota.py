"""Trusted journal sizes and deployment-local proof of an actual storage debit."""

from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.evidence.models import EvidenceUploadFinalization


def finalized_size_bytes(state):
    """Declared photo sizes never establish a charge or a retention fallback."""
    if state is None or state.status != EvidenceUploadFinalization.Status.FINALIZED:
        return 0
    size = state.size_bytes
    return size if type(size) is int and size > 0 else 0


def local_accounting_database_id():
    """Read the existing singleton per operation; never seed or cache identity."""
    database_uuid = DeploymentDatabaseIdentity.objects.filter(pk=1).values_list(
        "database_uuid", flat=True
    ).first()
    # UUIDField supplies a UUID, whose string form is canonical and nonempty.
    return str(database_uuid) if database_uuid is not None else None


def proven_charge_bytes(evidence, state):
    """Return at most one journal amount, never a sum of historical markers.

    A consistent same-deployment restore may retain this proof. Foreign identities,
    source-prefixed portable metadata and legacy flags cannot establish a debit.
    Callers settling expiry must hold the finalization row lock.
    """
    size = finalized_size_bytes(state)
    if (
        not size
        or state.quota_charged is not True
        or state.evidence_id != evidence.pk
        or state.updated_at is None
    ):
        return 0
    database_id = local_accounting_database_id()
    if database_id is None:
        return 0
    journal_version = state.updated_at.isoformat()
    markers = AuditLog.objects.filter(
        makerspace_id=evidence.makerspace_id,
        target_type=evidence._meta.label_lower,
        target_id=str(evidence.pk),
        action="evidence.storage_charged",
    ).order_by().values_list("meta", flat=True)
    for meta in markers.iterator():
        if (
            isinstance(meta, dict)
            and type(meta.get("version")) is int
            and meta["version"] == 1
            and type(meta.get("bytes")) is int
            and meta["bytes"] == size
            and meta.get("journal_version") == journal_version
            and meta.get("accounting_database_id") == database_id
        ):
            return size
    return 0
