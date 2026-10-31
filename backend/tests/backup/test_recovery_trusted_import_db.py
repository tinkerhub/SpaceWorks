"""Actual import command/services under OLD settings after sealed signed admission.

Compose/age and upload transport are synthetic. Ed25519, ledger, root delegation,
principal reload, durable registration and audit run without bypasses.
"""

from io import StringIO
import os
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup import storage
from apps.backup.import_preflight import ImportPreflightError
from apps.backup.models import BackupArchive, DeploymentRecoveryState, RestoreOperation
from tests.backup.full_backup_fixture_helpers import make_full_fixture
from tests.backup.full_backup_preflight_helpers import configure_target
from tests.backup.recovery_input_support import InputTransport, admitted_inputs, isolated_host_state


pytestmark = pytest.mark.django_db(transaction=True)


class RegisteringTransport(InputTransport):
    def compose(self, *args):
        if "import_backup_archive" not in args:
            return super().compose(*args)
        assert os.environ["SECRET_KEY"] == "old-installed-target"
        assert not list((self.ops / "private").glob("*/configuration.json"))
        assert list((self.ops / "private").glob("*/bundle/database.dump"))
        self.events.append(("real-registration", tuple(args), dict(os.environ)))
        argv = list(args[args.index("import_backup_archive") + 1:])
        for flag in ("--encrypted-file", "--bundle", "--manifest", "--continuity-secrets"):
            index = argv.index(flag) + 1
            argv[index] = str(self.mapped(argv[index]))
        # The prior static dispatch put the root delegation at its real fixed
        # container mount path. The validator consumes it without ACL patches.
        output = StringIO()
        call_command("import_backup_archive", *argv, stdout=output)
        identifier = output.getvalue().strip().splitlines()[-1]
        self.metadata["restore_id"] = identifier
        return identifier


@pytest.mark.parametrize("fault", [None, "signature", "ledger", "principal"])
def test_static_admission_precedes_provider_mutation_and_old_env_registration(tmp_path, settings, monkeypatch, fault):
    fixture = make_full_fixture(tmp_path)
    configure_target(monkeypatch, fixture)
    monkeypatch.setenv("SECRET_KEY", "old-installed-target")
    actor = User.objects.create_superuser(username="operator", password="unused")
    if fault == "signature":
        fixture.manifest["archive_signature"]["value"] = "AA=="
        fixture.write()
    elif fault == "ledger":
        fixture.write_tar(replacements={"database.dump": b"forged payload"})
    elif fault == "principal":
        User.objects.filter(pk=actor.pk).update(is_active=False)
    uploads = []
    def uploaded(key, path):
        assert os.environ["SECRET_KEY"] == "old-installed-target"
        assert not BackupArchive.objects.exists() and not RestoreOperation.objects.exists()
        assert Path(path).read_bytes() == fixture.encrypted.read_bytes()
        uploads.append(key)
    monkeypatch.setattr(storage, "upload_archive", uploaded)
    before = DeploymentRecoveryState.objects.values().get(pk=1)
    with isolated_host_state():
        t = RegisteringTransport(tmp_path / "target", fixture)
        if fault:
            with pytest.raises((ImportPreflightError, CommandError)):
                admitted_inputs(t, imported=True)
            assert uploads == []
            assert not BackupArchive.objects.exists() and not RestoreOperation.objects.exists()
            assert not AuditLog.objects.filter(action__startswith="backup.").exists()
        else:
            inputs = admitted_inputs(t, imported=True)
            row = RestoreOperation.objects.select_related("archive").get(pk=inputs.restore_id)
            assert row.kind == "disaster" and row.stage == "requested"
            assert row.requested_by_id == actor.pk
            assert row.archive.manifest == fixture.manifest
            assert len(uploads) == 1
            assert set(AuditLog.objects.filter(action__startswith="backup.").values_list("action", flat=True)) == {
                "backup.archive_imported", "backup.restore_requested"}
            events = [event[0] for event in t.events if isinstance(event, tuple)]
            assert events == ["preflight_backup_import", "real-registration"]
        assert os.environ["SECRET_KEY"] == "old-installed-target"
        assert DeploymentRecoveryState.objects.values().get(pk=1) == before
