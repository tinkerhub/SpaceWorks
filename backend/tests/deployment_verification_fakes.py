"""Extract real workflow programs; execute only against disposable host tools."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml


ROOT = Path("/workspace") if Path("/workspace/install.sh").exists() else Path(__file__).resolve().parents[2]
SHA = "a1" * 20
OTHER_SHA = "b2" * 20
CONTAINER = "c3" * 32
OTHER_CONTAINER = "d4" * 32
SENTINEL = "PRIVATE-payload-credential-sentinel"
BASH = shutil.which("bash") or "bash"


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())


def shell_step(job, index=0):
    return workflow()["jobs"][job]["steps"][index]["run"]


def shell_run(path, script, values, path_value=None):
    summary, output = path / "summary", path / "output"
    summary.write_text("")
    output.write_text("")
    # Do not inherit BASH_ENV, credentials or production install settings.
    env = {"PATH": path_value or os.defpath, "HOME": str(path), "LC_ALL": "C",
           "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(output), **values}
    result = subprocess.run([BASH, "--noprofile", "--norc", "-c", script], cwd=path,
                            env=env, capture_output=True, text=True, timeout=20)
    return result, summary.read_text(), output.read_text()


class InstalledHost:
    def __init__(self, path):
        self.path = path
        self.bin = path / "bin"
        self.bin.mkdir()
        scripts = path / "scripts"
        scripts.mkdir()
        self.marker = path / ".spaceworks-version"
        self.marker.write_text(f"1.2.3-main.42.{SHA[:12]}\n")
        self.config = {"container": [CONTAINER], "revision": [SHA], "ready": [0]}
        for tool in ("docker", "timeout", "sleep"):
            self.executable(self.bin / tool)
        self.executable(scripts / "spaceworks-compose.sh")

    @staticmethod
    def executable(path):
        path.write_text(f"#!{sys.executable}\n" + FAKE_TOOLS)
        path.chmod(0o755)

    def run(self, expected=SHA, **config):
        (self.path / "config.json").write_text(json.dumps({**self.config, **config}))
        return shell_run(self.path, shell_step("deploy", 1), {
            "EXPECTED_SHA": expected, "SPACEWORKS_INSTALL_DIR": str(self.path),
            "FAKE_HOST": str(self.path),
        }, str(self.bin))

    def calls(self):
        file = self.path / "calls.jsonl"
        return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


FAKE_TOOLS = r'''
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["FAKE_HOST"])
config = json.loads((root / "config.json").read_text())
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / "calls.jsonl").open("a") as file:
    file.write(json.dumps([name, *args]) + "\n")

def next_value(key):
    state = root / (key + ".count")
    count = int(state.read_text()) if state.exists() else 0
    state.write_text(str(count + 1))
    values = config[key]
    return values[min(count, len(values) - 1)]

if name == "timeout":
    assert args[:1] == ["--kill-after=5s"], args
    operation = Path(args[2]).name
    if operation == "spaceworks-compose.sh":
        assert args[1] == "20s"
        kind = "compose"
    else:
        assert operation == "docker"
        kind = args[3]
        assert args[1] == ("10s" if kind == "exec" else "20s")
    if config.get("timeout_operation") == kind:
        print("PRIVATE-payload-credential-sentinel", file=sys.stderr)
        sys.exit(124)
    sys.exit(subprocess.run(args[2:], timeout=3).returncode)
if name == "sleep":
    assert args == ["3"]
    sys.exit(0)
if name == "spaceworks-compose.sh":
    assert args == ["bundled", "ps", "-q", "backend"], args
    if config.get("compose_fail"):
        print("PRIVATE-payload-credential-sentinel", file=sys.stderr)
        sys.exit(1)
    print(next_value("container"))
elif name == "docker":
    if args[0] == "inspect":
        assert args[1:3] == ["--format", '{{ index .Config.Labels "org.opencontainers.image.revision" }}']
        assert args[3] == config["container"][0]
        if config.get("inspect_fail"):
            print("PRIVATE-payload-credential-sentinel", file=sys.stderr)
            sys.exit(1)
        print(next_value("revision"))
    elif args[0] == "exec":
        assert args[1] == config["container"][0]
        assert args[2:4] == ["python", "-c"] and len(args) == 5
        status = next_value("ready")
        if status == 0:
            if "mutate_marker" in config:
                (root / ".spaceworks-version").write_text(config["mutate_marker"])
            if config.get("remove_marker"):
                (root / ".spaceworks-version").unlink()
        print("PRIVATE-payload-credential-sentinel")
        print("PRIVATE-payload-credential-sentinel", file=sys.stderr)
        sys.exit(status)
    else:
        raise AssertionError(args)
else:
    raise AssertionError(name)
'''
