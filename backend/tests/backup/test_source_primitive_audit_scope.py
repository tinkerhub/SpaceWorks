"""Dated audit data stays inventoried; executable inputs still require review."""

import hashlib
from pathlib import Path

import pytest

from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import (
    FINGERPRINT_VERSION, FORMAT_VERSION, PARSER_VERSION, SourcePrimitiveCoverageError,
)
from apps.backup.source_primitive_registry import assemble_reviewed_registry, reconcile_registry
from apps.backup.source_primitive_scope import collect_scope
from .source_primitive_helpers import (
    assert_node20, explicit_review, sql_fixture, write_sources,
)


AUDIT = "docs/audits/2026-10-29"


def test_dated_audit_data_retains_rows_without_reads_hashes_or_corpus_churn(tmp_path, monkeypatch):
    sql_fixture(tmp_path)
    files = {f"{AUDIT}/result{suffix}": "audit data\n"
             for suffix in (".txt", ".log", ".xml", ".json", ".csv")}
    write_sources(tmp_path, files)
    original = Path.read_bytes

    def read_bytes(path):
        assert path.relative_to(tmp_path).as_posix() not in files, "Audit data bytes read as source"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    rows, sources = collect_scope(tmp_path)
    assert set(sources) == {"owner.py"}
    for row in rows:
        if row["path"] in files:
            assert row == dict(path=row["path"], classification="documentation", language=None)
    assert {row["path"] for row in rows} == {*files, "owner.py"}
    before = collect_source_primitives(tmp_path)
    write_sources(tmp_path, {path: "changed bytes\n" for path in files})
    after = collect_source_primitives(tmp_path)
    # Equality covers scope, calls, symbols, site contexts/corpus hashes and fingerprints.
    assert after == before
    for site in after["sites"]:
        assert site.context["format_version"] == FORMAT_VERSION
        assert site.context["parser_version"] == PARSER_VERSION
        assert site.context["fingerprint_version"] == FINGERPRINT_VERSION


def test_cited_dated_document_still_binds_actual_review_report_bytes(tmp_path):
    _, _, _, options = sql_fixture(tmp_path)
    relative = f"{AUDIT}/review.txt"
    report = tmp_path / relative
    report.parent.mkdir(parents=True)
    report.write_bytes(Path(options["report"]).read_bytes())
    options["report"] = relative
    census = collect_source_primitives(tmp_path)
    entry = explicit_review(census["sites"][0], **options)
    ledger = assemble_reviewed_registry(census, [entry], reviewer=options["reviewer"], report=relative)
    assert ledger["report_binding"]["sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert next(row for row in census["scope"] if row["path"] == relative) == {
        "path": relative, "classification": "documentation", "language": None,
    }
    reconcile_registry(census, ledger)
    report.write_text("Review withdrawn after independent inspection.\n", encoding="utf-8")
    changed = collect_source_primitives(tmp_path)
    assert changed == census
    with pytest.raises(SourcePrimitiveCoverageError, match="^actual review report missing, unsafe or changed$"):
        reconcile_registry(changed, ledger)


def test_executables_and_unknown_files_inside_dated_audit_folder_still_need_review(tmp_path):
    assert_node20()
    _, _, _, options = sql_fixture(tmp_path)
    files = {
        f"{AUDIT}/mutate.sh": "psql -c 'DELETE FROM x'\n",
        f"{AUDIT}/mutate.sql": "DELETE FROM x;\n",
        f"{AUDIT}/mutate.py": "from adapter import cursor\ncursor.execute('DELETE FROM x')\n",
        f"{AUDIT}/mutate.ts": "export function write(db: any) { db.query('DELETE FROM x'); }\n",
        f"{AUDIT}/mutate.html": "<script>mutate()</script>\n",
        f"{AUDIT}/mutate.tpl": "{{ mutate() }}\n",
        f"{AUDIT}/mutate.unseen": "custom executable grammar\n",
    }
    write_sources(tmp_path, files)
    wasm = f"{AUDIT}/mutate.wasm"
    raw = b"\x00asm\x01\x00\x00\x00"
    (tmp_path / wasm).write_bytes(raw)
    census = collect_source_primitives(tmp_path)
    rows = {row["path"]: row for row in census["scope"]}
    for path, source in files.items():
        assert rows[path]["classification"] == (
            "unsupported-source" if path.endswith(".unseen") else "production-source"
        )
        assert rows[path]["language"]
        assert rows[path]["digest"] == hashlib.sha256(source.encode()).hexdigest()
    assert rows[wasm]["classification"] == "production-source"
    assert rows[wasm]["digest"] == hashlib.sha256(raw).hexdigest()
    assert {site.path for site in census["sites"]} == {*files, wasm, "owner.py"}
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed source sites"):
        reconcile_registry(census, [])
    reviews = [explicit_review(site, facts=site.unresolved, **options) for site in census["sites"]]
    reconcile_registry(census, reviews)


@pytest.mark.parametrize("path", [
    "runtime/config.json",
    "docs/audits/config.json",
    "docs/other/2026-10-29/config.json",
    "docs/audits/2026-02-30/config.json",
    "docs/audits/2026-1-29/config.json",
    "docs/audits/20261029/config.json",
    "docs/audits/2026-W44-4/config.json",
])
def test_runtime_data_and_invalid_or_noncanonical_date_folders_still_hash_bytes(tmp_path, path):
    _, _, ledger, _ = sql_fixture(tmp_path)
    write_sources(tmp_path, {path: '{"enabled":true}\n'})
    before = collect_source_primitives(tmp_path)
    row = next(row for row in before["scope"] if row["path"] == path)
    assert row == dict(path=path, classification="production-input", language="opaque",
                       digest=hashlib.sha256(b'{"enabled":true}\n').hexdigest())
    assert any(site.path == path and site.unresolved for site in before["sites"])
    with pytest.raises(SourcePrimitiveCoverageError, match="scope/dependency index: scope"):
        reconcile_registry(before, ledger)
    write_sources(tmp_path, {path: '{"enabled":false}\n'})
    after = collect_source_primitives(tmp_path)
    changed = next(row for row in after["scope"] if row["path"] == path)
    assert changed["digest"] != row["digest"]
    assert after["sites"] != before["sites"]
