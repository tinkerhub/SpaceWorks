"""Actual RestoreInputs admission ordering, root copies and externally pinned crypto."""

import pytest

from apps.backup.host_restore_transport import RestoreHostError
from apps.backup.import_preflight import ImportPreflightError
from tests.backup.full_backup_fixture_helpers import make_full_fixture
from tests.backup.full_backup_preflight_helpers import configure_target
from tests.backup.recovery_input_support import InputTransport, admitted_inputs, isolated_host_state
from tests.backup.recovery_test_support import RESTORE_ID


@pytest.mark.parametrize("field,value", [
    ("archive_sha256", None), ("archive_sha256", ""), ("archive_sha256", "A" * 64),
    ("restore_id", "4511b438-1234-4c35-89ab-000000000000"),
    ("archive_scope", "makerspace"), ("archive_format", "unknown"),
    ("archive_protocol_version", "wrong"), ("archive_partial", True), ("archive_partial", 0),
    ("archive_id", "4511B438-1234-4C35-89AB-0123456789AB"),
    ("requested_by", True), ("kind", "unknown"),
])
def test_registered_identity_must_admit_before_export_decrypt_or_parse(tmp_path, field, value):
    fixture = make_full_fixture(tmp_path)
    t = InputTransport(tmp_path / "target", fixture)
    t.metadata[field] = value
    with pytest.raises(RestoreHostError):
        admitted_inputs(t)
    assert t.events == ["describe"]
    assert not list((t.ops / "private").glob("*/archive.tar*"))


@pytest.mark.parametrize("legacy", [False, True])
def test_changed_persisted_outer_digest_refuses_before_decryption(tmp_path, legacy):
    fixture = make_full_fixture(tmp_path)
    t = InputTransport(tmp_path / "target", fixture)
    if legacy:
        t.metadata.update(archive_format="spaceworks-phase5a-v1", archive_protocol_version="")
    t.metadata["archive_sha256"] = "f" * 64
    with pytest.raises(RestoreHostError, match="outer hash"):
        admitted_inputs(t)
    assert t.events == ["describe", "export-archive"]
    assert not list((t.ops / "private").glob("*/metadata"))


def test_registered_forged_metadata_refuses_before_static_preflight_or_extraction(tmp_path):
    fixture = make_full_fixture(tmp_path)
    t = InputTransport(tmp_path / "target", fixture)
    t.metadata["archive_id"] = "4511b438-1234-4c35-89ab-000000000000"
    with pytest.raises(RestoreHostError, match="registered archive"):
        admitted_inputs(t)
    assert t.events == ["describe", "export-archive", "synthetic-age"]
    assert not list((t.ops / "private").glob("*/bundle"))


@pytest.mark.parametrize("corruption", ["signature", "dump-ledger", "pinned-key"])
def test_real_signature_and_complete_tar_ledger_precede_full_extraction(tmp_path, monkeypatch, settings, corruption):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    if corruption == "signature":
        fixture.manifest["archive_signature"]["value"] = "AA=="
        fixture.write()
    elif corruption == "dump-ledger":
        fixture.write_tar(replacements={"database.dump": b"forged SQL bytes"})
    else:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        import base64

        settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY = base64.b64encode(
            Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    t = InputTransport(tmp_path / "target", fixture, kind="rollback_in_place")
    with pytest.raises(ImportPreflightError):
        admitted_inputs(t)
    assert any(isinstance(event, tuple) and event[0] == "preflight_backup_import" for event in t.events)
    assert not list((t.ops / "private").glob("*/bundle"))
    assert not any(isinstance(event, tuple) and event[0] == "import_backup_archive" for event in t.events)


def test_strict_rollback_uses_real_installed_keys_and_never_prospective(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    monkeypatch.setenv("SECRET_KEY", "installed-other-key")
    t = InputTransport(tmp_path / "target", fixture, kind="rollback_in_place")
    with pytest.raises(ImportPreflightError, match="settings_policy"):
        admitted_inputs(t)
    command = next(event[1] for event in t.events if isinstance(event, tuple))
    assert "--prospective-record" not in command and "--restore-id" not in command
    assert not list((t.ops / "private").glob("*/bundle"))


def test_valid_real_signed_rollback_reaches_complete_extraction(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    t = InputTransport(tmp_path / "target", fixture, kind="rollback_in_place")
    inputs = admitted_inputs(t)
    assert (inputs.private / "bundle/database.dump").read_bytes() == fixture.members["database.dump"]
    assert (inputs.private / "bundle/manifest.json").read_bytes() == (inputs.private / "metadata/manifest.json").read_bytes()
    assert inputs.prospective is None


@pytest.mark.parametrize("imported", [False, True])
def test_prospective_real_root_binding_for_disaster_or_initial_import(tmp_path, monkeypatch, imported):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    monkeypatch.setenv("SECRET_KEY", "old-installed-target")
    with isolated_host_state():
        t = InputTransport(tmp_path / "target", fixture)
        inputs = admitted_inputs(t, imported=imported)
        events = [event for event in t.events if isinstance(event, tuple)]
        preflight = events[0][1]
        assert ("--restore-id" in preflight) is (not imported)
        if not imported:
            assert preflight[preflight.index("--restore-id") + 1] == RESTORE_ID
        else:
            assert [event[0] for event in events] == ["preflight_backup_import", "import_backup_archive"]
            assert all(event[2]["SECRET_KEY"] == "old-installed-target" for event in events)
        assert (inputs.private / "bundle/database.dump").is_file()
