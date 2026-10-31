"""Real updater/init/rollback shell decisions; only external transports are synthetic."""

import gzip

import pytest

from tests.runtime_image_provisioning_support import (
    A, B, NEW, NEW_PROOF, OLD, OLD_PROOF, REPO, digest_in, events, fixture_host,
    proof_hash, run_host,
)


def run_update(path, failure=""):
    env = fixture_host(path)
    env.update(PROVIDER_UPDATE="1", PROVIDER_FAILURE=failure,
               SPACEWORKS_OCI_DIGEST="sha256:" + "e" * 64)
    return run_host(path, env, "scripts/update.sh", "--no-module-changes")


def starts(calls, tag):
    return [i for i, call in enumerate(calls) if call["kind"] == "compose" and call["tag"] == tag
            and call["args"][1:3] == ["up", "-d"] and "db" not in call["args"]]


def records(calls, tag):
    return [call for call in calls if call["tag"] == tag and "record-config" in call["args"]]


def assert_records(calls, digest):
    assert len(calls) == 6
    assert {call["args"][call["args"].index("--record") + 1] for call in calls} == {
        "/ops/compose-topology" + suffix + ".json"
        for suffix in ("", "-build", "-tls", "-build-tls", "-saas", "-build-saas")
    }
    assert {call["digest"] for call in calls} == {digest}
    assert {call["inherited"] for call in calls} == {digest}


def assert_backup_and_saved_proof_precede_new_identity(calls):
    backup = next(i for i, call in enumerate(calls) if call["kind"] == "compose"
                  and call["args"][1:5] == ["exec", "-T", "db", "test"])
    save = next(i for i, call in enumerate(calls) if "cp -p /p/producer-capability.json" in " ".join(call["args"]))
    inspect = next(i for i, call in enumerate(calls) if call["args"] == ["image", "inspect", REPO + ":" + NEW])
    install = next(i for i, call in enumerate(calls) if "/app/scripts/install_producer_capability.py" in call["args"])
    assert backup < save < inspect < install
    assert calls[inspect]["saved_proof"] == proof_hash(OLD_PROOF)
    assert calls[inspect]["proof"] == proof_hash(OLD_PROOF)
    assert calls[backup]["inherited"] == ""  # Ambient OCI was cleared at updater entry.
    assert calls[inspect]["inherited"] == ""


def test_update_binds_new_tag_and_digest_before_raw_no_repull_start(tmp_path):
    result = run_update(tmp_path)
    assert result.returncode == 0, result.stderr
    calls = events(tmp_path)
    assert_backup_and_saved_proof_precede_new_identity(calls)
    start, = starts(calls, NEW)
    assert calls[start]["args"] == ["bundled", "up", "-d", "--pull", "never"]
    assert calls[start]["digest"] == B
    assert calls[start]["inherited"] == ""  # Child init persists dotenv; its export cannot reach this parent.
    assert calls[start]["proof"] == proof_hash(NEW_PROOF)
    assert_records(records(calls[:start], NEW), B)
    inspections = [i for i, call in enumerate(calls) if call["args"] == ["image", "inspect", REPO + ":" + NEW]]
    assert len(inspections) == 2
    assert inspections[-1] < min(i for i, call in enumerate(calls) if "record-config" in call["args"]) < start
    assert not any("pull" in call["args"] for call in calls[inspections[-1] + 1:start])
    assert not starts(calls, OLD)
    assert digest_in(tmp_path) == B
    assert (tmp_path / ".spaceworks-version").read_text() == NEW + "\n"
    assert not (tmp_path / "host/public/.producer-capability.previous").exists()
    assert not (tmp_path / ".spaceworks-update.lock").exists()


@pytest.mark.parametrize("failure", ["deploy", "old-identity", "old-records"])
def test_rollback_restores_proof_then_requires_old_identity_and_records_before_start(tmp_path, failure):
    result = run_update(tmp_path, failure)
    assert result.returncode == 37  # Cleanup must preserve the initial deployment failure.
    calls = events(tmp_path)
    assert_backup_and_saved_proof_precede_new_identity(calls)
    new_start, = starts(calls, NEW)
    assert calls[new_start]["args"] == ["bundled", "up", "-d", "--pull", "never"]
    assert calls[new_start]["digest"] == B
    assert calls[new_start]["inherited"] == ""  # Child init persists dotenv; its export cannot reach this parent.
    restore = next(i for i, call in enumerate(calls) if "mv -f /p/.producer-capability.previous" in " ".join(call["args"]))
    old_inspections = [i for i, call in enumerate(calls) if call["args"] == ["image", "inspect", REPO + ":" + OLD]]
    assert new_start < restore < old_inspections[0]
    assert calls[old_inspections[0]]["proof"] == proof_hash(OLD_PROOF)
    assert calls[restore]["saved_proof"] == proof_hash(OLD_PROOF)
    assert (tmp_path / "host/public/producer-capability.json").read_bytes() == OLD_PROOF
    assert (tmp_path / ".spaceworks-version").read_text() == OLD + "\n"
    backup, = (tmp_path / "backups").glob("pre-update-*.sql.gz")
    assert gzip.decompress(backup.read_bytes()) == b"synthetic database backup\n"
    installers = [call for call in calls if "/app/scripts/install_producer_capability.py" in call["args"]]
    assert len(installers) == 1
    assert installers[0]["tag"] == NEW
    assert not (tmp_path / ".spaceworks-update.lock").exists()
    assert "synthetic-do-not-log" not in result.stdout + result.stderr
    if failure == "deploy":
        old_start, = starts(calls, OLD)
        assert calls[old_start]["args"] == ["bundled", "up", "-d", "--pull", "never", "--no-deps", "backend", "worker", "beat", "frontend"]
        assert calls[old_start]["digest"] == calls[old_start]["inherited"] == A
        assert calls[old_start]["proof"] == proof_hash(OLD_PROOF)
        assert len(old_inspections) == 2
        assert_records(records(calls[old_inspections[-1]:old_start], OLD), A)
        assert not any("pull" in call["args"] for call in calls[old_inspections[-1] + 1:old_start])
        assert digest_in(tmp_path) == A
        assert "Rollback complete:" in result.stdout
    else:
        assert not starts(calls, OLD)
        assert "automatic rollback" in result.stdout and "failed" in result.stdout
        assert "Rollback complete:" not in result.stdout
        assert len(old_inspections) == (1 if failure == "old-identity" else 2)
        old_records = records(calls, OLD)
        assert len(old_records) == (0 if failure == "old-identity" else 1)
        assert digest_in(tmp_path) == (B if failure == "old-identity" else A)
