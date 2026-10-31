"""Actual builder's serialized boundary; synthetic capture/age transport only."""

from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from apps.backup import archive_builder as builder
from apps.backup import producer_capability
from apps.backup.full_format import FULL_FORMAT
from apps.backup.host_marker import _assert_trusted_file
from apps.backup.recipient_selection import BackupBuildError
from tests.backup.recovery_test_support import require_linux_root


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("field", ["manifest", "continuity"])
@pytest.mark.parametrize("overflow", [False, True])
def test_serialized_caps_precede_tar_encryption_or_publication(monkeypatch, field, overflow):
    require_linux_root()
    # The shared conftest relaxes this producer-only ownership seam for legacy
    # tests. Restore the actual ACL check for this root lane; do not edit conftest.
    monkeypatch.setattr(producer_capability, "_assert_trusted_file", _assert_trusted_file)
    effects = []
    selected = [{"public_recipient": "synthetic-age-transport"}]
    manifest = {"format": FULL_FORMAT, "contents": []}
    continuity = b'{"SECRET_KEY":"synthetic-capture"}'
    real_write = builder._write_json

    def observed_write(path, value):
        real_write(path, value)
        monkeypatch.setattr(builder, "MANIFEST_MAX_BYTES", path.stat().st_size - int(field == "manifest" and overflow))

    class Capture:
        is_full = True
        def __init__(self, **_kwargs):
            pass
        def project_readable_main(self, value):
            return value
        def build_manifest(self, value):
            return value
        def promotion_snapshot(self):
            return {"synthetic": True}
        def cleanup_verifier_material(self):
            pass

    def snapshot(archive, root, *args, **kwargs):
        (root / "keys").mkdir()
        (root / "keys/env.json").write_bytes(continuity)
        (root / "database.dump").write_bytes(b"synthetic-capture")
        return dict(manifest)

    def encrypt(argv, **kwargs):
        effects.append("encryption")
        Path(argv[argv.index("-o") + 1]).write_bytes(b"synthetic-age-result")

    monkeypatch.setattr(builder, "_require_postgres_clients", lambda: None)
    monkeypatch.setattr(builder, "_require_binary", lambda _name: None)
    monkeypatch.setattr(builder.recipients, "selection_for", lambda _archive: selected)
    monkeypatch.setattr(builder, "_selection_at_read_committed", lambda _archive: selected)
    monkeypatch.setattr(builder, "_storage_modes", lambda: {})
    monkeypatch.setattr(builder, "DeploymentCapture", Capture)
    monkeypatch.setattr(builder, "_snapshot_payload", snapshot)
    monkeypatch.setattr(builder, "build_content_ledger", lambda _root: [])
    monkeypatch.setattr(builder, "_write_json", observed_write)
    monkeypatch.setattr(builder.subprocess, "run", encrypt)
    # Small limits exercise actual serialized file sizes through the entire
    # builder; the receiver test separately uses the real 64MiB/1MiB limits.
    monkeypatch.setattr(builder, "CONTINUITY_MAX_BYTES", len(continuity) - int(field == "continuity" and overflow))
    archive = SimpleNamespace(scope="deployment", id=uuid.uuid4())
    if overflow:
        with pytest.raises(BackupBuildError, match="fixed byte limits"):
            builder.build_archive(archive)
        assert effects == []
    else:
        result = builder.build_archive(archive)
        try:
            assert result.encrypted.read_bytes() == b"synthetic-age-result"
            assert effects == ["encryption"]
        finally:
            result.tempdir.cleanup()
