"""Read-only prospective compatibility and installed-environment revalidation."""

import json
import os

import pytest

from apps.backup import import_preflight, storage
from apps.backup.host_restore_prepare import RestoreInputs
from apps.backup.import_preflight import ImportPreflightError, validate_import_preflight
from tests.backup.full_backup_fixture_helpers import make_full_fixture, sha, sign_manifest
from tests.backup.full_backup_preflight_helpers import configure_target
from tests.backup.recovery_input_support import InputTransport, isolated_host_state


def test_prospective_continuity_is_read_only_and_installed_values_must_agree(tmp_path, monkeypatch):
    fixture = make_full_fixture(tmp_path)
    probes = configure_target(monkeypatch, fixture)
    monkeypatch.setenv("SECRET_KEY", "target-secret-before-continuity-install")
    before = dict(os.environ)
    with isolated_host_state():
        transport = InputTransport(tmp_path / "target", fixture)
        inputs = RestoreInputs(transport, restore_id=transport.metadata["restore_id"])
        assert inputs.prospective is not None
        options = dict(fixture.kwargs(), prospective_record=inputs.prospective,
                       restore_id=inputs.restore_id, require_host_support=True)
        result = validate_import_preflight(**options)
        assert result.manifest == fixture.manifest
        assert len(probes) == 4  # Actual input admission and explicit delegated recheck.
        assert dict(os.environ) == before
        with pytest.raises(ImportPreflightError, match="settings_policy"):
            validate_import_preflight(**fixture.kwargs(), prospective_environment=False)
        assert dict(os.environ) == before
        monkeypatch.setenv("SECRET_KEY", fixture.secrets["SECRET_KEY"])
        validate_import_preflight(**fixture.kwargs(), prospective_environment=False)


@pytest.mark.parametrize("name,value", [
    ("API_CLIENT_AUTH_REQUIRED", "changed-target-policy"),
    ("CHECKIN_API_URL", "https://other-roster.invalid"),
    ("AUDIT_ATTESTATION_HTTP_BEARER_TOKEN", "target-owned-different"),
    ("EVENT_STATION_PIN_PEPPER", "target-owned-different"),
    ("SPACEWORKS_OCI_DIGEST", "sha256:" + "f" * 64),
])
def test_noncontinuity_security_values_remain_target_owned(tmp_path, monkeypatch, name, value):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    monkeypatch.setenv(name, value)
    before = dict(os.environ)
    with pytest.raises(ImportPreflightError, match="settings_policy|oci_identity"):
        validate_import_preflight(**fixture.kwargs())
    assert dict(os.environ) == before


@pytest.mark.parametrize("failure", ["signature", "build", "pg-target", "pg-client", "storage"])
def test_full_signature_build_pg_and_storage_refuse_without_mutation(tmp_path, monkeypatch, failure):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    if failure == "signature":
        fixture.manifest["archive_signature"]["value"] = "AA=="
    elif failure == "build":
        monkeypatch.setattr(import_preflight, "build_info", lambda: {"source_hash": "f" * 64})
    elif failure == "pg-target":
        monkeypatch.setattr(import_preflight, "server_major", lambda: 17)
    elif failure == "pg-client":
        fixture.manifest["postgres"]["client"] = "pg_dump (PostgreSQL) 17.4"
        fixture.manifest = sign_manifest(fixture.manifest)
    else:
        def unavailable():
            raise OSError("object store unavailable")

        monkeypatch.setattr(storage, "client", unavailable)
    fixture.write()
    before = dict(os.environ)
    with pytest.raises(ImportPreflightError):
        validate_import_preflight(**fixture.kwargs(), require_host_support=True)
    assert dict(os.environ) == before


@pytest.mark.parametrize("change", ["extra-trust-key", "missing", "bool", "newline", "nul"])
def test_signed_continuity_requires_exact_names_and_single_line_strings(tmp_path, monkeypatch, change):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    if change == "extra-trust-key":
        fixture.secrets["BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY"] = "archive-must-never-supply-trust"
    elif change == "missing":
        fixture.secrets.pop("PII_MASTER_KEY")
    else:
        fixture.secrets["SECRET_KEY"] = {"bool": True, "newline": "line\nbreak", "nul": "nul\x00byte"}[change]
    raw = json.dumps(fixture.secrets, sort_keys=True).encode()
    fixture.members["keys/env.json"] = raw
    next(item for item in fixture.manifest["contents"] if item["path"] == "keys/env.json").update(
        size=len(raw), sha256=sha(raw),
    )
    fixture.manifest = sign_manifest(fixture.manifest)
    fixture.write()
    before = dict(os.environ)
    with pytest.raises(ImportPreflightError, match="continuity_secret"):
        validate_import_preflight(**fixture.kwargs())
    assert dict(os.environ) == before
