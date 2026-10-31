"""Synthetic age/Compose transport; actual sealed tar and signature admission run."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil

from apps.backup.full_format import FULL_FORMAT, FULL_PROTOCOL
from apps.backup.host_restore_prepare import RestoreInputs
from apps.backup.import_preflight import validate_import_preflight
from tests.backup.full_backup_fixture_helpers import sha
from tests.backup.recovery_test_support import RESTORE_ID, require_linux_root


@contextmanager
def isolated_host_state():
    """Explicit disposable-container lane only: never touch an installed host mount."""
    require_linux_root()
    assert os.environ.get("SPACEWORKS_TEST_PRIVATE_HOST_STATE") == "1", (
        "Use a disposable UID0 container with no /run/spaceworks-host bind mount; set SPACEWORKS_TEST_PRIVATE_HOST_STATE=1."
    )
    path = Path("/run/spaceworks-host")
    assert not path.exists(), "Private proof requires /run/spaceworks-host absent; do not remove or reuse live host authority."
    path.mkdir(mode=0o755)
    try:
        yield path
    finally:
        # Only the exact delegations produced by this proof; unknown files refuse cleanup.
        for item in path.iterdir():
            assert item.name.startswith("restore-prospective-") and item.suffix == ".json" and item.is_file()
            item.unlink()
        path.rmdir()


class InputTransport:
    def __init__(self, root, fixture, *, kind="disaster"):
        require_linux_root()
        self.root, self.fixture = root, fixture
        self.ops, self.host = root / "ops", root / "host"
        for directory in (self.ops / "work", self.host / "public"):
            directory.mkdir(mode=0o700, parents=True)
        self.events = []
        self.metadata = {"restore_id": RESTORE_ID, "archive_id": fixture.manifest["archive_id"],
            "archive_sha256": sha(fixture.encrypted.read_bytes()), "requested_by": 1, "kind": kind,
            "archive_scope": "deployment", "archive_format": FULL_FORMAT,
            "archive_protocol_version": FULL_PROTOCOL, "archive_partial": False}
        self.old_environment = dict(os.environ)

    def mapped(self, path):
        if path.startswith("/run/spaceworks-host/"):
            return self.host / "public" / path.removeprefix("/run/spaceworks-host/")
        return self.ops / "work" / path.removeprefix("/var/lib/spaceworks/ops/work/")

    def app_path(self, path):
        return "/var/lib/spaceworks/ops/work/" + str(path.relative_to(self.ops / "work"))

    def control(self, action, *args):
        self.events.append(action)
        if action == "describe":
            return json.dumps(self.metadata)
        if action == "export-archive":
            self.mapped(args[args.index("--output") + 1]).write_bytes(self.fixture.encrypted.read_bytes())
            return ""
        raise AssertionError((action, args))

    def compose(self, *args):
        if "age" in args:
            self.events.append("synthetic-age")
            shutil.copyfile(self.fixture.bundle, self.mapped(args[args.index("-o") + 1]))
            return ""
        command = next((name for name in ("preflight_backup_import", "import_backup_archive") if name in args), None)
        assert command is not None, args
        self.events.append((command, tuple(args), dict(os.environ)))
        # This is a read-only real Ed25519 / complete ledger validator. Only the
        # age and external Compose dispatch are synthetic; there is no PG dump claim.
        options = {}
        for flag, key in (("--encrypted-file", "encrypted_file"), ("--bundle", "bundle"),
            ("--manifest", "manifest_file"), ("--continuity-secrets", "continuity_secrets_file")):
            options[key] = self.mapped(args[args.index(flag) + 1])
        options["expected_sha256"] = args[args.index("--expected-sha256") + 1]
        if "--prospective-record" in args:
            fixed = Path(args[args.index("--prospective-record") + 1])
            # Model Docker's host/public -> /run/spaceworks-host read-only mapping
            # with a real root file. The actual validator checks fixed namespace,
            # ownership, mode, hash, key set and operation; none are patched.
            assert os.environ.get("SPACEWORKS_TEST_PRIVATE_HOST_STATE") == "1"
            raw = self.mapped(str(fixed)).read_bytes()
            if fixed.exists():
                assert fixed.read_bytes() == raw
            else:
                fixed.write_bytes(raw)
                fixed.chmod(0o444)
            options["prospective_record"] = fixed
        if "--restore-id" in args:
            options["restore_id"] = args[args.index("--restore-id") + 1]
        validate_import_preflight(**options, require_host_support=True)
        assert not list((self.ops / "private").glob("*/configuration.json"))
        if command == "import_backup_archive":
            assert dict(os.environ) == self.old_environment
            return RESTORE_ID  # Registration response only; DB registration has its own lane.
        return "import-preflight-ok"


def admitted_inputs(transport, *, imported=False):
    if imported:
        return RestoreInputs(transport, source=transport.fixture.encrypted, username="operator")
    return RestoreInputs(transport, restore_id=RESTORE_ID)
