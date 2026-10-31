"""Read the release-pinned restore guard as data; never import its host code."""

import ast
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


# Reviewed closure, not a second digest/signature authority. Digests live in restore.sh.
REVIEWED_PATHS = (
    "backend/apps/__init__.py",
    "backend/apps/backup/__init__.py",
    "backend/apps/backup/full_format.py",
    "backend/apps/backup/host_capability_journal.py",
    "backend/apps/backup/host_capability_types.py",
    "backend/apps/backup/host_marker.py",
    "backend/apps/backup/host_marker_file.py",
    "backend/apps/backup/host_pointer.py",
    "backend/apps/backup/host_private_file.py",
    "backend/apps/backup/host_restore_admission.py",
    "backend/apps/backup/host_restore_configuration.py",
    "backend/apps/backup/host_restore_files.py",
    "backend/apps/backup/host_restore_lifecycle.py",
    "backend/apps/backup/host_restore_prepare.py",
    "backend/apps/backup/host_restore_resume.py",
    "backend/apps/backup/host_restore_transport.py",
    "backend/apps/backup/host_run_ledger.py",
    "backend/apps/backup/host_supervisor.py",
    "backend/apps/backup/host_topology_record.py",
    "backend/apps/backup/inplace_marker.py",
    "backend/apps/backup/inplace_recovery_facts.py",
    "backend/apps/backup/operation_lock.py",
    "backend/apps/backup/restore_manifest_facts.py",
    "backend/apps/backup/topology.py",
    "scripts/restore-host.py",
)
GUARD_START = 'python3 -I -B - "$ROOT" <<\'PY_GUARD\'\n'


def safe_relative(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)
            or PurePosixPath(value).is_absolute() or ".." in value.split("/")
            or str(PurePosixPath(value)) != value or value == "."):
        raise ValueError("Noncanonical runtime path.")
    return value


def read_regular(root, relative, *, content=True):
    relative = safe_relative(relative)
    path = root / relative
    for directory in (root, *(root / part for part in PurePosixPath(relative).parents if str(part) != ".")):
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise ValueError(f"Linked or non-directory runtime parent: {relative}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Linked or nonregular runtime file: {relative}")
    if not content:
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_nlink) != (info.st_dev, info.st_ino, 1):
            raise ValueError(f"Runtime file changed during preflight: {relative}")
        return handle.read()


def declared_dependencies(source):
    if source.count(GUARD_START) != 1 or source.splitlines().count("PY_GUARD") != 1:
        raise ValueError("Missing or ambiguous exact PY_GUARD heredoc.")
    body = source.split(GUARD_START, 1)[1].split("\nPY_GUARD\n", 1)
    if len(body) != 2:
        raise ValueError("Unterminated PY_GUARD heredoc.")
    tree = ast.parse(body[0])
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == "EXPECTED"]
    stores = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
              and node.id == "EXPECTED" and isinstance(node.ctx, ast.Store)]
    if len(assignments) != 1 or len(stores) != 1 or not isinstance(assignments[0].value, ast.Dict):
        raise ValueError("EXPECTED must be one literal dictionary assignment.")
    mapping = assignments[0].value
    result = {}
    for key, value in zip(mapping.keys, mapping.values):
        if (not isinstance(key, ast.Constant) or not isinstance(value, ast.Constant)
                or not isinstance(value.value, str) or not re.fullmatch(r"[0-9a-f]{64}", value.value)):
            raise ValueError("EXPECTED contains nonliteral paths or invalid SHA256 data.")
        relative = safe_relative(key.value)
        if relative in result:
            raise ValueError("EXPECTED repeats a runtime path.")
        result[relative] = value.value
    if set(result) != set(REVIEWED_PATHS):
        raise ValueError("EXPECTED differs from the exact reviewed 25-file closure.")
    return result


def main():
    if len(sys.argv) < 2:
        raise ValueError("Expected staged source root and optional fixed runtime paths.")
    root = Path(sys.argv[1]).absolute()
    # The caller's original fixed runtime list is checked before any bundle writes.
    for relative in dict.fromkeys(("scripts/check-restore-host-bundle.py", *sys.argv[2:])):
        read_regular(root, relative, content=False)
    expected = declared_dependencies(read_regular(root, "scripts/restore.sh").decode("utf-8"))
    for relative in REVIEWED_PATHS:
        if hashlib.sha256(read_regular(root, relative)).hexdigest() != expected[relative]:
            raise ValueError(f"Restore source SHA256 differs: {relative}")
    # No partial stdout: installers may append this exact set only after success.
    print("\n".join(REVIEWED_PATHS))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
        print(f"Restore host bundle preflight refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
