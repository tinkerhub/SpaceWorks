#!/usr/bin/env python3
"""Bind private Compose dotenv to an actual local backend RepoDigest (host only)."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COMPONENT = re.compile(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*")
REGISTRY = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]{1,5})?")
KEY = re.compile(rb"[ \t]*(?:export[ \t]+)?(?:SPACEWORKS_OCI_DIGEST|'SPACEWORKS_OCI_DIGEST'|\"SPACEWORKS_OCI_DIGEST\")[ \t]*=")
ENTRYPOINT = ["python", "/app/scripts/spaceworks_entrypoint.py"]
GUIDANCE = (
    "Publish and pull the actual backend image, rerun this helper with --env-file and "
    "--image repository:tag, then refresh trusted Compose records before starting with --pull never."
)


class ProvisionError(RuntimeError):
    """Safe operator-facing refusal; never contains inspect output or dotenv bytes."""


def repository(value):
    parts = value.split("/")
    explicit = len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost")
    registry = parts.pop(0) if explicit else "docker.io"
    if not REGISTRY.fullmatch(registry) or (
        ":" in registry and not 0 < int(registry.rsplit(":", 1)[1]) <= 65535
    ) or not parts or not all(COMPONENT.fullmatch(part) for part in parts):
        raise ProvisionError("unsupported_image_repository")
    if registry in {"docker.io", "index.docker.io"}:
        registry = "docker.io"
        if len(parts) == 1:
            parts.insert(0, "library")
    return registry + "/" + "/".join(parts)


def selected_repository(image):
    name, separator, tag = image.rpartition(":")
    if not separator or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise ProvisionError("expected_repository_and_tag")
    return repository(name)


def image_witness(image, selected):
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image], check=True, capture_output=True,
            text=True, timeout=30,
        )
        images = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ProvisionError("image_inspection_failed") from exc
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise ProvisionError("ambiguous_image_inspection")
    image_data = images[0]
    config = image_data.get("Config")
    witness = image_data.get("Id")
    if not isinstance(witness, str) or not DIGEST.fullmatch(witness):
        raise ProvisionError("invalid_image_witness")
    if not isinstance(config, dict) or config.get("Entrypoint") != ENTRYPOINT:
        raise ProvisionError("unexpected_backend_entrypoint")
    entries = image_data.get("RepoDigests")
    if not isinstance(entries, list) or not entries:
        raise ProvisionError("image_has_no_repository_digest")
    candidates = set()
    for entry in entries:
        if not isinstance(entry, str) or entry.count("@") != 1:
            raise ProvisionError("malformed_repository_digest")
        name, digest = entry.split("@")
        if not DIGEST.fullmatch(digest):
            raise ProvisionError("malformed_repository_digest")
        if repository(name) == selected:
            candidates.add(digest)
    if len(candidates) != 1:
        raise ProvisionError("missing_or_ambiguous_selected_repository_digest")
    return witness, candidates.pop()


def dotenv_payload(original, digest):
    lines = original.splitlines(keepends=True)
    positions, quote = [], None
    for index, line in enumerate(lines):
        if quote is not None:
            if quote_closed(line, quote):
                quote = None
            continue
        match = KEY.match(line)
        if match:
            positions.append(index)
        value = line.split(b"=", 1)[1].lstrip(b" \t") if b"=" in line and not line.lstrip().startswith(b"#") else b""
        if value[:1] in {b"'", b'"'} and not quote_closed(value[1:], value[0]):
            if match:
                raise ProvisionError("multiline_oci_digest_assignment")
            quote = value[0]
    if quote is not None:
        raise ProvisionError("unterminated_dotenv_quote")
    if len(positions) > 1:
        raise ProvisionError("duplicate_oci_digest_assignment")
    assignment = b"SPACEWORKS_OCI_DIGEST=" + digest.encode("ascii")
    if positions:
        index = positions[0]
        line = lines[index]
        ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
        lines[index] = assignment + ending
        return b"".join(lines)
    separator = b"" if not original or original.endswith(b"\n") else b"\n"
    return original + separator + assignment + b"\n"


def quote_closed(value, quote):
    escaped = False
    for byte in value:
        if escaped:
            escaped = False
        elif byte == 92:
            escaped = True
        elif byte == quote:
            return True
    return False


def file_witness(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def persist(path, image=None):
    selected = selected_repository(image) if image is not None else None
    actual = image_witness(image, selected) if image is not None else None
    digest = actual[1] if actual is not None else ""
    path = Path(os.path.abspath(path))
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".runtime-image-" + secrets.token_hex(12)
    temporary_created = False
    fd = None
    try:
        parent = os.fstat(directory)
        if parent.st_uid not in {0, os.geteuid()} or parent.st_mode & 0o022:
            raise ProvisionError("unsafe_dotenv_parent")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o077):
            raise ProvisionError("dotenv_must_be_private_owned_regular_single_link_file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        with os.fdopen(os.dup(fd), "rb") as source:
            original = source.read()
        payload = dotenv_payload(original, digest)
        target_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
        temporary_created = True
        with os.fdopen(target_fd, "wb") as target:
            os.fchown(target.fileno(), info.st_uid, info.st_gid)
            os.fchmod(target.fileno(), 0o600)
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        # The config Id is only a change witness; the persisted identity is RepoDigest.
        if image is not None and image_witness(image, selected) != actual:
            raise ProvisionError("selected_image_changed_during_provisioning")
        current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        parent_now = os.stat(path.parent, follow_symlinks=False)
        os.lseek(fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(fd), "rb") as source:
            unchanged = source.read() == original
        if (file_witness(current) != file_witness(info) or not unchanged
                or (parent_now.st_dev, parent_now.st_ino) != (parent.st_dev, parent.st_ino)):
            raise ProvisionError("dotenv_changed_during_provisioning")
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        try:
            os.fsync(directory)
        except OSError as exc:
            raise ProvisionError("dotenv_replaced_but_directory_fsync_failed_rerun_before_startup") from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            if temporary_created:
                os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)
    return digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--image")
    mode.add_argument("--clear", action="store_true")
    args = parser.parse_args(argv)
    try:
        digest = persist(args.env_file, args.image)
    except (ProvisionError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ProvisionError) else "dotenv_atomic_update_failed"
        print(f"Runtime image provisioning refused: {reason}. {GUIDANCE}", file=sys.stderr)
        return 1
    if args.clear:
        print(f"Source build: OCI identity cleared; signed FULL backup is unavailable. {GUIDANCE}", file=sys.stderr)
    print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
