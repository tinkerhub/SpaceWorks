import hashlib
import json

import pytest

from apps.backup.compound_restore_types import (
    CompoundRestoreRefused,
    CompoundTopologyFacts,
)
from apps.backup.host_restore_capability import InstalledHostCapability
from apps.backup.outer_manifest import PROTOCOL_VERSION


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def installed_capability_case(tmp_path):
    script = tmp_path / "restore-host"
    entrypoint = tmp_path / "entrypoint"
    script.write_bytes(b"restore-v1")
    entrypoint.write_bytes(b"entrypoint-v1")
    tmp_path.chmod(0o700)
    script.chmod(0o600)
    entrypoint.chmod(0o600)
    record = tmp_path / "compound-capability.json"
    record.write_text(json.dumps({
        "version": 1,
        "compound_protocol": PROTOCOL_VERSION,
        "signing_key_fingerprint": "a" * 64,
        "migration_version": "backup.0022_target_import_recovery_mode",
        "topology_path": "bundled-compose",
        "writer_set": ["backend", "worker", "beat"],
        "installed_files": {
            "entrypoint": _digest(entrypoint),
            "restore-host": _digest(script),
        },
    }), encoding="utf-8")
    record.chmod(0o600)
    capability = InstalledHostCapability(
        record_path=record,
        installed_files={"restore-host": script, "entrypoint": entrypoint},
        installed_migration="backup.0022_target_import_recovery_mode",
        require_root_owned=False,
    )
    topology = CompoundTopologyFacts(
        "bundled-compose", True, True, True, True, True,
        ("backend", "worker", "beat"),
    )
    manifest = {"archive_signature": {"signer_fingerprint": "a" * 64}}

    return capability, topology, manifest, script, record


def test_installed_host_capability_binds_protocol_signer_migration_and_files(tmp_path):
    capability, topology, manifest, script, _record = installed_capability_case(tmp_path)
    assert capability.validate(
        inputs=object(), manifest=manifest, topology=topology
    )["validated"] is True

    script.write_bytes(b"modified-after-capability-install")
    with pytest.raises(CompoundRestoreRefused, match="does not match"):
        capability.validate(inputs=object(), manifest=manifest, topology=topology)
