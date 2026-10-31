"""Derived executable client exclusion requires exact independently bound inputs."""

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from apps.backup.source_primitive_derived import (
    DERIVED_INPUTS, derivation_fingerprint, draft_derived_api, validated_derived,
)
from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import (
    FINGERPRINT_VERSION, FORMAT_VERSION, PARSER_VERSION, SourcePrimitiveCoverageError,
)
from apps.backup.source_primitive_reports import report_binding, review_fingerprint
from .source_primitive_helpers import assert_node20, review_options, write_sources


def derived_fixture(tmp_path):
    files = {
        DERIVED_INPUTS[0]: "export function generate() { return 'export const value = 1;'; }\n",
        DERIVED_INPUTS[1]: '{"openapi":"3.0.3"}\n',
        DERIVED_INPUTS[2]: '{"lockfileVersion":3}\n',
        DERIVED_INPUTS[3]: '{"type":"module"}\n',
        DERIVED_INPUTS[4]: "export const value = 1;\n",
    }
    write_sources(tmp_path, files)
    record, = draft_derived_api(tmp_path)
    assert record["status"] == "UNREVIEWED"
    assert all(record[key] is None for key in (
        "reviewer", "report", "report_binding", "review_fingerprint",
    ))
    assert record["generator_command"] == ["node", "scripts/generate-api-client.mjs"]
    assert record["inputs"] == {p: hashlib.sha256(s.encode()).hexdigest() for p, s in files.items()}
    options = review_options(tmp_path)
    # The tiny generator, schema and output above were explicitly inspected here.
    reviewed = dict(record, status="REVIEWED", reviewer=options["reviewer"], report=options["report"])
    binding = report_binding(tmp_path, options["report"])
    raw = Path(options["report"]).read_bytes()
    assert binding["sha256"] == hashlib.sha256(raw).hexdigest()
    assert binding["size"] == len(raw)
    reviewed["report_binding"] = binding
    reviewed["review_fingerprint"] = review_fingerprint(derivation_fingerprint(record), binding)
    assert validated_derived(tmp_path, [reviewed]) == {DERIVED_INPUTS[-1]}
    return files, record, reviewed


def test_generator_observation_never_approves_derived_output(tmp_path):
    _, draft, _ = derived_fixture(tmp_path)
    with pytest.raises(SourcePrimitiveCoverageError, match="unreviewed or invalid derived"):
        validated_derived(tmp_path, [draft])


@pytest.mark.parametrize("changed_path", DERIVED_INPUTS)
def test_any_generator_schema_lock_manifest_or_output_byte_change_refuses(tmp_path, changed_path):
    files, _, reviewed = derived_fixture(tmp_path)
    write_sources(tmp_path, {changed_path: files[changed_path] + "\n"})
    with pytest.raises(SourcePrimitiveCoverageError, match="^derived snapshot input/output fingerprint changed$"):
        validated_derived(tmp_path, [reviewed])


@pytest.mark.parametrize("version_field,expected", [
    ("format_version", FORMAT_VERSION), ("parser_version", PARSER_VERSION),
    ("fingerprint_version", FINGERPRINT_VERSION),
])
def test_derived_snapshot_itself_binds_parser_and_detector_versions(tmp_path, version_field, expected):
    _, draft, reviewed = derived_fixture(tmp_path)
    assert draft.get(version_field) == expected, "Derived snapshot omits its parser/detector version binding"
    reviewed[version_field] = "unknown-future-parser-or-detector"
    with pytest.raises(SourcePrimitiveCoverageError, match="^derived format/parser/fingerprint version mismatch$"):
        validated_derived(tmp_path, [reviewed])


@pytest.mark.parametrize("mutation,diagnostic", [
    ("command", "unreviewed or invalid derived snapshot"),
    ("output", "unreviewed or invalid derived snapshot"),
    ("duplicate", "duplicate derived snapshot"),
    ("report", "unreviewed or invalid derived snapshot"),
    ("input-set", "derived snapshot input/output fingerprint changed"),
])
def test_invalid_derived_records_refuse(tmp_path, mutation, diagnostic):
    _, _, reviewed = derived_fixture(tmp_path)
    records = [deepcopy(reviewed)]
    if mutation == "command":
        records[0]["generator_command"] = ["node", "other-generator.mjs"]
    elif mutation == "output":
        records[0]["output"] = "frontend/src/other.ts"
    elif mutation == "duplicate":
        records.append(deepcopy(reviewed))
    elif mutation == "report":
        records[0]["report"] = None
    else:
        records[0]["inputs"].pop(DERIVED_INPUTS[0])
    with pytest.raises(SourcePrimitiveCoverageError, match=f"^{diagnostic}$"):
        validated_derived(tmp_path, records)


def test_reviewed_output_exclusion_does_not_exclude_generator_source(tmp_path):
    assert_node20()
    _, _, reviewed = derived_fixture(tmp_path)
    census = collect_source_primitives(tmp_path, derived=[reviewed])
    assert DERIVED_INPUTS[0] in census["symbol_index"]
    assert DERIVED_INPUTS[-1] not in census["symbol_index"]
    assert any(row["path"] == DERIVED_INPUTS[-1] and row.get("digest") for row in census["scope"])
    assert "<module>.generate" in census["symbol_index"][DERIVED_INPUTS[0]]["symbols"]
    assert all(site.path != DERIVED_INPUTS[-1] for site in census["sites"])


@pytest.mark.parametrize("mutation,diagnostic", [
    ("missing-report", "unreviewed or invalid derived snapshot"),
    ("nonexistent-report", "actual review report missing, unsafe or changed"),
    ("deleted-report", "actual review report missing, unsafe or changed"),
    ("changed-bytes", "actual review report missing, unsafe or changed"),
    ("changed-path", "actual review report missing, unsafe or changed"),
    ("symlink-report", "actual review report missing, unsafe or changed"),
    ("missing-binding", "actual review report missing, unsafe or changed"),
    ("wrong-binding", "actual review report missing, unsafe or changed"),
    ("missing-fingerprint", "changed derived review report/source fingerprint"),
    ("wrong-fingerprint", "changed derived review report/source fingerprint"),
])
def test_report_guard_refuses_before_generated_output_is_excluded(tmp_path, mutation, diagnostic):
    _, _, reviewed = derived_fixture(tmp_path)
    report = Path(reviewed["report"])
    if mutation == "missing-report":
        reviewed.pop("report")
    elif mutation == "nonexistent-report":
        reviewed["report"] = str(report.with_name(report.stem + "-absent.txt"))
        assert not Path(reviewed["report"]).exists()
    elif mutation == "deleted-report":
        report.unlink()
    elif mutation == "changed-bytes":
        report.write_bytes(report.read_bytes() + b"Review withdrawn.\n")
    elif mutation == "changed-path":
        alternate = report.with_name(report.stem + "-other.txt")
        alternate.write_bytes(report.read_bytes())
        reviewed["report"] = str(alternate)
    elif mutation == "symlink-report":
        actual = report.with_name(report.stem + "-actual.txt")
        report.rename(actual)
        report.symlink_to(actual)
    elif mutation == "missing-binding":
        reviewed.pop("report_binding")
    elif mutation == "wrong-binding":
        reviewed["report_binding"]["sha256"] = "0" * 64
    elif mutation == "missing-fingerprint":
        reviewed.pop("review_fingerprint")
    else:
        reviewed["review_fingerprint"] = "0" * 64
    # Each public boundary must raise, rather than returning an excluded output
    # or a partial census. Validation precedes foreign parsing, so no Node needed.
    with pytest.raises(SourcePrimitiveCoverageError, match=f"^{diagnostic}$"):
        validated_derived(tmp_path, [reviewed])
    with pytest.raises(SourcePrimitiveCoverageError, match=f"^{diagnostic}$"):
        collect_source_primitives(tmp_path, derived=[reviewed])
