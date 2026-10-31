"""Lane E row 5: real independent discovery, no blanket parse-error success."""

import pytest

from apps.backup.source_primitive_guard import (
    SourcePrimitiveCoverageError, discover_whole_source_primitives,
    validate_whole_source_primitive_coverage,
)
from .source_primitive_helpers import explicit_review, review_options, write_sources


CASES = {
    "direct_raw_sql.py": (
        "def write(cursor):\n    cursor.execute('DELETE FROM x')\n",
        "write", "raw_sql", 2,
    ),
    "aliased_raw_sql.py": (
        "def write(cursor):\n    run = cursor.executemany\n"
        "    run('INSERT INTO x VALUES (%s)', [(1,)])\n",
        "write", "raw_sql", 3,
    ),
    "object_client.py": (
        "def write(s3):\n    s3.copy_object(Bucket='b', Key='k')\n",
        "write", "object_storage", 2,
    ),
    "settings_environment.py": (
        "import os\nfrom django.conf import settings as config\n"
        "VALUE = os.environ['SECRET_KEY']\nOTHER = config.AWS_STORAGE_BUCKET_NAME\n",
        "<module>", "settings_environment", 4,
    ),
    "generated_path.py": (
        "def path(owner, token):\n    return f'evidence/{owner}/{token}.jpg'\n",
        "path", "generated_path", 2,
    ),
    "mixed_semantic.py": (
        "def write(row, payload):\n    row.meta = payload\n    row.save()\n",
        "write", "mixed_semantic", 2,
    ),
    "direct_psql.sh": (
        "psql \"$DATABASE_URL\" -c 'UPDATE x SET value=1'\n",
        "<shell>", "shell_psql", 1,
    ),
}


@pytest.mark.parametrize("relative", tuple(CASES))
def test_each_unregistered_whole_source_primitive_fails_independently(relative, tmp_path):
    source, owner, category, line = CASES[relative]
    write_sources(tmp_path, {relative: source})
    discovered = discover_whole_source_primitives(tmp_path)
    candidates = [s for s in discovered if (s.path, s.owner, s.category, s.line)
                  == (relative, owner, category, line)]
    assert candidates, f"Missing independently expected {relative}/{owner}/{category}"
    assert all(s.source_symbol.startswith(f"{relative}::{owner}::{category}:")
               for s in candidates)
    if relative == "settings_environment.py":
        assert any(s.category == category and s.line == 3 for s in discovered)
    if relative == "mixed_semantic.py":
        assert any(s.category == category and s.line == 3 for s in discovered)
    with pytest.raises(SourcePrimitiveCoverageError, match="new/unreviewed source sites"):
        validate_whole_source_primitive_coverage(tmp_path, registry={})


def test_moving_a_reviewed_direct_use_invalidates_its_fingerprint(tmp_path):
    # Imported receiver is statically named, so this fixture has one exact site.
    source = "from adapter import cursor\ndef write():\n    cursor.execute('DELETE FROM x')\n"
    write_sources(tmp_path, {"reviewed.py": source})
    site, = discover_whole_source_primitives(tmp_path)
    assert (site.path, site.owner, site.category) == ("reviewed.py", "write", "raw_sql")
    reviewed = explicit_review(site, **review_options(tmp_path))
    registry = {reviewed.source_symbol: reviewed}
    assert validate_whole_source_primitive_coverage(tmp_path, registry) == [site]
    write_sources(tmp_path, {"reviewed.py": "\n" + source})
    moved, = discover_whole_source_primitives(tmp_path)
    assert moved.source_symbol == site.source_symbol
    assert moved.line == site.line + 1
    assert moved.fingerprint != site.fingerprint
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        validate_whole_source_primitive_coverage(tmp_path, registry)
