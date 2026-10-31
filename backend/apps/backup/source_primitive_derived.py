"""Optional exact bindings for generated API code; never infer trust from a path."""

from pathlib import Path

from .source_primitive_fingerprint import (
    FORMAT_VERSION, PARSER_VERSION, FINGERPRINT_VERSION,
    SourcePrimitiveCoverageError, bytes_digest, digest,
)
from .source_primitive_reports import review_fingerprint, validate_report


DERIVED_INPUTS = (
    "frontend/scripts/generate-api-client.mjs", "frontend/openapi-schema.json",
    "frontend/package-lock.json", "frontend/package.json",
    "frontend/src/generated/api.ts",
)
GENERATOR_COMMAND = ["node", "scripts/generate-api-client.mjs"]


def draft_derived_api(root):
    """An observation only. The generator source remains independently scanned."""
    root = Path(root)
    if not all((root / path).is_file() for path in DERIVED_INPUTS):
        return []
    return [{
        "kind": "executable-derived-api", "status": "UNREVIEWED",
        "format_version": FORMAT_VERSION, "parser_version": PARSER_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "generator_command": GENERATOR_COMMAND,
        "output": DERIVED_INPUTS[-1],
        "inputs": {path: bytes_digest((root / path).read_bytes()) for path in DERIVED_INPUTS},
        "reviewer": None, "report": None,
        "report_binding": None, "review_fingerprint": None,
    }]


def derivation_fingerprint(record):
    """Bind the known derivation fields before combining them with report bytes."""
    return digest({key: record[key] for key in (
        "kind", "format_version", "parser_version", "fingerprint_version",
        "generator_command", "output", "inputs",
    )})


def validated_derived(root, records):
    """Validate a complete reviewed derivation before omitting any output AST."""
    outputs = set()
    for record in records:
        if (not isinstance(record, dict) or record.get("status") != "REVIEWED"
                or any(not isinstance(record.get(key), str) or not record[key].strip()
                       for key in ("reviewer", "report"))
                or record.get("kind") != "executable-derived-api"
                or record.get("generator_command") != GENERATOR_COMMAND
                or record.get("output") != DERIVED_INPUTS[-1]):
            raise SourcePrimitiveCoverageError("unreviewed or invalid derived snapshot")
        if any(record.get(key) != value for key, value in (
                ("format_version", FORMAT_VERSION), ("parser_version", PARSER_VERSION),
                ("fingerprint_version", FINGERPRINT_VERSION))):
            raise SourcePrimitiveCoverageError("derived format/parser/fingerprint version mismatch")
        actual = draft_derived_api(root)
        if not actual or record.get("inputs") != actual[0]["inputs"]:
            raise SourcePrimitiveCoverageError("derived snapshot input/output fingerprint changed")
        binding = validate_report(root, record["report"], record.get("report_binding"))
        if record.get("review_fingerprint") != review_fingerprint(
                derivation_fingerprint(record), binding):
            raise SourcePrimitiveCoverageError("changed derived review report/source fingerprint")
        output = record["output"]
        if output in outputs:
            raise SourcePrimitiveCoverageError("duplicate derived snapshot")
        outputs.add(output)
    return outputs
