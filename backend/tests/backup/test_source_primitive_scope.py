"""Exact release-input scope, including exclusions that must never read secrets."""

import hashlib
from pathlib import Path

import pytest

from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import SourcePrimitiveCoverageError
from apps.backup.source_primitive_registry import reconcile_registry
from apps.backup.source_primitive_scope import classify, collect_scope
from .source_primitive_helpers import (
    assert_node20, explicit_review, review_options, sql_fixture, write_sources,
)


@pytest.mark.parametrize("path,classification,language", [
    ("backend/apps/x/migrations/0012_write.py", "production-source", "python"),
    ("frontend/scripts/generate-api-client.mjs", "production-source", "typescript"),
    ("frontend/src/generated/api.ts", "production-source", "typescript"),
    ("Dockerfile.runtime", "production-source", "container"),
    ("deploy/runtime.yaml", "production-source", "container"),
    ("runtime/client.j2", "production-source", "opaque"),
    ("new_program.unseen", "unsupported-source", "opaque"),
    ("credential_rotation.py", "production-source", "python"),
    ("credential_provider.mjs", "production-source", "typescript"),
    ("credential_provider.mts", "production-source", "typescript"),
    ("credential_provider.cts", "production-source", "typescript"),
    ("credential_rotation.bash", "production-source", "shell"),
    ("credential_rotation.sql", "production-source", "sql"),
    ("config.json", "production-input", "opaque"),
    ("backend/tests/check.py", "test-excluded", None),
    ("frontend/src/page.test.tsx", "test-excluded", None),
    ("docs/source-audit/registry.json", "review-ledger", None),
    ("README.md", "documentation", None),
    ("backend/.env", "private-excluded", None),
    ("keys/private.pem", "private-excluded", None),
])
def test_scope_classification_is_explicit(path, classification, language):
    assert classify(path) == (classification, language)


def test_scope_has_exact_paths_and_source_hashes(tmp_path):
    files = {"owner.py": "VALUE = 1\n", "credential_rotation.py": "VALUE = 2\n",
             "input.json": "{}\n", "README.md": "read me\n", "tests/check.py": "not python!"}
    write_sources(tmp_path, files)
    rows, sources = collect_scope(tmp_path)
    assert [row["path"] for row in rows] == sorted(files)
    assert set(sources) == {"owner.py", "credential_rotation.py", "input.json"}
    for row in rows:
        if row["path"] in sources:
            assert row["digest"] == hashlib.sha256(files[row["path"]].encode()).hexdigest()
        else:
            assert "digest" not in row
    census = collect_source_primitives(tmp_path)
    assert census["scope"] == rows


def test_private_files_are_excluded_without_reading_their_bytes(tmp_path, monkeypatch):
    secrets = {".env", ".env.production", "backend/.env", "private.pem", "server.key",
               "credentials.json", "id_ed25519", "secrets/hidden.py",
               "other/.env.example", "backend/.env.production.example",
               "frontend/.env.production.example", ".env.example.backup",
               ".env.example/hidden.py"}
    write_sources(tmp_path, {path: "SENTINEL_NEVER_READ" for path in secrets})
    write_sources(tmp_path, {"credential_rotation.py": "from adapter import cursor\ncursor.execute('DELETE FROM x')\n"})
    original = Path.read_bytes
    touched = []

    def read_bytes(path):
        relative = path.relative_to(tmp_path).as_posix()
        assert relative not in secrets, "Excluded secret bytes were accessed"
        touched.append(relative)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    census = collect_source_primitives(tmp_path)
    assert {row["path"] for row in census["scope"]} == {"credential_rotation.py"}
    assert touched == ["credential_rotation.py"]
    assert any(site.category == "raw_sql" for site in census["sites"])
    assert "SENTINEL_NEVER_READ" not in repr(census)


def test_migrations_and_storage_primitives_are_not_exempt(tmp_path):
    write_sources(tmp_path, {
        "backend/apps/example/migrations/0042_change.py":
            "from django.db import migrations\noperation = migrations.RunSQL('UPDATE x SET a=1')\n",
        "backend/apps/example/storage.py":
            "from adapter import s3\ndef inspect():\n    return s3.head_object(Bucket='b', Key='k')\n",
    })
    census = collect_source_primitives(tmp_path)
    assert {(s.path, s.category) for s in census["sites"]} == {
        ("backend/apps/example/migrations/0042_change.py", "raw_sql"),
        ("backend/apps/example/storage.py", "object_storage"),
    }
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed"):
        reconcile_registry(census, {})


@pytest.mark.parametrize("source,line,owner", [
    ("from django.db import models\nclass Loan(models.Model):\n"
     "    space = models.ForeignKey('makerspaces.Makerspace', on_delete=models.PROTECT)\n", 3, "Loan"),
    ("from django.urls import path\nfrom .views import public_catalog\n"
     "urlpatterns = [path('catalog/', public_catalog, name='public-catalog')]\n", 3, "<module>"),
    ("from django.conf import settings as config\nPUBLIC = config.PUBLIC_CATALOG\n", 2, "<module>"),
])
def test_declarations_config_and_public_routes_need_explicit_nonmutation_review(tmp_path, source, line, owner):
    write_sources(tmp_path, {"declarations.py": source})
    census = collect_source_primitives(tmp_path)
    candidates = [s for s in census["sites"] if s.path == "declarations.py"
                  and s.line == line and s.owner == owner]
    assert candidates, "Declarations/routes must be discovered before an explicit read/declaration disposition"
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed"):
        reconcile_registry(census, {})
    options = review_options(tmp_path)
    options["disposition"] = "explicit reviewed declaration/read; no runtime mutation"
    reviews = [explicit_review(site, facts=site.unresolved, **options)
               for site in census["sites"]]
    reconcile_registry(census, reviews)


@pytest.mark.parametrize("new_path,source", [
    ("new_program.unseen", "custom mutation runtime\n"),
    ("runtime/entry.j2", "{{ executable_command }}\n"),
    ("Dockerfile.generated", "RUN psql -c 'DELETE FROM x'\n"),
    ("runtime.yaml", "service:\n  command: psql -c 'DELETE FROM x'\n"),
])
def test_new_executable_and_runtime_template_cannot_leave_scope_unchanged(tmp_path, new_path, source):
    _, _, ledger, _ = sql_fixture(tmp_path)
    write_sources(tmp_path, {new_path: source})
    changed = collect_source_primitives(tmp_path)
    assert any(row["path"] == new_path and row["language"] for row in changed["scope"])
    assert any(site.path == new_path for site in changed["sites"])
    with pytest.raises(SourcePrimitiveCoverageError, match="scope/dependency index"):
        reconcile_registry(changed, ledger)


def test_wasm_executable_bytes_are_fingerprinted_even_when_classified_as_asset(tmp_path):
    path = tmp_path / "runtime.wasm"
    first = b"\x00asm\x01\x00\x00\x00"
    path.write_bytes(first)
    rows, _ = collect_scope(tmp_path)
    row, = rows
    assert row.get("digest") == hashlib.sha256(first).hexdigest(), (
        "Executable WASM currently falls into static assets without a byte fingerprint"
    )
    path.write_bytes(first + b"\x00\x00")
    changed, _ = collect_scope(tmp_path)
    assert changed != rows


@pytest.mark.parametrize("mutation", ["path", "classification", "language", "digest", "missing", "extra"])
def test_normalized_scope_path_classification_and_hash_set_must_match_exactly(tmp_path, mutation):
    census, _, ledger, _ = sql_fixture(tmp_path)
    row, = ledger["scope"]
    if mutation in {"path", "classification", "language", "digest"}:
        row[mutation] = "unrecognized-value"
    elif mutation == "missing":
        ledger["scope"] = []
    else:
        ledger["scope"].append(dict(path="extra.py", classification="production-source",
                                    language="python", digest="0" * 64))
    with pytest.raises(SourcePrimitiveCoverageError, match="scope/dependency index: scope"):
        reconcile_registry(census, ledger)


def test_exact_frontend_build_cache_add_change_remove_never_reads_or_changes_census(tmp_path, monkeypatch):
    census, _, ledger, _ = sql_fixture(tmp_path)
    cache = tmp_path / "frontend/tsconfig.tsbuildinfo"
    cache.parent.mkdir()
    original = Path.read_bytes

    def read_bytes(path):
        assert path != cache, "Exact compiler cache must be excluded before byte access"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    for raw in (b"initial cache", b"changed cache\xff", None):
        if raw is None:
            cache.unlink()
        else:
            cache.write_bytes(raw)
        rows, sources = collect_scope(tmp_path)
        assert rows == census["scope"]
        assert set(sources) == {"owner.py"}
        actual = collect_source_primitives(tmp_path)
        assert actual == census
        reconcile_registry(actual, ledger)


def test_other_buildinfo_paths_remain_opaque_hashed_inputs(tmp_path):
    files = {"tsconfig.tsbuildinfo": "root cache\n",
             "other/tsconfig.tsbuildinfo": "other root\n",
             "frontend/other.tsbuildinfo": "other name\n"}
    write_sources(tmp_path, files)
    rows, sources = collect_scope(tmp_path)
    assert set(sources) == set(files)
    for row in rows:
        assert row["classification"] == "unsupported-source"
        assert row["language"] == "opaque"
        assert row["digest"] == hashlib.sha256(files[row["path"]].encode()).hexdigest()
    census = collect_source_primitives(tmp_path)
    assert {site.path for site in census["sites"]} == set(files)
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed source sites"):
        reconcile_registry(census, [])


def test_gitignored_new_shell_and_typescript_still_enter_source_scope(tmp_path):
    assert_node20()
    # A real ignore rule is source input too; it grants no exclusion to matching files.
    write_sources(tmp_path, {".gitignore": "*.sh\n*.ts\n"})
    before = collect_source_primitives(tmp_path)
    files = {"ignored-new.sh": "psql -c 'DELETE FROM x'\n",
             "frontend/ignored-new.ts": "export function write(db: any) { db.query('DELETE FROM x'); }\n"}
    write_sources(tmp_path, files)
    actual = collect_source_primitives(tmp_path)
    assert actual != before
    rows = {row["path"]: row for row in actual["scope"]}
    for path, source in files.items():
        assert rows[path]["classification"] == "production-source"
        assert rows[path]["digest"] == hashlib.sha256(source.encode()).hexdigest()
        assert any(site.path == path for site in actual["sites"])
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed source sites"):
        reconcile_registry(actual, [])
