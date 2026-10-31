"""Compile manifest facts against trusted target catalog, never retained rows."""

import hashlib
import json
import uuid

from apps.backup.compound_restore_catalog import target_catalog_binding
from apps.backup.models import B1ReservationEntry
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_enforcement import catalog_bound_payload, _is_digest


FACT_GROUPS = (
    ("reservation_commitments", B1ReservationEntry.Kind.COMMITMENT),
    ("broad_fence_scopes", B1ReservationEntry.Kind.BROAD_FENCE),
    ("relationship_fence_scopes", B1ReservationEntry.Kind.RELATIONSHIP_FENCE),
    ("object_namespace_fences", B1ReservationEntry.Kind.OBJECT_NAMESPACE),
)


def canonical_text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical_text(value).encode("utf-8")).hexdigest()


def require_expectation(operation, text, sha256):
    if not operation.expected_installation or not operation.expected_installation_sha256:
        raise BackupBuildError("Legacy unfinished restore is unattested; start a fresh restore.")
    if (operation.expected_installation != text
            or operation.expected_installation_sha256 != sha256):
        raise BackupBuildError("The selected manifest or compiled target expectation changed.")


def compile_expectation(manifest, *, using):
    components = component_map(manifest)
    entries = []
    keys = set()
    shared = {}
    for group, kind in FACT_GROUPS:
        facts = manifest.get(group)
        if not isinstance(facts, list):
            raise BackupBuildError(f"The signed {group} declaration is missing.")
        for fact in facts:
            if not isinstance(fact, dict):
                raise BackupBuildError("A signed reservation fact is invalid.")
            identities = fact_components(fact, kind)
            if not identities or not identities <= components.keys():
                raise BackupBuildError("A reservation names an unknown component.")
            payload = catalog_bound_payload(
                fact, kind=kind, reservation_salt=manifest.get("reservation_salt"),
                using=using,
            )
            identity = fact.get("constraint_identity") or fact.get("registry_identity")
            definition = fact.get("definition_sha256")
            if not _is_digest(identity) or not _is_digest(definition):
                raise BackupBuildError("A signed reservation digest is invalid.")
            binding = target_catalog_binding(payload, using=using)
            signature = (definition, canonical_text(payload), binding["target_relation_oid"])
            if identity in shared and shared[identity] != signature:
                raise BackupBuildError("Shared reservation definitions conflict.")
            shared[identity] = signature
            for component_id in sorted(identities, key=str):
                key = (str(component_id), kind, identity)
                if key in keys:
                    raise BackupBuildError("A signed reservation tuple is duplicated.")
                keys.add(key)
                entries.append({
                    "component_id": str(component_id), "kind": kind,
                    "registry_identity": identity, "definition_sha256": definition,
                    "source_fact": fact, "installed_payload": payload, **binding,
                })
    sequences = manifest.get("sequence_reservations")
    if not isinstance(sequences, list) or any(not isinstance(f, dict) for f in sequences):
        raise BackupBuildError("The signed sequence declaration is missing or invalid.")
    sequence_keys = [(f.get("schema"), f.get("sequence")) for f in sequences]
    if (any(not isinstance(s, str) or not isinstance(n, str) for s, n in sequence_keys)
            or len(set(sequence_keys)) != len(sequence_keys)):
        raise BackupBuildError("A signed sequence identity is invalid or duplicated.")
    expected = {
        "version": 1, "manifest_sha256": digest(manifest),
        "components": [
            {"component_id": str(identity), **fact}
            for identity, fact in sorted(components.items(), key=lambda pair: str(pair[0]))
        ],
        "entries": sorted(entries, key=lambda f: (
            f["component_id"], f["kind"], f["registry_identity"]
        )),
        "sequences": sorted(sequences, key=lambda f: (f["schema"], f["sequence"])),
    }
    text = canonical_text(expected)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def component_map(manifest):
    result = {}
    for item in manifest.get("slice_components", ()):
        try:
            identity = uuid.UUID(item["component_id"])
            makerspace_id = item["makerspace_id"]
            ciphertext = item["ciphertext_sha256"]
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupBuildError("A signed slice component is invalid.") from exc
        if (identity in result or str(identity) != item["component_id"]
                or type(makerspace_id) is not int or makerspace_id <= 0
                or not _is_digest(ciphertext)):
            raise BackupBuildError("A signed slice component identity is invalid or duplicated.")
        result[identity] = {"makerspace_id": makerspace_id, "ciphertext_sha256": ciphertext}
    if not result:
        raise BackupBuildError("A compound restore has no opaque component.")
    return result


def fact_components(fact, kind):
    try:
        values = (
            [item["component_id"] for item in fact["component_commitments"]]
            if kind == B1ReservationEntry.Kind.COMMITMENT else fact["component_ids"]
        )
        identities = {uuid.UUID(value) for value in values}
        if (len(identities) != len(values)
                or any(str(uuid.UUID(value)) != value for value in values)):
            raise ValueError
        return identities
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BackupBuildError("A reservation component identity is invalid.") from exc
