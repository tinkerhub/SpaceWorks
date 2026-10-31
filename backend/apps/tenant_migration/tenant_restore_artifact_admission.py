"""Mandatory selected-byte admission before any Lane D restore phase effect."""

from dataclasses import dataclass
import hashlib
import hmac
import json
from types import MappingProxyType
from uuid import UUID

from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_outer_artifact import read_outer_manifest
from .tenant_dump_projection_proof import validate_projection_verification
from .tenant_restore_artifact_files import read_inner_manifest_bytes
from .tenant_restore_inner_admission import validate_authenticated_inner
from .tenant_restore_types import TenantRestoreRefused


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class VerifiedArtifactContext:
    artifact_sha256: str
    outer_version: int
    capture_id: str
    inner_manifest_sha256: str | None
    projection_mode: str
    projection_proof_sha256: str | None
    database_member_sha256: str | None
    api_client_catalog: MappingProxyType | None = None

    def ledger_bindings(self):
        return {
            "artifact_sha256": self.artifact_sha256, "outer_version": self.outer_version,
            "capture_id": self.capture_id, "inner_manifest_sha256": self.inner_manifest_sha256,
            "projection_mode": self.projection_mode, "projection_proof_sha256": self.projection_proof_sha256,
            "database_member_sha256": self.database_member_sha256,
        }


# Retain the descriptive name used in the approved protocol handoff.
FrozenVerifiedArtifactContext = VerifiedArtifactContext


def _path(artifact, method, inputs):
    reader = getattr(artifact, method, None)
    if not callable(reader):
        raise TenantRestoreRefused(f"The artifact adapter must implement {method}.")
    try:
        return reader(inputs)
    except NotImplementedError as exc:
        raise TenantRestoreRefused(f"The artifact adapter does not support {method}.") from exc


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON constants are not supported.")


def read_selected_artifact_context(inputs, artifact):
    try:
        outer = read_outer_manifest(
            _path(artifact, "selected_artifact_path", inputs),
            expected_artifact_sha256=inputs.artifact_sha256,
        )
        capture = str(UUID(str(inputs.capture_id)))
        if outer["capture_id"] != capture or outer["artifact_id"] != capture:
            raise TenantRestoreRefused("The selected artifact names another capture.")
        if outer["version"] == 1:
            proof = validate_projection_verification(None, outer_manifest=outer)
            return VerifiedArtifactContext(inputs.artifact_sha256, 1, capture, None,
                                           proof.mode, proof.proof_sha256, proof.database_member_sha256)
        data = read_inner_manifest_bytes(_path(artifact, "inner_manifest_path", inputs))
        inner_sha256 = hashlib.sha256(data).hexdigest()
        if not hmac.compare_digest(inner_sha256, outer["compatibility"]["inner_manifest_sha256"]):
            raise TenantRestoreRefused("The inner manifest differs from the selected artifact.")
        inner = json.loads(data.decode("utf-8"), object_pairs_hook=_json_object,
                           parse_constant=_reject_constant)
        catalog = validate_authenticated_inner(inner, outer)
        proof = validate_projection_verification(inner, outer_manifest=outer)
        return VerifiedArtifactContext(inputs.artifact_sha256, 2, capture, inner_sha256,
                                       proof.mode, proof.proof_sha256, proof.database_member_sha256,
                                       freeze(catalog))
    except (TenantDumpVerificationError, OSError, ValueError, TypeError, KeyError,
            UnicodeError, RecursionError, AttributeError, OverflowError) as exc:
        raise TenantRestoreRefused("Selected Lane D artifact admission failed.") from exc
