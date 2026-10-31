"""Existing-dotenv setup runs end to end against image/Compose transport doubles."""

import json

from tests.runtime_image_provisioning_support import (
    A, B, OLD, REPO, digest_in, events, fixture_host, run_host,
)


RECORD_NAMES = {
    "/ops/compose-topology.json", "/ops/compose-topology-build.json",
    "/ops/compose-topology-tls.json", "/ops/compose-topology-build-tls.json",
    "/ops/compose-topology-saas.json", "/ops/compose-topology-build-saas.json",
}


def records(calls):
    return [call for call in calls if "record-config" in call["args"]]


def assert_records(calls, digest):
    assert len(calls) == 6
    assert {call["args"][call["args"].index("--record") + 1] for call in calls} == RECORD_NAMES
    assert {call["digest"] for call in calls} == {digest}
    assert {call["inherited"] for call in calls} == {digest}


def test_existing_setup_rebinds_final_pull_and_all_six_records_before_raw_start(tmp_path):
    env = fixture_host(tmp_path)
    # A stale persisted value and an ambient override cannot stand in for inspection.
    stale = "sha256:" + "e" * 64
    dotenv = tmp_path / ".env"
    dotenv.write_text(dotenv.read_text().replace(A, stale))
    env["SPACEWORKS_OCI_DIGEST"] = stale
    result = run_host(tmp_path, env, "setup.sh")
    assert result.returncode == 0, result.stderr
    calls = events(tmp_path)
    prepare_pull = next(i for i, call in enumerate(calls) if call["kind"] == "docker"
                        and call["args"] == ["pull", REPO + ":" + OLD])
    final_pull = next(i for i, call in enumerate(calls) if call["kind"] == "compose"
                      and call["args"] == ["bundled", "pull"])
    starts = [i for i, call in enumerate(calls) if call["kind"] == "compose" and call["args"][1:2] == ["up"]]
    assert len(starts) == 1
    start = starts[0]
    assert prepare_pull < final_pull < start
    assert calls[start]["args"] == ["bundled", "up", "-d", "--pull", "never"]
    assert calls[start]["digest"] == calls[start]["inherited"] == B
    assert_records(records(calls[prepare_pull:final_pull]), A)
    assert_records(records(calls[final_pull:start]), B)
    final_inspects = [call for call in calls[final_pull:start] if call["args"][:2] == ["image", "inspect"]]
    assert len(final_inspects) == 2
    assert all(call["args"] == ["image", "inspect", REPO + ":" + OLD] for call in final_inspects)
    last_record = max(i for i, call in enumerate(calls[:start]) if "record-config" in call["args"])
    assert not any("pull" in call["args"] for call in calls[last_record + 1:start])
    assert any("init-keys" in call["args"] for call in calls[:start])
    assert digest_in(tmp_path) == B
    captures = list((tmp_path / "ops").glob("*.capture"))
    assert len(captures) == 6
    assert {json.loads(path.read_text())["digest"] for path in captures} == {B}
    assert "synthetic-do-not-log" not in result.stdout + result.stderr


def test_source_setup_clears_stale_identity_before_records_and_raw_build_start(tmp_path):
    env = fixture_host(tmp_path)
    env["SPACEWORKS_OCI_DIGEST"] = A
    result = run_host(tmp_path, env, "setup.sh", "--build")
    assert result.returncode == 0, result.stderr
    calls = events(tmp_path)
    start = next(i for i, call in enumerate(calls) if call["kind"] == "compose" and call["args"][1:2] == ["up"])
    assert calls[start]["args"] == ["bundled", "up", "-d", "--build", "--pull", "never"]
    assert calls[start]["digest"] == calls[start]["inherited"] == ""
    assert_records(records(calls[:start]), "")
    assert any(call["args"][:1] == ["build"] for call in calls[:start])
    assert not any(call["args"][:2] == ["image", "inspect"] or
                   ("pull" in call["args"] and not (call["kind"] == "compose" and
                    call["args"] == ["bundled", "pull", "--ignore-buildable"]))
                   for call in calls[:start])
    assert digest_in(tmp_path) == ""
    assert "signed FULL backup is unavailable" in result.stderr
