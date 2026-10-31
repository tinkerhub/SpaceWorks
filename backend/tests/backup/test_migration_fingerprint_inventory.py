"""Inventory boundaries and deterministic wire framing through the public API."""

from contextlib import contextmanager
import hashlib
import os
import struct

import pytest

from apps.backup.producer_capability import installed_migration_version
from tests.backup.migration_fingerprint_test_support import tree_files, write_tree


def test_exact_length_framing_of_paths_and_raw_bytes(tmp_path):
    files = {
        "sample/migrations/__init__.py": b"\x00init\xff",
        "sample/migrations/0001_initial.py": b"abc\x00def\n",
    }
    root = write_tree(tmp_path.resolve() / "apps", files)
    framed = b"spaceworks-django-migrations-v1\x00"
    for relative in sorted(files):
        path, content = relative.encode("utf-8"), files[relative]
        framed += struct.pack(">Q", len(path)) + path
        framed += struct.pack(">Q", len(content)) + content

    expected = "django-migrations-v1:" + hashlib.sha256(framed).hexdigest()
    assert installed_migration_version(root) == expected


def test_creation_traversal_order_and_resolved_root_do_not_change_digest(
    tmp_path, monkeypatch
):
    files = tree_files()
    first = write_tree(tmp_path.resolve() / "first", files)
    second = write_tree(tmp_path.resolve() / "second", dict(reversed(list(files.items()))))
    expected = installed_migration_version(first)
    real_scandir = os.scandir

    @contextmanager
    def reversed_scandir(path):
        with real_scandir(path) as entries:
            yield iter(reversed(list(entries)))

    monkeypatch.setattr(os, "scandir", reversed_scandir)
    assert installed_migration_version(first) == expected
    assert installed_migration_version(second) == expected


def test_regular_compiler_caches_are_inert(tmp_path):
    root = write_tree(tmp_path.resolve() / "apps")
    expected = installed_migration_version(root)
    package = root / "backup" / "migrations"
    caches = [package / "helper.pyc", package / "lib" / "helper.pyo",
              package / "__pycache__" / "0001_fake.py"]
    for path in caches:
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"compiler output")
    assert installed_migration_version(root) == expected
    for path in caches:
        path.write_bytes(b"changed compiler output")
    assert installed_migration_version(root) == expected
    for path in caches:
        path.unlink()
    assert installed_migration_version(root) == expected


@pytest.mark.parametrize("files", [
    {},
    {"orphan/migrations/helper.py": b"helper only"},
    {"orphan/migrations/nested/0001_fake.py": b"numbered asset, not entrypoint"},
])
def test_only_direct_numbered_entrypoint_satisfies_minimum(tmp_path, files):
    root = tmp_path.resolve() / "apps"
    root.mkdir()
    write_tree(root, files)
    with pytest.raises(OSError, match="no installed numbered migration"):
        installed_migration_version(root)


def test_missing_root_fails_closed(tmp_path):
    with pytest.raises(OSError):
        installed_migration_version(tmp_path.resolve() / "missing")
