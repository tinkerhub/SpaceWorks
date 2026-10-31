"""Actual controller helpers; Docker, age, SQL and registration are synthetic.

No shell replacement, ownership mock, private guard bypass or host attestation.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import signal
import stat
import subprocess
import sys
from unittest.mock import patch

from apps.backup.host_marker import read_marker
from apps.backup.host_restore_transport import RestoreTransport
from apps.backup.import_preflight import validate_import_preflight
from tests.backup.full_backup_fixture_helpers import sha
from tests.backup.full_backup_preflight_helpers import configure_target
from tests.backup.recovery_input_support import InputTransport, isolated_host_state
from tests.backup.recovery_test_support import RESTORE_ID, marker_rig, repo_root
from tests.backup.recovery_transport_support import SyntheticTransport


class HostTransport(SyntheticTransport, InputTransport):
    """Join the new read-only helpers at their external transport boundary only."""

    def __init__(self, rig, root, fixture):
        self.fixture = fixture
        super().__init__(rig, root)
        self.old_environment = dict(os.environ)
        self.metadata = {"restore_id": RESTORE_ID, "archive_id": fixture.manifest["archive_id"],
            "archive_sha256": sha(fixture.encrypted.read_bytes()), "requested_by": 1, "kind": "disaster",
            "archive_scope": fixture.manifest["scope"], "archive_format": fixture.manifest["format"],
            "archive_protocol_version": fixture.manifest["protocol_version"], "archive_partial": False}
        self.trace = []
        self.preflights = 0
        self.second_token = "full-preflight-ok"

    def resolved(self, path):
        config = super().resolved(path)
        for role in ("backend", "worker", "beat"):
            config["services"][role]["environment"]["SPACEWORKS_OCI_DIGEST"] = self.fixture.manifest["oci_digest"]
        return config

    def image(self, reference):
        image = super().image(reference)
        if reference == "app:fixed":
            image["RepoDigests"] = ["synthetic@" + self.fixture.manifest["oci_digest"]]
        return image

    def observe(self, name, args=(), **extra):
        # Every actual controller transport phase must remain inside the same
        # host lock; the child cannot inherit its descriptor and claim success.
        contender = """import fcntl,sys
with open(sys.argv[1], 'a+') as lock:
    try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: sys.exit(73)
sys.exit(0)
"""
        held = subprocess.run([sys.executable, "-I", "-B", "-c", contender,
            str(self.ops / "operation.lock")], close_fds=True, capture_output=True, timeout=10)
        assert held.returncode == 73, (name, held.stderr)
        assert name != "control:cleanup-rollback"
        self.trace.append({"name": name, "args": args, "environment": self.static_env.read_bytes(),
            "marker": read_marker(self.rig.marker).state, "running": set(self.running), **extra})

    def mirror_prospective(self, path):
        # Model Docker's read-only bind view with genuine root-owned 0444 bytes.
        # Registration legitimately refreshes this record to bind the returned UUID.
        fixed = Path(path)
        assert fixed.parent == Path("/run/spaceworks-host")
        assert os.environ.get("SPACEWORKS_TEST_PRIVATE_HOST_STATE") == "1"
        source = self.mapped(path)
        facts = source.stat(follow_symlinks=False)
        assert stat.S_ISREG(facts.st_mode) and facts.st_uid == 0 and facts.st_nlink == 1
        assert stat.S_IMODE(facts.st_mode) == 0o444
        fixed.write_bytes(source.read_bytes())
        fixed.chmod(0o444)

    def compose(self, *args, **kwargs):
        if args[0] in {"stop", "up", "config"}:
            self.observe("compose:" + args[0], args)
        admission = next((name for name in ("preflight_backup_import", "import_backup_archive") if name in args), None)
        if admission or "age" in args:
            if "--prospective-record" in args:
                self.mirror_prospective(args[args.index("--prospective-record") + 1])
            self.observe(admission or "synthetic-age", args)
            return InputTransport.compose(self, *args)
        if "SPACEWORKS_GRANTS_ONLY=1" in args:
            self.observe("synthetic-grants", args, identity=kwargs.get("input_bytes"))
            self.hit("grants")
            return ""
        return super().compose(*args, **kwargs)

    def control(self, action, *args):
        self.observe("control:" + action, args)
        if action in {"describe", "export-archive"}:
            return InputTransport.control(self, action, *args)
        if action == "preflight":
            self.preflights += 1
            # Model the one-shot management process's resolved environment. Run
            # the real externally pinned Ed25519 and complete ledger validator;
            # the registered DB command's response token remains synthetic.
            options = {key: self.mapped(args[args.index(flag) + 1]) for flag, key in (
                ("--encrypted-file", "encrypted_file"), ("--decrypted-bundle", "bundle"),
                ("--manifest", "manifest_file"), ("--continuity-secrets", "continuity_secrets_file"))}
            options["expected_sha256"] = self.metadata["archive_sha256"]
            if "--prospective-record" in args:
                record = args[args.index("--prospective-record") + 1]
                self.mirror_prospective(record)
                options.update(prospective_record=record, restore_id=RESTORE_ID)
            environment = self.config["services"]["backend"]["environment"]
            with patch.dict(os.environ, environment):
                validate_import_preflight(**options, require_host_support=True)
            return self.second_token if self.preflights == 2 else "full-preflight-ok"
        if action == "export-control":
            # Synthetic registration/control payload, never a DB identity proof.
            self.mapped(args[args.index("--output") + 1]).write_text(json.dumps({
                "full_target_identity": self.probe()["target_record"]}))
            return ""
        return super().control(action, *args)

    def sql(self, command, **kwargs):
        self.observe("synthetic-sql", (command,))
        return super().sql(command, **kwargs)

    def grants(self, **kwargs):
        # Exercise the actual fixed bootstrap argument and stdin construction.
        return RestoreTransport.grants(self, **kwargs)


@contextmanager
def host_case(tmp_path, monkeypatch, fixture):
    configure_target(monkeypatch, fixture)  # Synthetic build/PG/storage probes only.
    for name in fixture.secrets:
        monkeypatch.setenv(name, "old-" + name)
    with isolated_host_state():
        # Release setup's real flock so main() acquires the same inode itself.
        with marker_rig(tmp_path) as rig:
            pass
        yield rig, HostTransport(rig, tmp_path, fixture)


def run_controller(monkeypatch, transport, *args):
    """Real main/lock/marker/admission/lifecycle, substituting external I/O only.

    Shell source/installed-root guard coverage belongs to copied-install tests;
    this helper neither executes that guard nor claims to have satisfied it.
    """
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGHUP, signal.SIGTERM)}
    search_path = list(sys.path)
    try:
        namespace = runpy.run_path(str(repo_root() / "scripts/restore-host.py"))
        namespace["main"].__globals__["RestoreTransport"] = lambda _root: transport
        monkeypatch.setattr(sys, "argv", ["restore-host.py", *map(str, args)])
        return namespace["main"]()
    finally:
        sys.path[:] = search_path
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
