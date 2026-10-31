"""Every mutation starts from a fully reconciled explicit synthetic review."""

import pytest

from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import SourcePrimitiveCoverageError
from apps.backup.source_primitive_registry import reconcile_registry
from .source_primitive_helpers import explicit_review, review_options, sql_fixture, write_sources


BASE = (
    "from adapter import cursor\n"
    "SQL = 'DELETE FROM x'\n"
    "def require_active(actor):\n    return actor.active\n"
    "def write(actor):\n    require_active(actor)\n"
    "    run = cursor.execute\n    run(SQL)\n"
)


@pytest.mark.parametrize("mutation", [
    "constant", "import", "alias", "rebind", "shadow", "branch", "boundary", "line",
])
def test_owner_import_constant_alias_and_boundary_changes_invalidate(tmp_path, mutation):
    write_sources(tmp_path, {"owner.py": BASE})
    census = collect_source_primitives(tmp_path)
    site, = census["sites"]
    assert (site.owner, site.category) == ("write", "raw_sql")
    reviewed = explicit_review(site, **review_options(tmp_path))
    reconcile_registry(census, [reviewed])
    changes = {
        "constant": BASE.replace("DELETE FROM x", "DELETE FROM y"),
        "import": BASE.replace("from adapter", "from other_adapter"),
        "alias": BASE.replace("run =", "alias =").replace("run(SQL)", "alias(SQL)"),
        "rebind": BASE.replace("    run(SQL)", "    run = cursor.executemany\n    run(SQL)"),
        "shadow": BASE.replace("def write(actor):", "def write(actor, cursor):"),
        "branch": BASE.replace("    run(SQL)", "    if actor:\n        run = cursor.executemany\n    run(SQL)"),
        "boundary": BASE.replace("return actor.active", "return True"),
        "line": "\n" + BASE,
    }
    write_sources(tmp_path, {"owner.py": changes[mutation]})
    changed = collect_source_primitives(tmp_path)
    actual = [s for s in changed["sites"] if s.source_symbol == site.source_symbol]
    assert len(actual) == 1 and actual[0].category == "raw_sql"
    assert actual[0].fingerprint != site.fingerprint
    if mutation == "branch":
        assert actual[0].unresolved
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        reconcile_registry(changed, [reviewed])


def test_new_caller_without_new_primitive_invalidates_whole_corpus_review(tmp_path):
    census, entry, ledger, _ = sql_fixture(tmp_path)
    write_sources(tmp_path, {"new_caller.py": "from owner import write\ndef bypass():\n    write()\n"})
    changed = collect_source_primitives(tmp_path)
    assert [s.source_symbol for s in changed["sites"]] == [s.source_symbol for s in census["sites"]]
    assert changed["call_index"] != census["call_index"]
    assert any(c["target"] == "owner.write" and c["owner"] == "bypass"
               for c in changed["call_index"])
    assert changed["sites"][0].fingerprint != census["sites"][0].fingerprint
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        reconcile_registry(changed, [entry])
    with pytest.raises(SourcePrimitiveCoverageError, match="scope/dependency index"):
        reconcile_registry(changed, ledger)


def test_private_path_prefix_is_part_of_the_review(tmp_path):
    original = "def path(token):\n    return f'evidence/{token}.jpg'\n"
    write_sources(tmp_path, {"path.py": original})
    census = collect_source_primitives(tmp_path)
    assert all(s.category == "generated_path" and s.owner == "path" for s in census["sites"])
    assert census["sites"]
    options = review_options(tmp_path)
    # Each actual literal/template candidate in this ONE inspected owner is explicit.
    reviews = [explicit_review(site, **options) for site in census["sites"]]
    reconcile_registry(census, reviews)
    write_sources(tmp_path, {"path.py": original.replace("evidence/", "private/")})
    changed = collect_source_primitives(tmp_path)
    assert len(changed["sites"]) == len(census["sites"])
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        reconcile_registry(changed, reviews)


@pytest.mark.parametrize("mutation,diagnostic", [
    ("file", "stale/orphan"), ("owner", "stale/orphan"),
    ("delete", "stale/orphan"), ("second-site", "new/unreviewed"),
])
def test_movement_deletion_and_added_site_are_not_auto_repaired(tmp_path, mutation, diagnostic):
    census, entry, _, _ = sql_fixture(tmp_path)
    path = tmp_path / "owner.py"
    source = path.read_text(encoding="utf-8")
    if mutation == "file":
        path.rename(tmp_path / "moved.py")
    elif mutation == "owner":
        path.write_text(source.replace("def write", "def renamed"), encoding="utf-8")
    elif mutation == "delete":
        path.unlink()
    else:
        path.write_text(source + "    cursor.execute('UPDATE x SET a=1')\n", encoding="utf-8")
    changed = collect_source_primitives(tmp_path)
    assert changed["sites"] != census["sites"]
    with pytest.raises(SourcePrimitiveCoverageError, match=diagnostic):
        reconcile_registry(changed, [entry])


def test_python_parse_failure_is_a_distinct_sanitized_diagnostic(tmp_path):
    sql_fixture(tmp_path)
    write_sources(tmp_path, {"owner.py": "def invalid( SECRET_SENTINEL\n"})
    with pytest.raises(SourcePrimitiveCoverageError, match="static parse failed: owner.py") as error:
        collect_source_primitives(tmp_path)
    assert "SECRET_SENTINEL" not in str(error.value)
