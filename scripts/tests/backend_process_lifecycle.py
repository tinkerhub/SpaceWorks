#!/usr/bin/env -S python3 -B
"""Operator-only, finite synthetic process probe; excluded from default pytest.

From the checkout on a Docker host, using an ALREADY LOCAL immutable image ID:
    python3 -B scripts/tests/backend_process_lifecycle.py \
        --image sha256:<64-lowercase-hex> --output /tmp/backend-process-fresh.json

--root optionally selects the checkout whose actual Compose sources are captured.
No pull/build, application entrypoint, Django import, DB, S3 or restore is performed.
Only nine uniquely labelled containers are created, with network none and no ports.
Evidence establishes synthetic command/process behavior, not application or restore
correctness. Requires installed Docker + Compose and a Python 3.12/Gunicorn image.
"""

import sys

# Set before importing local helpers, including when invoked without -B.
sys.dont_write_bytecode = True

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from backend_process_inputs import PROFILES, ProbeError, file_hashes, render_commands, require, write_probe
from backend_process_runtime import DockerProbe


def capture_sources(root):
    names = [*PROFILES.values(), "backend/Dockerfile",
        "backend/scripts/spaceworks_entrypoint.py",
        "backend/apps/backup/host_restore_admission.py", "docs/self-hosting.md"]
    paths = {name: root / name for name in names}
    for name in ("backend_process_lifecycle.py", "backend_process_inputs.py", "backend_process_runtime.py"):
        paths["probe-code/" + name] = Path(__file__).resolve().parent / name
    return paths


def exercise(args, report):
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", args.image) is not None,
        "--image must be an immutable local sha256 image ID")
    docker = shutil.which("docker")
    require(docker is not None, "installed Docker CLI required")
    root = args.root.resolve()
    sources = capture_sources(root)
    if args.compose_plugin_dir:
        plugin = (args.compose_plugin_dir / "docker-compose").resolve()
        require(plugin.is_file() and os.access(plugin, os.X_OK), "explicit Compose plugin unavailable")
        sources["compose-plugin"] = plugin
    before = file_hashes(sources)
    report["source_sha256_before"] = before
    with tempfile.TemporaryDirectory(prefix="backend-process-") as scratch:
        private = Path(scratch)
        probe = None
        fixed, fixed_before = {}, {}
        try:
            commands, rendered_hashes, render_inputs = render_commands(docker, root, private, args.compose_plugin_dir)
            report["rendered_config_sha256"] = rendered_hashes
            probe_dir = private / "probe"
            fixed = {**render_inputs, **write_probe(probe_dir)}
            fixed_before = file_hashes(fixed)
            report["fixed_input_sha256_before"] = fixed_before
            probe = DockerProbe(docker, args.image, probe_dir)
            # Local inspect only; --pull=never is also enforced at every create.
            image_result = probe.cli("image", "inspect", args.image)
            try:
                images = json.loads(image_result.stdout)
                require(isinstance(images, list) and len(images) == 1, "local image inspect shape invalid")
                image = images[0]
            except (ValueError, TypeError):
                raise ProbeError("local image inspect JSON invalid") from None
            require(image["Id"] == args.image and image["Os"] == "linux", "local Linux image ID mismatch")
            require(not image["Config"].get("Volumes"), "image declares unexpected persistent volumes")
            report["image_id"] = image["Id"]
            for profile, command in commands.items():
                shell = command[4]  # Prefix/length validated BEFORE extraction.
                legacy = shell.replace("&& exec gunicorn", "&& gunicorn", 1)
                require(legacy != shell and legacy.replace("&& gunicorn", "&& exec gunicorn", 1) == shell,
                    "legacy control must remove only exec")
                for variant, body in (("exec-master", shell), ("collectstatic-fails", shell), ("legacy-shell", legacy)):
                    require(file_hashes(sources) == before and file_hashes(fixed) == fixed_before,
                        "fixed inputs changed before case")
                    record = {"profile": profile, "variant": variant, "status": "incomplete",
                        "decoded_compose_command": command}
                    report["cases"].append(record)
                    try:
                        probe.case(profile, variant, body, record)
                    except Exception:
                        record["status"] = "failed"
                        raise
                    require(file_hashes(sources) == before and file_hashes(fixed) == fixed_before,
                        "fixed inputs changed during case")
        finally:
            try:
                if probe is not None:
                    try:
                        probe.cleanup()
                        report["cleanup"] = {"status": "passed", "containers": probe.cleanup_records}
                    except ProbeError:
                        report["cleanup"] = {"status": "failed", "containers": probe.cleanup_records}
                        raise
            finally:
                after = file_hashes(sources)
                report["source_sha256_after"] = after
                report["sources_unchanged"] = before == after
                fixed_after = file_hashes(fixed)
                report["fixed_input_sha256_after"] = fixed_after
                report["fixed_inputs_unchanged"] = fixed_before == fixed_after
                require(before == after and fixed_before == fixed_after, "source or synthetic inputs changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path, help="Fresh JSON path; existing files refused")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--compose-plugin-dir", type=Path, help="Explicit plugin directory for isolated Docker config")
    args = parser.parse_args()
    report = {"scope": "synthetic command/process only; no application or restore guarantee",
        "status": "failed", "cases": []}
    try:
        output = args.output.open("x", encoding="utf-8")
    except OSError:
        print("Fresh writable --output path required; existing files are never replaced.", file=sys.stderr)
        return 1
    with output:
        try:
            exercise(args, report)
            report["status"] = "passed"
        except ProbeError as error:
            report["failure"] = str(error)  # Only fixed, secret-free labels.
        except (Exception, KeyboardInterrupt):
            report["failure"] = "input or runtime fact invalid (details withheld)"
        finally:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    print("Synthetic backend process probe " + report["status"] + "; see JSON report.")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
