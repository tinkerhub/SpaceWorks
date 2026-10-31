"""Portable pre-P1 red case: only the two host source files are copied, if present."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "ghcr.io/spaceworks-hq/spaceworks-backend"
DIGEST = "sha256:" + "a" * 64


def test_default_published_prepare_binds_actual_repository_digest(tmp_path):
    tmp_path.chmod(0o700)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("setup-host-orchestration.sh", "provision-runtime-image.py"):
        source = ROOT / "scripts" / name
        if source.exists():
            shutil.copyfile(source, scripts / name)
    dotenv = tmp_path / ".env"
    dotenv.write_text("SPACEWORKS_SCHEDULER_MODE=image\nSECRET_KEY=synthetic-private\n")
    dotenv.chmod(0o600)
    provider = tmp_path / "docker"
    provider.write_text("#!" + sys.executable + "\n" + r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ["PROVIDER_ROOT"])
if args[:2] == ["image", "inspect"]:
    assert args[2:] == [os.environ["SELECTED_IMAGE"]]
    print(json.dumps([{
        "Id": "sha256:" + "c" * 64,
        "RepoDigests": [os.environ["SELECTED_REPO"] + "@" + os.environ["SELECTED_DIGEST"]],
        "Config": {"Entrypoint": ["python", "/app/scripts/spaceworks_entrypoint.py"]},
    }]))
elif args == ["pull", os.environ["SELECTED_IMAGE"]]:
    pass
elif args[:1] == ["run"]:
    entrypoint = args[args.index("--entrypoint") + 1]
    if "record-config" in args:
        assignments = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines()
                           if "=" in line and not line.startswith("#"))
        with (root / "records.jsonl").open("a") as log:
            log.write(json.dumps({"record": args[args.index("--record") + 1],
                                  "inherited": os.environ.get("SPACEWORKS_OCI_DIGEST", ""),
                                  "dotenv": assignments.get("SPACEWORKS_OCI_DIGEST", "")}) + "\n")
    elif entrypoint in {"sh", "test"} or "init-keys" in args:
        pass  # Provider already has a pointer and accepts its directory/key operations.
    else:
        sys.exit(93)
else:
    sys.exit(94)
''')
    provider.chmod(0o755)
    env = {"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
           "ROOT": str(tmp_path), "PROVIDER_ROOT": str(tmp_path),
           "SELECTED_IMAGE": REPOSITORY + ":latest", "SELECTED_REPO": REPOSITORY,
           "SELECTED_DIGEST": DIGEST, "HOST_CONFIG_IMAGE": REPOSITORY + ":latest",
           "SPACEWORKS_HOST_CONFIG_BUILD": "0", "SPACEWORKS_OPS_HOST_DIR": str(tmp_path / "ops"),
           "SPACEWORKS_HOST_STATE_DIR": str(tmp_path / "host")}
    completed = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; source "$ROOT/scripts/setup-host-orchestration.sh"; '
         'prepare_compose_wrapper'], env=env, capture_output=True, text=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    records = [json.loads(line) for line in (tmp_path / "records.jsonl").read_text().splitlines()]
    persisted = next((line.split("=", 1)[1] for line in dotenv.read_text().splitlines()
                      if line.startswith("SPACEWORKS_OCI_DIGEST=")), "")
    # Pre-P1 reaches this assertion with blank identity; no absent-helper import is needed.
    assert persisted == DIGEST
    assert len(records) == 6
    assert {record["dotenv"] for record in records} == {DIGEST}
    assert {record["inherited"] for record in records} == {DIGEST}
