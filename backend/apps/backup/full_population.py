"""Snapshot cohort facts and locked publication checks for signed full custody."""

from django.db import connection

from apps.backup.compound_recipients import frozen_population
from apps.backup.errors import BackupBuildError
from apps.backup.models import BackupArchive, BackupRun
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


SERVABILITY_FIELDS = ("archived_at", "lifecycle_state", "purge_started_at")


def retained_population():
    population = frozen_population()
    spaces = {row.pk: row for row in Makerspace.objects.order_by("pk")}
    return [{
        **item,
        **servability_facts(spaces[item["makerspace_id"]]),
        "custody_state": None,
        "recipients": [],
    } for item in population]


def servability_facts(space):
    return {
        name: value.isoformat() if hasattr(value, "isoformat") else value
        for name in SERVABILITY_FIELDS
        for value in (getattr(space, name),)
    }


def servable_cohort():
    return {
        str(pk): flag for pk, flag in servable_queryset().order_by("pk").values_list(
            "pk", "superadmin_access_enabled"
        )
    }


def typed_flags(flags):
    if not isinstance(flags, dict) or any(
        not isinstance(key, str) or not key.isascii() or not key.isdecimal()
        or str(int(key)) != key or int(key) <= 0 or type(value) is not bool
        for key, value in flags.items()
    ):
        raise BackupBuildError("The backup run flags are not a canonical typed cohort.")
    return dict(flags)


def run_facts(archive, cohort):
    # Do not use archive.backup_run: its relation cache may predate this snapshot.
    binding = BackupArchive.objects.values_list("backup_run_id", flat=True).get(pk=archive.pk)
    if binding != archive.backup_run_id:
        raise BackupBuildError("The archive run binding changed before capture.")
    if binding is None:
        return None
    run = BackupRun.objects.get(pk=binding)
    validate_run(run, cohort)
    return {
        "id": str(run.pk), "holder": str(run.holder) if run.holder else None,
        "status": run.status, "flag_snapshot": typed_flags(run.flag_snapshot),
    }


def validate_run(run, cohort, frozen=None):
    if (
        run.holder is None
        or run.status not in {BackupRun.Status.PENDING, BackupRun.Status.RUNNING}
        or typed_flags(run.flag_snapshot) != typed_flags(cohort)
        or (frozen is not None and (
            str(run.pk) != frozen["id"]
            or (str(run.holder) if run.holder else None) != frozen["holder"]
            or typed_flags(run.flag_snapshot) != typed_flags(frozen["flag_snapshot"])
        ))
    ):
        raise BackupBuildError("The frozen backup run holder, status or exact cohort changed.")


def lock_full_publication(facts):
    """First locks in the promotion transaction: population fence, then run."""
    from apps.backup.artifact_ledger import ArtifactLedgerMismatch

    with connection.cursor() as cursor:
        cursor.execute("LOCK TABLE makerspaces_makerspace IN SHARE MODE")
    manifest = facts["outer_manifest"]
    frozen = facts["frozen_promotion_snapshot"]
    run_id = manifest["backup_run_id"]
    binding = BackupArchive.objects.values_list("backup_run_id", flat=True).get(
        pk=facts["archive_uuid_snapshot"]
    )
    expected = frozen["run"]
    if (
        (str(binding) if binding else None) != run_id
        or (expected["id"] if expected else None) != run_id
    ):
        raise ArtifactLedgerMismatch("The signed archive run binding changed.")
    run = None
    if run_id:
        try:
            run = BackupRun.objects.select_for_update().get(pk=run_id)
        except BackupRun.DoesNotExist as exc:
            raise ArtifactLedgerMismatch("The frozen backup run is no longer eligible for publication.") from exc
    # Eligibility is checked before new publication below. An already-published
    # artifact may return idempotently after its run has subsequently completed.
    return run


def validate_full_population(artifact, archive, spaces, locked_run):
    from apps.backup.artifact_ledger import ArtifactLedgerMismatch
    from apps.backup.not_restored import assert_deployment_fully_restored, TenantNotRestored

    frozen = artifact.frozen_promotion_snapshot
    try:
        assert_deployment_fully_restored()
    except TenantNotRestored as exc:
        raise ArtifactLedgerMismatch("An opaque not-restored population appeared before publication.") from exc
    if frozen["servable_run_cohort"] != servable_cohort():
        raise ArtifactLedgerMismatch("The complete servable run cohort changed.")
    for item in frozen["retained"]:
        if servability_facts(spaces[item["makerspace_id"]]) != {
            name: item[name] for name in SERVABILITY_FIELDS
        }:
            raise ArtifactLedgerMismatch("A frozen makerspace lifecycle fact changed.")
    expected = frozen["run"]
    if (str(archive.backup_run_id) if archive.backup_run_id else None) != (
        expected["id"] if expected else None
    ):
        raise ArtifactLedgerMismatch("The archive run binding changed under publication locks.")
    if expected:
        if locked_run is None:
            raise ArtifactLedgerMismatch("Full publication requires a locked backup run.")
        try:
            validate_run(locked_run, frozen["servable_run_cohort"], expected)
        except BackupBuildError as exc:
            raise ArtifactLedgerMismatch("The locked backup run changed before publication.") from exc
