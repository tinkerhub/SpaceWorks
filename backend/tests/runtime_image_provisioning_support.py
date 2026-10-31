"""Synthetic image/Compose transport; host decisions remain in checked-in scripts."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
REPO = "registry.example:5443/team/backend"
OLD = "1.2.3-main.41.123456abcdef"
NEW = "1.2.3-main.42.abcdef123456"
A, B = ("sha256:" + character * 64 for character in "ab")
OLD_PROOF, NEW_PROOF = b'{"synthetic":"old"}\n', b'{"synthetic":"new"}\n'


def inspect_payload(digest=A, repo=REPO, witness="c"):
    return [{"Id": "sha256:" + witness * 64, "RepoDigests": [repo + "@" + digest],
             "Config": {"Entrypoint": ["python", "/app/scripts/spaceworks_entrypoint.py"]}}]


def executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def load_helper():
    spec = importlib.util.spec_from_file_location("runtime_image_host_helper", ROOT / "scripts/provision-runtime-image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_host(path):
    path.chmod(0o700)
    scripts, bin_dir = path / "scripts", path / "bin"
    scripts.mkdir()
    bin_dir.mkdir()
    for name in ("provision-runtime-image.py", "setup-host-orchestration.sh", "init-host-orchestration.sh",
                 "update.sh", "update-lock.sh", "module-selection.sh", "request-access-selection.sh",
                 "env-file.sh", "host-image.sh", "setup-deploy-runner.sh", "retire-update-polling.sh",
                 "retire-update-tombstone.sh", "install-host-bundle.sh", "refresh-proxy-config.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(ROOT / "setup.sh", path / "setup.sh")
    for directory in (path / "ops", path / "host", path / "host/public"):
        directory.mkdir(mode=0o700)
    (path / "host/public/producer-capability.json").write_bytes(OLD_PROOF)
    (path / "ops/database-pointer.env").write_text("DATABASE_URL='postgres://app:synthetic@db:5432/restored_db'\n")
    (path / ".spaceworks-version").write_text(OLD + "\n")
    dotenv = path / ".env"
    dotenv.write_text("SECRET_KEY=synthetic-do-not-log\nAPI_CLIENT_ENC_KEY=synthetic-key\n"
                      "AUDIT_MAC_MASTER_KEY=synthetic-audit\nPOSTGRES_APP_PASSWORD=synthetic-app\n"
                      "SPACEWORKS_SCHEDULER_MODE=image\nBACKUP_AGE_RECIPIENT=synthetic-age\n"
                      "BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY=synthetic-signing\n"
                      "BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY=synthetic-public\n"
                      "AUTH_COOKIE_SAMESITE=Lax\nAUTH_COOKIE_SECURE=False\n"
                      "MAKERSPACE_BACKEND_IMAGE=" + REPO + "\nSPACEWORKS_OCI_DIGEST=" + A + "\n")
    dotenv.chmod(0o600)
    (path / "payloads.json").write_text(json.dumps({REPO + ":" + OLD: [inspect_payload(A)],
                                                 REPO + ":" + NEW: [inspect_payload(B)],
                                                 REPO + ":latest": [inspect_payload(A)]}))
    driver = path / "provider.py"
    driver.write_text(PROVIDER)
    for command in ("docker", "curl", "crontab"):
        executable(bin_dir / command, "#!" + sys.executable + "\n" +
                   "import runpy,sys\nsys.argv.insert(1," + repr(command) + ")\nrunpy.run_path(" + repr(str(driver)) + ",run_name='__main__')\n")
    executable(scripts / "spaceworks-compose.sh", '#!/bin/sh\nexec "$PROVIDER_PYTHON" "$PROVIDER_DRIVER" compose "$@"\n')
    return {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "PROVIDER_ROOT": str(path), "PROVIDER_PYTHON": sys.executable, "PROVIDER_DRIVER": str(driver),
            "SPACEWORKS_OPS_HOST_DIR": str(path / "ops"), "SPACEWORKS_HOST_STATE_DIR": str(path / "host")}


def run_host(path, env, script, *args):
    return subprocess.run(["bash", str(path / script), *args], cwd=path, env=env,
                          capture_output=True, text=True, timeout=25)


def events(path):
    log = path / "events.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def digest_in(path):
    return next(line.split("=", 1)[1] for line in (path / ".env").read_text().splitlines()
                if line.startswith("SPACEWORKS_OCI_DIGEST="))


def proof_hash(value):
    return hashlib.sha256(value).hexdigest()


PROVIDER = r'''
import gzip, hashlib, json, os, shlex, subprocess, sys
from pathlib import Path
root = Path(os.environ["PROVIDER_ROOT"])
kind, args = sys.argv[1], sys.argv[2:]
repo = "registry.example:5443/team/backend"
old, new = "1.2.3-main.41.123456abcdef", "1.2.3-main.42.abcdef123456"
tag = os.environ.get("MAKERSPACE_IMAGE_TAG", old)
dotenv = root / ".env"
digest = next((line.split("=", 1)[1] for line in dotenv.read_text().splitlines()
               if line.startswith("SPACEWORKS_OCI_DIGEST=")), "")
proof = root / "host/public/producer-capability.json"
saved = proof.with_name(".producer-capability.previous")
event = {"kind": kind, "args": args, "tag": tag, "digest": digest,
         "inherited": os.environ.get("SPACEWORKS_OCI_DIGEST", ""),
         "saved_proof": hashlib.sha256(saved.read_bytes()).hexdigest() if saved.exists() else None,
         "proof": hashlib.sha256(proof.read_bytes()).hexdigest() if proof.exists() else None}
with (root / "events.jsonl").open("a") as log:
    log.write(json.dumps(event) + "\n")
failure = os.environ.get("PROVIDER_FAILURE", "")
if kind == "crontab":
    assert args == ["-l"]
elif kind == "curl":
    if "-o" in args:
        Path(args[args.index("-o") + 1]).write_text("# synthetic provider proxy\n")
    else:
        print(json.dumps({"tag_name": "v" + new}))
elif kind == "compose":
    assert args[0] == "bundled"
    command = args[1:]
    if command == ["pull"]:
        payloads = json.loads((root / "payloads.json").read_text())
        payloads[repo + ":" + old][0][0]["RepoDigests"] = [repo + "@sha256:" + "b" * 64]
        (root / "payloads.json").write_text(json.dumps(payloads))
    elif command == ["pull", "--ignore-buildable"]:
        pass
    elif command == ["pull", "backend", "worker", "beat", "frontend"]:
        pass
    elif command[:2] == ["up", "-d"]:
        if command != ["up", "-d", "--wait", "db"] and failure and tag == new:
            sys.exit(37)
    elif command[:1] == ["exec"] and "pg_dump" in command[-1]:
        import re
        name = re.search(r'/backups/(pre-update-[^"\s]+\.sql\.gz)', command[-1]).group(1)
        (root / "backups" / name).write_bytes(gzip.compress(b"synthetic database backup\n"))
    elif command[:4] == ["exec", "-T", "db", "test"]:
        assert (root / "backups" / Path(command[-1]).name).stat().st_size > 0
    elif command[:4] == ["exec", "-T", "backend", "python"] and "health/readiness/" in command[-1]:
        pass
    elif command == ["ps", "-q", "caddy"]:
        pass
    else:
        sys.exit(92)
elif kind == "docker" and args[:2] == ["image", "inspect"]:
    image = args[2]
    counts_path = root / "inspect-counts.json"
    counts = json.loads(counts_path.read_text()) if counts_path.exists() else {}
    count = counts.get(image, 0)
    counts[image] = count + 1
    counts_path.write_text(json.dumps(counts))
    if count == 1 and os.environ.get("PROVIDER_MUTATE_DOTENV"):
        dotenv.write_bytes(dotenv.read_bytes() + b"# concurrent edit\n")
    responses = json.loads((root / "payloads.json").read_text())[image]
    payload = responses[min(count, len(responses) - 1)]
    if failure == "old-identity" and tag == old:
        payload = [dict(payload[0], RepoDigests=[])]
    print(json.dumps(payload))
elif kind == "docker" and args[:1] == ["run"]:
    entrypoint = args[args.index("--entrypoint") + 1]
    if "record-config" in args:
        if failure == "old-records" and tag == old:
            sys.exit(41)
        record = Path(args[args.index("--record") + 1]).name
        # Transport capture only, not a forged configure-compose-wrapper result.
        (root / "ops" / (record + ".capture")).write_text(json.dumps(event))
    elif "init-keys" in args or entrypoint == "test":
        pass
    elif "/app/scripts/install_producer_capability.py" in args:
        if tag == old and os.environ.get("PROVIDER_UPDATE"):
            sys.exit(95)
        proof.write_bytes(b'{"synthetic":"new"}\n')
    elif entrypoint == "sh":
        command = args[args.index("-c") + 1]
        if "/p/" in command:
            # Execute the production marker shell command on private fixture proof bytes.
            translated = command.replace("/p/", shlex.quote(str(proof.parent)) + "/")
            sys.exit(subprocess.run(["sh", "-c", translated]).returncode)
        assert command.startswith("mkdir -p /ops/work && ")
    else:
        sys.exit(93)
elif kind == "docker" and args[:1] in (["pull"], ["build"]):
    pass
elif kind == "docker" and args in (["info"], ["compose", "version"]):
    pass
else:
    sys.exit(94)
'''
