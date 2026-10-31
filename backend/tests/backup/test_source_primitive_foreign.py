"""Actual locked TypeScript worker and shell/embedded adapters, never mocks."""

import json
import subprocess

import pytest

from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import SourcePrimitiveCoverageError
from apps.backup.source_primitive_registry import reconcile_registry
from .source_primitive_helpers import (
    ROOT, assert_node20, explicit_review, review_options, write_sources,
)


@pytest.fixture(scope="module", autouse=True)
def installed_node20_parser():
    assert_node20()


def test_actual_mjs_imports_meta_env_generator_and_private_output_are_discovered(tmp_path):
    relative = "frontend/scripts/generator.mjs"
    write_sources(tmp_path, {relative:
        "import { writeFile as emit } from 'node:fs';\n"
        "const bucket = import.meta.env.VITE_BUCKET;\n"
        "export function generate(client) {\n"
        "  client.copyObject({Bucket: bucket, Key: 'private/output'});\n"
        "  emit('private/generated.js', 'export const value = 1;');\n}\n"})
    census = collect_source_primitives(tmp_path)
    sites = census["sites"]
    assert {s.category for s in sites} >= {"settings_environment", "object_storage", "generated_path"}
    assert any(s.path == relative and s.owner == "<module>.generate"
               and s.category == "object_storage" and s.line == 4 for s in sites)
    assert "node:fs" in census["symbol_index"][relative]["dependencies"]
    assert "frontend/package-lock.json" in census["symbol_index"][relative]["dependencies"]
    assert "<parser>" in census["symbol_index"][relative]["symbols"]
    assert any(c["target"] == "node:fs.writeFile" for c in census["call_index"])
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed"):
        reconcile_registry(census, {})


def test_typescript_recovered_ast_diagnostics_still_refuse(tmp_path):
    source = "export const SECRET_SENTINEL: = 1;\n"
    request = dict(root=str(ROOT), path="invalid.ts", text=source)
    worker = subprocess.run(
        ["node", str(ROOT / "scripts/source_audit/parse_typescript.mjs")],
        input=json.dumps(request), text=True, capture_output=True, check=False, timeout=30,
    )
    response = json.loads(worker.stdout)
    assert worker.returncode != 0
    assert response["error"] == "typescript_parse_diagnostics"
    assert response["diagnostics"]
    assert all(set(d) == {"code", "start"} for d in response["diagnostics"])
    assert "SECRET_SENTINEL" not in worker.stdout
    write_sources(tmp_path, {"invalid.ts": source})
    with pytest.raises(SourcePrimitiveCoverageError, match="static parse failed: invalid.ts") as error:
        collect_source_primitives(tmp_path)
    assert "SECRET_SENTINEL" not in str(error.value)


def test_dynamic_js_callee_is_opaque_and_needs_exact_explicit_review(tmp_path):
    write_sources(tmp_path, {"dynamic.ts":
        "export function invoke(client: any, operation: string) {\n"
        "  return client[operation]('payload');\n}\n"})
    census = collect_source_primitives(tmp_path)
    sites = census["sites"]
    assert sites and all(s.category == "unresolved_dynamic" for s in sites)
    facts = {fact for s in sites for fact in s.unresolved}
    assert facts >= {"dynamic_or_opaque_callee", "computed_member_requires_context_review"}
    assert any(c["target"] == "<dynamic-member>" for c in census["call_index"])
    options = review_options(tmp_path)
    with pytest.raises(SourcePrimitiveCoverageError, match="opaque direct review"):
        explicit_review(sites[0], **options)
    # Only this exact two-fact synthetic dynamic owner has been inspected.
    assert len(sites) == 2 and {s.owner for s in sites} == {"<module>.invoke"}
    reviews = [explicit_review(s, facts=s.unresolved, **options) for s in sites]
    reconcile_registry(census, reviews)
    write_sources(tmp_path, {"dynamic.ts": "export function invoke(client: any) { return client['delete'](); }\n"})
    with pytest.raises(SourcePrimitiveCoverageError, match="fingerprint|stale/orphan|new/unreviewed"):
        reconcile_registry(collect_source_primitives(tmp_path), reviews)


@pytest.mark.parametrize("program,category,target", [
    ("sh -c \"psql -c 'DELETE FROM x'\"\n", "raw_sql", "psql"),
    ("python3 -c \"from adapter import cursor; cursor.execute('DELETE FROM x')\"\n",
     "raw_sql", "adapter.cursor.execute"),
    ("node -e \"import {db} from 'sql'; db.query('DELETE FROM x')\"\n",
     "raw_sql", "sql.db.query"),
])
def test_literal_inline_programs_are_scanned_in_actual_language(tmp_path, program, category, target):
    write_sources(tmp_path, {"entry.sh": program})
    census = collect_source_primitives(tmp_path)
    assert any(s.category == category and ".inline@" in s.owner for s in census["sites"])
    assert any(c["target"] == target and ".inline@" in c["owner"] for c in census["call_index"])
    assert any("shell_whole_context_review_required" in s.unresolved for s in census["sites"])


@pytest.mark.parametrize("program,category,target", [
    ("psql <<'SQL'\nUPDATE x SET a=1;\nSQL\n", "raw_sql", None),
    ("python3 <<'PY'\nfrom adapter import s3\ns3.copy_object(Bucket='b', Key='k')\nPY\n",
     "object_storage", "adapter.s3.copy_object"),
    ("node <<'JS'\nimport {db} from 'sql';\ndb.query('DELETE FROM x');\nJS\n",
     "raw_sql", "sql.db.query"),
])
def test_heredoc_programs_use_sql_python_or_actual_js_parser(tmp_path, program, category, target):
    write_sources(tmp_path, {"entry.sh": program})
    census = collect_source_primitives(tmp_path)
    assert any(s.category == category and ".heredoc@" in s.owner and s.line >= 2
               for s in census["sites"])
    if target:
        assert any(c["target"] == target and ".heredoc@" in c["owner"]
                   for c in census["call_index"])
    assert not any("unsupported_embedded_language" in s.unresolved for s in census["sites"])


def test_shell_branch_has_whole_file_opaque_obligation_and_context_binding(tmp_path):
    source = "if test -n \"$ACTIVE\"; then\n  psql -c 'DELETE FROM x'\nfi\n"
    write_sources(tmp_path, {"entry.sh": source})
    census = collect_source_primitives(tmp_path)
    sites = census["sites"]
    facts = {fact for s in sites for fact in s.unresolved}
    assert facts >= {"shell_compound_or_substitution_grammar", "shell_whole_context_review_required"}
    assert any(s.category == "raw_sql" for s in sites)
    options = review_options(tmp_path)
    reviews = [explicit_review(s, facts=s.unresolved, **options) for s in sites]
    reconcile_registry(census, reviews)
    write_sources(tmp_path, {"entry.sh": source.replace('"$ACTIVE"', '"$OTHER"')})
    changed = collect_source_primitives(tmp_path)
    assert {s.source_symbol for s in changed["sites"]} == {s.source_symbol for s in sites}
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        reconcile_registry(changed, reviews)


@pytest.mark.parametrize("path,source,opaque_fact", [
    ("Dockerfile.runtime", "RUN psql -c 'DELETE FROM x'\n", "container_whole_context_review_required"),
    ("runtime.yaml", "services:\n  worker:\n    command: psql -c 'DELETE FROM x'\n",
     "yaml_whole_context_review_required"),
    ("runtime.yaml", "jobs:\n  build:\n    steps:\n      - run: |\n          node <<'JS'\n          import {db} from 'sql'; db.query('DELETE FROM x');\n          JS\n",
     "yaml_whole_context_review_required"),
])
def test_runtime_container_yaml_commands_are_obligations(tmp_path, path, source, opaque_fact):
    write_sources(tmp_path, {path: source})
    census = collect_source_primitives(tmp_path)
    assert any(s.category == "raw_sql" for s in census["sites"])
    assert any(opaque_fact in s.unresolved for s in census["sites"])
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed"):
        reconcile_registry(census, {})
