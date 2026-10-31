"""Inspect raw setup Docker argv and simulate cache loss after trusted binding."""

import stat

from tests.runtime_image_provisioning_support import (
    A, B, OLD, OLD_PROOF, REPO, digest_in, events, fixture_host, run_host,
)


def test_setup_helper_docker_runs_and_application_start_explicitly_forbid_pulls(tmp_path):
    env = fixture_host(tmp_path)
    result = run_host(tmp_path, env, "setup.sh")
    assert result.returncode == 0, result.stderr
    calls = events(tmp_path)
    helper_runs = [call for call in calls if call["kind"] == "docker"
                   and call["args"][:1] == ["run"]]
    assert helper_runs
    for call in helper_runs:
        args = call["args"]
        assert args.count("--pull=never") == 1
        assert args[args.index("--entrypoint") + 1] in {"python", "sh", "test"}
        assert REPO + ":" + OLD in args
    # These are setup helpers, not update.sh's producer_marker shell commands.
    assert not any("/p/" in arg for call in helper_runs for arg in call["args"])
    assert sum("record-config" in call["args"] for call in helper_runs) == 12
    assert any("init-keys" in call["args"] for call in helper_runs)
    assert any("/app/scripts/install_producer_capability.py" in call["args"] for call in helper_runs)
    starts = [call for call in calls if call["kind"] == "compose" and call["args"][1:2] == ["up"]]
    assert len(starts) == 1
    assert starts[0]["args"] == ["bundled", "up", "-d", "--pull", "never"]
    assert starts[0]["digest"] == starts[0]["inherited"] == B


def cache_eviction_host(path):
    env = fixture_host(path)
    provider = path / "provider.py"
    source = provider.read_text()
    anchor = '    entrypoint = args[args.index("--entrypoint") + 1]\n'
    assert source.count(anchor) == 1
    # Only the Docker transport changes. Real setup/provisioning decisions still run.
    eviction = '''    if "record-config" in args and digest == "sha256:" + "b" * 64:
        image = repo + ":" + tag
        absent = root / "evicted-image"
        absent.write_text(image)
        with (root / "events.jsonl").open("a") as log:
            log.write(json.dumps(dict(event, kind="cache-eviction", image=image)) + "\\n")
        if absent.exists():
            never = "--pull=never" in args
            with (root / "events.jsonl").open("a") as log:
                log.write(json.dumps(dict(event, kind="cache-miss" if never else "implicit-pull",
                                          image=image)) + "\\n")
            if never:
                print("record-config image absent; --pull=never refused", file=sys.stderr)
                sys.exit(47)
            # Docker's default would implicitly pull and let the helper succeed.
            absent.unlink()
'''
    provider.write_text(source.replace(anchor, anchor + eviction))
    return env


def test_cache_eviction_at_record_helper_refuses_before_any_application_start(tmp_path):
    env = cache_eviction_host(tmp_path)
    dotenv = tmp_path / ".env"
    original = dotenv.read_bytes()
    pointer = (tmp_path / "ops/database-pointer.env").read_bytes()
    result = run_host(tmp_path, env, "setup.sh")
    assert result.returncode == 47
    assert "record-config image absent; --pull=never refused" in result.stderr
    calls = events(tmp_path)
    final_pull = next(i for i, call in enumerate(calls)
                      if call["kind"] == "compose" and call["args"] == ["bundled", "pull"])
    final_inspections = [i for i, call in enumerate(calls) if i > final_pull
                         and call["kind"] == "docker" and
                         call["args"] == ["image", "inspect", REPO + ":" + OLD]]
    assert len(final_inspections) == 2
    eviction, = [i for i, call in enumerate(calls) if call["kind"] == "cache-eviction"]
    assert final_inspections[-1] < eviction
    miss, = [call for call in calls if call["kind"] == "cache-miss"]
    assert miss["image"] == REPO + ":" + OLD
    assert miss["digest"] == miss["inherited"] == B
    assert "--pull=never" in miss["args"] and "record-config" in miss["args"]
    assert not any(call["kind"] == "implicit-pull" for call in calls)
    assert not any(call["kind"] == "compose" and call["args"][1:2] == ["up"] for call in calls)
    assert not any(call["args"][:1] == ["pull"] or call["args"] == ["bundled", "pull"]
                   for call in calls[final_inspections[-1] + 1:])
    assert (tmp_path / "evicted-image").read_text() == REPO + ":" + OLD
    assert digest_in(tmp_path) == B
    assert dotenv.read_bytes() == original.replace(A.encode(), B.encode())
    assert stat.S_IMODE(dotenv.stat().st_mode) == 0o600 and dotenv.stat().st_nlink == 1
    assert not list(tmp_path.glob(".runtime-image-*"))
    assert (tmp_path / "ops/database-pointer.env").read_bytes() == pointer
    assert (tmp_path / "host/public/producer-capability.json").read_bytes() == OLD_PROOF
    assert "synthetic-do-not-log" not in result.stdout + result.stderr
