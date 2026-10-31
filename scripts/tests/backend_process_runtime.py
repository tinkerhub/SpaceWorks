"""Disposable Docker process checks; never starts Compose application services."""

import json
from pathlib import Path
import re
import time
import uuid

from backend_process_inputs import ProbeError, require, run


# Executed inside the disposable container, never imports the application's WSGI.
READINESS = '''import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
import gunicorn

assert sys.version_info[:2] == (3, 12)
assert not pathlib.Path(gunicorn.__file__).is_relative_to("/probe")
deadline = time.monotonic() + 12
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
while True:
    try:
        with opener.open("http://127.0.0.1:8000/", timeout=0.5) as response:
            assert response.status == 200
            payload = json.load(response)
        assert payload["marker"] == "synthetic-worker-http"
        break
    except (OSError, urllib.error.URLError):
        if time.monotonic() >= deadline:
            raise SystemExit(25)
        time.sleep(0.1)

def parent(pid):
    lines = pathlib.Path(f"/proc/{pid}/status").read_text().splitlines()
    return int(next(line.split()[1] for line in lines if line.startswith("PPid:")))

def argv(pid):
    return [word.decode() for word in pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\\0") if word]

worker = payload["worker_pid"]
master = parent(worker)
print(json.dumps({"worker_pid": worker, "master_pid": master,
    "master_parent_pid": parent(master), "pid1_cmdline": argv(1),
    "master_cmdline": argv(master), "python": list(sys.version_info[:3]),
    "gunicorn_version": gunicorn.__version__, "http_marker": payload["marker"]}))
'''


class DockerProbe:
    def __init__(self, docker, image, probe_dir):
        self.docker, self.image, self.probe_dir = docker, image, probe_dir
        self.owner = uuid.uuid4().hex
        self.names = set()
        self.cleanup_records = []

    def cli(self, *args, timeout=15, check=True):
        # Real host Docker context here; render-only environment is never reused.
        return run([self.docker, *args], timeout=timeout, check=check)

    def inspect(self, target, *, missing_ok=False, timeout=5):
        result = self.cli("inspect", target, check=not missing_ok, timeout=timeout)
        if result.returncode and missing_ok:
            # A missing name is expected after successful per-case removal. A daemon
            # failure must not be silently reported as successful cleanup.
            require("no such object:" in result.stderr.casefold() or "no such container:" in result.stderr.casefold(),
                "cleanup inspect unavailable")
            return None
        try:
            rows = json.loads(result.stdout)
            require(isinstance(rows, list) and len(rows) == 1, "inspect shape invalid")
            return rows[0]
        except (ValueError, TypeError):
            raise ProbeError("inspect JSON invalid") from None

    def create(self, profile, variant, shell):
        name = f"backend-process-{self.owner}-{profile}-{variant}"
        # Track before create: if the CLI times out after daemon creation, finally
        # still finds ONLY this unique name and verifies its ownership label.
        self.names.add(name)
        result = self.cli("create", "--pull=never", "--name", name,
            "--label", "spaceworks.backend-process-probe=" + self.owner,
            "--network", "none", "--init=false", "--no-healthcheck", "--read-only",
            "--log-driver", "json-file", "--log-opt", "max-size=1m", "--log-opt", "max-file=1",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--entrypoint", "sh",
            "--workdir", "/probe", "--mount", f"type=bind,src={self.probe_dir},dst=/probe,readonly",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONUNBUFFERED=1",
            "--env", "PYTHONPATH=/probe", "--env", "GUNICORN_CMD_ARGS=",
            "--env", "PROBE_COLLECTSTATIC_FAIL=" + ("1" if variant == "collectstatic-fails" else "0"),
            self.image, "-c", shell)
        cid = result.stdout.strip()
        require(re.fullmatch(r"[0-9a-f]{64}", cid) is not None, "created container ID invalid")
        facts = self.inspect(cid)
        require(facts["Image"] == self.image, "container image changed")
        require(facts["Config"]["Entrypoint"] == ["sh"]
            and facts["Config"]["Cmd"] == ["-c", shell], "actual container command changed")
        host = facts["HostConfig"]
        require(host.get("Init") is False and host["NetworkMode"] == "none"
            and not host.get("PortBindings") and not host.get("PublishAllPorts"), "container isolation changed")
        require(not any((facts["NetworkSettings"].get("Ports") or {}).values()), "published ports found")
        mounts = facts["Mounts"]
        binds = [m for m in mounts if m.get("Destination") == "/probe"]
        require(len(binds) == 1 and binds[0]["Type"] == "bind" and binds[0]["RW"] is False
            and Path(binds[0]["Source"]).resolve() == self.probe_dir.resolve(), "probe mount changed")
        require(all(m["Destination"] == "/probe" or (m["Destination"] == "/tmp" and m["Type"] == "tmpfs")
            for m in mounts), "unexpected container mount")
        return cid, {"init": host["Init"], "network": host["NetworkMode"], "published_ports": False,
            "entrypoint": facts["Config"]["Entrypoint"], "command": facts["Config"]["Cmd"]}

    def wait_exit(self, cid, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            state = self.inspect(cid, timeout=max(0.1, min(2, remaining)))["State"]
            if not state["Running"]:
                return state
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        return None

    def remove(self, cid, *, force):
        facts = self.inspect(cid)
        require(facts["Config"].get("Labels", {}).get("spaceworks.backend-process-probe") == self.owner,
            "cleanup ownership mismatch")
        self.cli("rm", *(["--force"] if force else []), cid)
        self.cleanup_records.append({"container_id": cid, "forced": force})

    def cleanup(self):
        failures = 0
        for name in sorted(self.names):
            try:
                facts = self.inspect(name, missing_ok=True)
                if facts is not None:
                    self.remove(facts["Id"], force=True)
            except (ProbeError, KeyError, TypeError, ValueError):
                failures += 1
        require(failures == 0, "owned-container cleanup incomplete")

    def case(self, profile, variant, shell, record):
        cid, isolation = self.create(profile, variant, shell)
        record.update(container_id=cid, actual_command=isolation, readiness=False)
        self.cli("start", cid)
        if variant == "collectstatic-fails":
            state = self.wait_exit(cid, 5)
            require(state is not None and state["ExitCode"] == 23, "collectstatic failure exit changed")
            logs = self.cli("logs", cid)
            text = logs.stdout + logs.stderr
            require(text.count("PROBE_COLLECTSTATIC") == 1 and "PROBE_WSGI_LOADED" not in text
                and "Starting gunicorn" not in text, "failed collectstatic started Gunicorn")
            record.update(exit_status=23, gunicorn_started=False, status="passed")
            self.remove(cid, force=False)
            return
        try:
            ready = json.loads(self.cli("exec", cid, "python", "-c", READINESS, timeout=18).stdout)
        except ValueError:
            raise ProbeError("HTTP/process probe returned invalid JSON") from None
        record.update(readiness=True, process=ready)
        master = ready["master_cmdline"]
        require(master and "gunicorn" in " ".join(master)
            and not master[0].startswith("gunicorn: worker") and ready["worker_pid"] != ready["master_pid"],
            "HTTP was not served by a real Gunicorn worker")
        logs = self.cli("logs", cid)
        require("PROBE_COLLECTSTATIC" in logs.stdout + logs.stderr
            and "PROBE_WSGI_LOADED" in logs.stdout + logs.stderr, "startup markers missing")
        legacy = variant == "legacy-shell"
        if legacy:
            require(ready["master_pid"] != 1 and ready["master_parent_pid"] == 1
                and Path(ready["pid1_cmdline"][0]).name == "sh"
                and ready["pid1_cmdline"][1:] == ["-c", shell], "legacy shell PID 1 mechanism absent")
        else:
            require(ready["master_pid"] == 1 and ready["pid1_cmdline"] == master,
                "Gunicorn master is not PID 1")
        started = time.monotonic()
        self.cli("kill", "--signal=TERM", cid, timeout=2)
        state = self.wait_exit(cid, max(0.1, (2 if legacy else 10) - (time.monotonic() - started)))
        elapsed = time.monotonic() - started
        record.update(shutdown_seconds=round(elapsed, 3), term_stopped=state is not None)
        if legacy:
            require(state is None, "legacy negative control unexpectedly stopped on TERM")
            record.update(status="passed", shutdown="TERM deadline exceeded; forced cleanup required")
            self.remove(cid, force=True)
        else:
            require(state is not None and state["ExitCode"] == 0 and elapsed <= 10,
                "Gunicorn TERM did not produce bounded normal exit 0")
            record.update(exit_status=0, status="passed", shutdown="normal")
            self.remove(cid, force=False)
