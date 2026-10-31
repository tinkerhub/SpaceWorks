"""Actual report bytes, with checkout-relative paths and bounded fixture support.

Report bindings are immutable snapshots, not approval decisions. Only the explicit
review constructors capture them; reconciliation re-reads and compares them.
"""

import os
from pathlib import Path
import stat
import tempfile

from .source_primitive_fingerprint import SourcePrimitiveCoverageError, bytes_digest, digest


REPORT_VERSION = "source-review-report-v1"


def _fail():
    raise SourcePrimitiveCoverageError("actual review report missing, unsafe or changed")


def _read_report(anchor, relative):
    """Keep every path lookup beneath a held directory; never follow links."""
    directory = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
                _fail()
            raw = handle.read()
            after = os.fstat(handle.fileno())
        if (before.st_size != len(raw) or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            _fail()
        return raw
    finally:
        os.close(directory)


def report_binding(root, report):
    """Hash a regular, nonempty report without following symlinks or reading secrets.

    Production reports must be checkout-relative. Disposable roots under the system
    temp directory may also use an absolute sibling report, as the explicit synthetic
    review helper does. A checkout with backend/apps and frontend never gets that
    exception, even when cloned under /tmp. No root path is persisted in the ledger.
    """
    from .source_primitive_scope import PRUNED, private_name

    if not isinstance(report, str) or not report.strip() or not root:
        _fail()
    root = Path(root).resolve()
    path = Path(report)
    if ".." in path.parts:
        _fail()
    if path.is_absolute():
        production = (root / "backend/apps").is_dir() and (root / "frontend").is_dir()
        temporary = any(root.is_relative_to(base.resolve()) for base in (
            Path(tempfile.gettempdir()), Path("/tmp")))
        if production or not temporary or path.parent.resolve() != root.parent:
            _fail()
        anchor, relative, identity = root.parent, Path(path.name), report
    else:
        if path.as_posix() != report or not path.parts:
            _fail()
        anchor, relative, identity = root, path, path.as_posix()
    for part in relative.parts:
        if part in PRUNED or private_name(part):
            _fail()
    try:
        raw = _read_report(anchor, relative)
    except (OSError, ValueError):
        _fail()
    return {"format_version": REPORT_VERSION, "path": identity,
            "sha256": bytes_digest(raw), "size": len(raw)}


def validate_report(root, report, expected):
    actual = report_binding(root, report)
    if (not isinstance(expected, dict) or type(expected.get("size")) is not int
            or expected != actual):
        _fail()
    return actual


def review_fingerprint(source_fingerprint, binding):
    """Bind the source review to the exact report identity and bytes."""
    return digest({"source_fingerprint": source_fingerprint, "report": binding})
