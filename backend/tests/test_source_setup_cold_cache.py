"""Actual source setup against a cold image-cache transport, with real Compose config."""

import json
import os
import subprocess

import pytest

from tests.runtime_image_provisioning_support import (
    A, NEW_PROOF, OLD_PROOF, ROOT, digest_in, events, fixture_host, proof_hash, run_host,
)


BUILDABLE = {
    "backend", "orchestration-init", "orchestration-ready", "migrate",
    "worker", "beat", "candidate-backend", "frontend",
}


def cold_host(path, layer):
    # Only the real CLI's client-side config renderer runs; no daemon operations.
    render_home = path / "render-home"
    render_home.mkdir()
    render_env = {
        "PATH": os.environ["PATH"], "HOME": str(render_home),
        "DOCKER_CONFIG": str(render_home / "docker"),
        "POSTGRES_PASSWORD": "synthetic-postgres", "MINIO_ROOT_USER": "synthetic-minio",
        "MINIO_ROOT_PASSWORD": "synthetic-minio-password", "SECRET_KEY": "synthetic-secret",
        "ALLOWED_HOSTS": "example.invalid", "DATABASE_URL": "postgres://app:synthetic@db/app",
        "SPACEWORKS_DB_POINTER_GENERATION": "synthetic-generation",
    }
    files = [ROOT / "docker-compose.prod.yml", ROOT / "docker/compose.build.yml"]
    if layer != "build":
        files.append(ROOT / ("docker/compose." + layer.removeprefix("build-") + ".yml"))
    if layer == "build-tls":
        render_env.update(PUBLIC_DOMAIN="example.invalid", STORAGE_DOMAIN="files.example.invalid",
                          CSRF_TRUSTED_ORIGINS="https://example.invalid")
    command = ["docker", "compose", "--env-file", os.devnull, "--project-directory", str(ROOT),
               "--profile", "*"]
    for file in files:
        command.extend(["-f", str(file)])
    rendered = subprocess.run(command + ["config", "--format", "json"], cwd=path,
                              env=render_env, capture_output=True, text=True, timeout=30)
    assert rendered.returncode == 0, rendered.stderr
    services = json.loads(rendered.stdout)["services"]
    buildable = {name for name, service in services.items() if service.get("build")}
    assert buildable == BUILDABLE
    infrastructure = set(services) - buildable
    assert {"db", "redis", "minio", "createbuckets"} <= infrastructure
    assert ("caddy" in infrastructure) == (layer != "build")

    env = fixture_host(path)
    env.update(SPACEWORKS_COMPOSE_LAYER=layer, SPACEWORKS_OCI_DIGEST=A)
    (path / "services.json").write_text(json.dumps(services))
    (path / "cache.json").write_text(json.dumps({"images": [], "pulled": [], "built": [], "started": False}))
    (path / "provider.py").rename(path / "base-provider.py")
    (path / "provider.py").write_text(CACHE_PROVIDER)
    return env, services


def cache_state(path):
    return json.loads((path / "cache.json").read_text())


def cache_calls(path):
    return [json.loads(line) for line in (path / "cache-calls.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("layer", ["build", "build-tls", "build-saas"])
def test_source_setup_builds_apps_and_pulls_all_infrastructure_from_empty_cache(tmp_path, layer):
    env, services = cold_host(tmp_path, layer)
    assert cache_state(tmp_path)["images"] == []
    result = run_host(tmp_path, env, "setup.sh", "--build")
    # On the pre-fix source this fails here with genuine missing-infrastructure stderr.
    assert result.returncode == 0, result.stderr
    calls = cache_calls(tmp_path)
    compose = [call["args"] for call in calls if call["kind"] == "compose"]
    assert compose[:2] == [["bundled", "pull", "--ignore-buildable"],
                           ["bundled", "up", "-d", "--build", "--pull", "never"]]
    pull = next(i for i, call in enumerate(calls) if call["kind"] == "compose")
    assert calls[pull + 1] == {"kind": "compose", "args": compose[1]}
    assert sum(call[1:2] == ["up"] for call in compose) == 1
    assert not any("--ignore-pull-failures" in call["args"] for call in calls)
    assert not any(call["kind"] == "docker" and call["args"][:1] == ["pull"] or
                   call["args"][:2] == ["image", "inspect"] for call in calls)
    state = cache_state(tmp_path)
    infrastructure = set(services) - BUILDABLE
    assert set(state["pulled"]) == infrastructure
    assert len(state["pulled"]) == len(infrastructure)
    assert set(state["built"]) == {name for name in BUILDABLE if not services[name].get("profiles")}
    assert state["started"] is True
    assert {service["image"] for service in services.values()} <= set(state["images"])
    assert "spaceworks-host-configure:local" in state["images"]
    assert (tmp_path / ".spaceworks-layer").read_text().strip() == layer
    assert digest_in(tmp_path) == ""

    host_calls = events(tmp_path)
    records = [call for call in host_calls if "record-config" in call["args"]]
    assert len(records) == 6
    assert {call["args"][call["args"].index("--record") + 1] for call in records} == {
        "/ops/compose-topology" + suffix + ".json"
        for suffix in ("", "-build", "-tls", "-build-tls", "-saas", "-build-saas")
    }
    assert all(call["digest"] == call["inherited"] == "" for call in records)
    start = next(i for i, call in enumerate(host_calls) if call["kind"] == "compose"
                 and call["args"][1:2] == ["up"])
    assert all(call in host_calls[:start] for call in records)
    assert host_calls[start]["digest"] == host_calls[start]["inherited"] == ""
    assert host_calls[start]["proof"] == proof_hash(OLD_PROOF)
    installs = [i for i, call in enumerate(host_calls)
                if "/app/scripts/install_producer_capability.py" in call["args"]]
    assert len(installs) == 1 and installs[0] > start
    assert (tmp_path / "host/public/producer-capability.json").read_bytes() == NEW_PROOF
    assert "signed FULL backup is unavailable" in result.stderr
    assert "synthetic-do-not-log" not in result.stdout + result.stderr


def test_infrastructure_pull_failure_stops_source_setup_before_startup(tmp_path):
    env, _ = cold_host(tmp_path, "build")
    env["COLD_PULL_FAILURE"] = "redis"
    result = run_host(tmp_path, env, "setup.sh", "--build")
    assert result.returncode == 47, result.stderr
    assert "infrastructure pull failed: redis" in result.stderr
    calls = cache_calls(tmp_path)
    assert [call["args"] for call in calls if call["kind"] == "compose"] == [
        ["bundled", "pull", "--ignore-buildable"],
    ]
    state = cache_state(tmp_path)
    assert state["started"] is False and state["built"] == []
    assert not set(state["pulled"]) & BUILDABLE
    assert digest_in(tmp_path) == ""
    assert not any("/app/scripts/install_producer_capability.py" in call["args"] for call in calls)
    assert (tmp_path / "host/public/producer-capability.json").read_bytes() == OLD_PROOF


# This wrapper uses only the pre-existing host fixture/provider. It works unchanged
# when this file alone is added to the preserved pre-fix source frame.
CACHE_PROVIDER = r'''
import json, os, runpy, sys
from pathlib import Path
root = Path(os.environ["PROVIDER_ROOT"])
kind, args = sys.argv[1], sys.argv[2:]
services = json.loads((root / "services.json").read_text())
cache_path = root / "cache.json"
state = json.loads(cache_path.read_text())
images = set(state["images"])
with (root / "cache-calls.jsonl").open("a") as log:
    log.write(json.dumps({"kind": kind, "args": args}) + "\n")

def save():
    state["images"] = sorted(images)
    cache_path.write_text(json.dumps(state))

if kind == "docker" and args[:1] == ["build"]:
    images.add(args[args.index("-t") + 1])
    save()
elif kind == "docker" and args[:1] == ["run"]:
    assert "spaceworks-host-configure:local" in args
    assert "spaceworks-host-configure:local" in images, "host helper image was not built"
elif kind == "compose":
    assert args[0] == "bundled"
    command = args[1:]
    if command[:1] == ["pull"]:
        assert set(command[1:]) <= {"--ignore-buildable", "--ignore-pull-failures"}
        for name, service in services.items():
            if "--ignore-buildable" in command and service.get("build"):
                continue
            if name == os.environ.get("COLD_PULL_FAILURE"):
                save()
                print("infrastructure pull failed: " + name, file=sys.stderr)
                if "--ignore-pull-failures" in command:
                    continue
                sys.exit(47)
            images.add(service["image"])
            state["pulled"].append(name)
        save()
        # The old provider does not recognize this new infra-only command.
        sys.exit(0)
    if command[:1] == ["up"]:
        active = {name: service for name, service in services.items() if not service.get("profiles")}
        if "--build" in command:
            for name, service in active.items():
                if service.get("build"):
                    images.add(service["image"])
                    state["built"].append(name)
        missing = [name for name, service in active.items() if service["image"] not in images]
        if missing:
            save()
            print("cold cache: missing images for: " + ", ".join(sorted(missing)), file=sys.stderr)
            sys.exit(46)
        state["started"] = True
        save()
runpy.run_path(str(root / "base-provider.py"), run_name="__main__")
'''
