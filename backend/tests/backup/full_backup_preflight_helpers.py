"""Target seams for admission tests; real signature/bundle/settings policies run."""

from types import SimpleNamespace
import hashlib

from apps.backup import import_preflight, storage
from tests.backup.full_backup_fixture_helpers import BUILD, OCI


def configure_target(monkeypatch, fixture):
    for name, value in fixture.secrets.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SPACEWORKS_OCI_DIGEST", OCI)
    monkeypatch.setattr(import_preflight, "build_info", lambda: dict(BUILD))
    monkeypatch.setattr(import_preflight, "server_major", lambda: 16)
    probes = []
    monkeypatch.setattr(storage, "client", lambda: SimpleNamespace(
        head_bucket=lambda **kwargs: probes.append(kwargs),
    ))
    return probes


def command_options(fixture):
    return {
        "encrypted_file": str(fixture.encrypted), "bundle": str(fixture.bundle),
        "manifest": str(fixture.manifest_file), "continuity_secrets": str(fixture.secrets_file),
        "expected_sha256": hashlib.sha256(fixture.encrypted.read_bytes()).hexdigest(),
    }
