"""Fail closed on untrusted entry types and bounded file-read faults."""

import os
from pathlib import Path

import pytest

from apps.backup.producer_capability import installed_migration_version
from tests.backup.migration_fingerprint_test_support import (
    ENTRYPOINT, TRIGGER, write_tree,
)


@pytest.mark.parametrize("relative", [
    ".", "backup", "backup/migrations", ENTRYPOINT, TRIGGER,
    "backup/migrations/lib", "backup/migrations/__pycache__",
    "backup/migrations/ignored.pyc", "backup/migrations/ignored.pyo",
])
def test_selected_symlinks_including_cache_names_refuse(tmp_path, relative):
    base = tmp_path.resolve()
    root = write_tree(base / "apps")
    installed_migration_version(root)
    selected = root if relative == "." else root / relative
    if selected.exists():
        destination = base / "displaced"
        selected.rename(destination)
    else:
        destination = base / "outside-data"
        destination.write_bytes(b"untrusted bytes")
    selected.symlink_to(destination, target_is_directory=destination.is_dir())

    # Deliberately pass the alias, without resolve(), for the ancestry oracle.
    with pytest.raises(OSError):
        installed_migration_version(root)


def test_unrelated_app_symlink_without_migrations_is_outside_inventory(tmp_path):
    base = tmp_path.resolve()
    root = write_tree(base / "apps")
    expected = installed_migration_version(root)
    outside = base / "unrelated"
    outside.mkdir()
    (root / "unrelated").symlink_to(outside, target_is_directory=True)

    assert installed_migration_version(root) == expected


@pytest.mark.parametrize("name", ["pipe", "__pycache__", "ignored.pyc", "ignored.pyo"])
def test_special_entries_are_classified_before_cache_exclusion(tmp_path, monkeypatch, name):
    if not hasattr(os, "mkfifo"):
        pytest.skip("This OS has no FIFO creation API")
    root = write_tree(tmp_path.resolve() / "apps")
    fifo = root / "backup" / "migrations" / name
    os.mkfifo(fifo)
    real_open = os.open

    def never_open_fifo(path, *args, **kwargs):
        if Path(path) == fifo:
            pytest.fail("FIFO must be rejected during entry classification, before open")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", never_open_fifo)

    # Inventory must reject the FIFO before any potentially blocking open.
    with pytest.raises(OSError, match="not a regular file or directory"):
        installed_migration_version(root)


def test_unreadable_helper_propagates_permission_failure(tmp_path, monkeypatch):
    root = write_tree(tmp_path.resolve() / "apps")
    helper = root / TRIGGER
    real_open = os.open

    def refuse_helper(path, *args, **kwargs):
        if Path(path) == helper:
            raise PermissionError("fixture denies migration helper read")
        return real_open(path, *args, **kwargs)

    # chmod alone is not an unreadability oracle when pytest runs as root.
    monkeypatch.setattr(os, "open", refuse_helper)
    with pytest.raises(PermissionError, match="fixture denies"):
        installed_migration_version(root)


def test_unreadable_nested_directory_is_not_silently_omitted(tmp_path, monkeypatch):
    root = write_tree(tmp_path.resolve() / "apps")
    nested = root / "backup" / "migrations" / "lib"
    real_scandir = os.scandir

    def refuse_nested(path):
        if Path(path) == nested:
            raise PermissionError("fixture denies nested traversal")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", refuse_nested)
    with pytest.raises(PermissionError, match="fixture denies nested traversal"):
        installed_migration_version(root)


@pytest.mark.parametrize("fault", ["different-inode", "short-read", "changed-after-read"])
def test_opened_identity_and_read_drift_fail_closed(tmp_path, monkeypatch, fault):
    base = tmp_path.resolve()
    root = write_tree(base / "apps")
    helper = root / TRIGGER
    original = helper.read_bytes()
    original_stat = helper.stat()
    replacement = base / "replacement"
    replacement.write_bytes(original)
    real_open, real_read, real_close = os.open, os.read, os.close
    opened, closed = [], []
    changed = False

    def open_helper(path, *args, **kwargs):
        if Path(path) == helper:
            path = replacement if fault == "different-inode" else path
            descriptor = real_open(path, *args, **kwargs)
            opened.append(descriptor)
            return descriptor
        return real_open(path, *args, **kwargs)

    def read_helper(descriptor, size):
        nonlocal changed
        if descriptor in opened:
            if fault == "short-read":
                return b""
            if fault == "changed-after-read" and not changed:
                chunk = real_read(descriptor, size)
                helper.write_bytes(original.replace(b"SELECT 1", b"SELECT 9"))
                os.utime(helper, ns=(original_stat.st_atime_ns,
                                     original_stat.st_mtime_ns + 1_000_000_000))
                changed = True
                return chunk
        return real_read(descriptor, size)

    def close_helper(descriptor):
        if descriptor in opened:
            closed.append(descriptor)
        return real_close(descriptor)

    monkeypatch.setattr(os, "open", open_helper)
    monkeypatch.setattr(os, "read", read_helper)
    monkeypatch.setattr(os, "close", close_helper)
    with pytest.raises(OSError, match="changed while|size changed"):
        installed_migration_version(root)
    assert len(opened) == 1
    assert closed == opened
