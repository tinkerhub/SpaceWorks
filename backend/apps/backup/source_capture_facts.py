"""Pure, immutable source provenance independent of the signed partition proof."""

from dataclasses import asdict, dataclass
import hashlib
import json

from apps.backup.errors import BackupBuildError


_IDENTITY_LIMIT = 512
_FIELDS = frozenset({
    "source_database_identity", "source_server_identity", "frozen_dump_sha256",
    "frozen_population_ownership_digest",
})


@dataclass(frozen=True, slots=True)
class SourceCaptureFacts:
    source_database_identity: str
    source_server_identity: str
    frozen_dump_sha256: str
    frozen_population_ownership_digest: str

    def __post_init__(self):
        for value in (self.source_database_identity, self.source_server_identity):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > _IDENTITY_LIMIT
                or any(character in value for character in ("\x00", "\r", "\n"))
            ):
                raise BackupBuildError("The frozen source capture identity is invalid.")
        for value in (self.frozen_dump_sha256, self.frozen_population_ownership_digest):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise BackupBuildError("The frozen source capture digest is invalid.")

    def as_dict(self) -> dict[str, str]:
        """Return only the four allowlisted, non-secret proof header fields."""
        return asdict(self)


def source_capture_facts_from_mapping(value) -> SourceCaptureFacts:
    """Validate the exact independent outer-manifest mapping."""
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise BackupBuildError("The outer source capture mapping is incomplete or malformed.")
    return SourceCaptureFacts(**value)


def build_source_capture_facts(
    *, source_database_identity, source_server_identity, frozen_dump_sha256,
    frozen_population, object_references,
) -> SourceCaptureFacts:
    """Build facts from frozen inputs only; usable by producers and pure fixtures."""
    if not isinstance(frozen_population, tuple) or not isinstance(object_references, tuple):
        raise BackupBuildError("The source capture inputs are not frozen tuples.")
    try:
        ownership = {
            "population": frozen_population,
            "references": [{
                "bucket_kind": item.bucket_kind,
                "site": item.site,
                "candidate_owner": item.candidate_owner,
                "makerspace_id": item.canonical_makerspace_id,
                "coordination_policy": item.coordination_policy,
            } for item in object_references],
        }
        # Preserve source_verifier._digest exactly, including ASCII escaping and
        # list order. The outer ledger digest uses a different JSON convention.
        raw = json.dumps(
            ownership, sort_keys=True, separators=(",", ":"), default=str,
            ensure_ascii=True,
        ).encode("utf-8")
    except (AttributeError, TypeError, ValueError, UnicodeError) as exc:
        raise BackupBuildError("The frozen source ownership inputs are invalid.") from exc
    return SourceCaptureFacts(
        source_database_identity=source_database_identity,
        source_server_identity=source_server_identity,
        frozen_dump_sha256=frozen_dump_sha256,
        frozen_population_ownership_digest=hashlib.sha256(raw).hexdigest(),
    )


def source_capture_facts_from_capture(capture) -> SourceCaptureFacts:
    """Read captured inputs without consulting the database or proof headers."""
    try:
        return build_source_capture_facts(
            source_database_identity=capture.source_database_identity,
            source_server_identity=capture.source_server_identity,
            frozen_dump_sha256=capture.source_dump_sha256,
            frozen_population=capture.frozen_population,
            object_references=capture.object_plan.references,
        )
    except AttributeError as exc:
        raise BackupBuildError("The source capture inputs are missing or unsupported.") from exc


def require_source_capture_facts(capture) -> SourceCaptureFacts:
    """Require an earlier independent freeze and refuse subsequent input drift."""
    frozen = getattr(capture, "source_capture_facts", None)
    if not isinstance(frozen, SourceCaptureFacts):
        raise BackupBuildError("The independent frozen source capture facts are missing.")
    if source_capture_facts_from_capture(capture) != frozen:
        raise BackupBuildError("The source capture inputs changed after freezing.")
    return frozen
