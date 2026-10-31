"""Public API regression oracles, runnable against the old numbered-only producer."""

import pytest

from apps.backup.producer_capability import installed_migration_version
from tests.backup.migration_fingerprint_test_support import (
    DATA, HELPERS, INIT, NESTED_HELPER, ORPHAN, write_tree,
)


@pytest.mark.parametrize("helper", HELPERS)
def test_extracted_sql_helper_bytes_change_public_version(tmp_path, helper):
    root = write_tree(tmp_path.resolve() / "apps")
    helper = root / "backup" / "migrations" / helper
    before = installed_migration_version(root)
    original = helper.read_bytes()

    helper.write_bytes(original.replace(b"SELECT 1", b"SELECT 9"))

    assert installed_migration_version(root) != before


@pytest.mark.parametrize("helper", ["_0025_trigger_sql.py", "_0025_stage_sql.py"])
def test_reverse_only_change_and_rollback_are_both_attested(tmp_path, helper):
    root = write_tree(tmp_path.resolve() / "apps")
    path = root / "backup" / "migrations" / helper
    original = path.read_bytes()
    before = installed_migration_version(root)
    path.write_bytes(original.replace(b"SELECT 2", b"SELECT 0"))
    changed = installed_migration_version(root)
    assert changed != before

    path.write_bytes(original)

    assert installed_migration_version(root) == before
    assert installed_migration_version(root) != changed


@pytest.mark.parametrize("relative", [NESTED_HELPER, DATA, INIT, ORPHAN])
def test_helper_data_init_and_orphan_path_sets_are_attested(tmp_path, relative):
    root = write_tree(tmp_path.resolve() / "apps")
    path = root / relative
    original = path.read_bytes()
    baseline = installed_migration_version(root)

    path.write_bytes(original + b"\n# changed bytes\n")
    assert installed_migration_version(root) != baseline
    path.write_bytes(original)
    assert installed_migration_version(root) == baseline

    path.unlink()
    removed = installed_migration_version(root)
    assert removed != baseline
    path.write_bytes(original)
    assert installed_migration_version(root) == baseline

    renamed = path.with_name("renamed_" + path.name)
    path.rename(renamed)
    assert installed_migration_version(root) not in {baseline, removed}
    renamed.rename(path)
    assert installed_migration_version(root) == baseline

    added = path.with_name("new_" + path.name)
    added.write_bytes(original)
    assert installed_migration_version(root) != baseline
    added.unlink()
    assert installed_migration_version(root) == baseline
