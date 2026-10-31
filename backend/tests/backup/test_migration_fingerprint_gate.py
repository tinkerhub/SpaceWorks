"""Real producer checks retain installer authority after migration-package drift."""

import hashlib
import json
from types import SimpleNamespace
import uuid

import pytest

from apps.backup import archive_builder, artifact_ledger, producer_capability
from tests.backup.migration_fingerprint_test_support import (
    DATA, TRIGGER, install_tree, regenerate_marker,
)


@pytest.mark.parametrize("change", ["forward", "reverse-rollback", "data", "rename"])
def test_helper_drift_requires_explicit_marker_regeneration(
    installed_producer_capability, settings, change
):
    installation = installed_producer_capability
    root = install_tree(installation, settings)
    accepted = producer_capability.assert_producer_capability()
    marker_before = installation["marker"].read_bytes()
    helper = root / TRIGGER
    if change == "forward":
        helper.write_bytes(helper.read_bytes().replace(b"SELECT 1", b"SELECT 9"))
    elif change == "reverse-rollback":
        helper.write_bytes(helper.read_bytes().replace(b"SELECT 2", b"SELECT 0"))
    elif change == "data":
        (root / DATA).write_bytes(b"SELECT 'older source shape';\n")
    else:
        helper.rename(helper.with_name("renamed_trigger.py"))

    for _ in range(2):
        with pytest.raises(producer_capability.ProducerCapabilityRefused) as refused:
            producer_capability.assert_producer_capability()
        assert refused.value.reason == "producer-capability-migration-version"
        assert installation["marker"].read_bytes() == marker_before

    payload = regenerate_marker(installation, settings)
    assert payload["migration_version"] != accepted.migration_version
    assert installation["marker"].read_bytes() != marker_before
    assert producer_capability.assert_producer_capability().migration_version == payload["migration_version"]


def test_old_numbered_only_marker_requires_regeneration(
    installed_producer_capability, settings
):
    installation = installed_producer_capability
    root = install_tree(installation, settings)
    payload = json.loads(installation["marker"].read_text(encoding="utf-8"))
    digest = hashlib.sha256(b"spaceworks-django-migrations-v1\0")
    for path in sorted(root.glob("*/migrations/[0-9][0-9][0-9][0-9]_*.py")):
        relative, content = path.relative_to(root).as_posix().encode(), path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big") + relative)
        digest.update(len(content).to_bytes(8, "big") + content)
    payload["migration_version"] = "django-migrations-v1:" + digest.hexdigest()
    producer_capability.write_capability_marker_fsynced(
        installation["marker"], payload, require_root_owned=False,
    )
    marker_before = installation["marker"].read_bytes()

    with pytest.raises(producer_capability.ProducerCapabilityRefused) as refused:
        producer_capability.assert_producer_capability()
    assert refused.value.reason == "producer-capability-migration-version"
    assert installation["marker"].read_bytes() == marker_before
    regenerate_marker(installation, settings)
    producer_capability.assert_producer_capability()


def test_real_builder_refuses_helper_drift_before_any_artifact_effect(
    installed_producer_capability, settings, monkeypatch
):
    installation = installed_producer_capability
    root = install_tree(installation, settings)
    producer_capability.assert_producer_capability()
    marker_before = installation["marker"].read_bytes()
    helper = root / TRIGGER
    helper.write_bytes(helper.read_bytes() + b"# drift\n")
    recovery_checks = []
    # This preceding recovery-state query is the sole DB-dependent precondition.
    monkeypatch.setattr(archive_builder, "assert_deployment_fully_restored",
                        lambda: recovery_checks.append("fully restored"))

    def forbidden(name):
        def effect(*args, **kwargs):
            pytest.fail(f"producer refusal must precede {name}")
        return effect

    for owner, name in (
        (archive_builder.recipients, "selection_for"),
        (archive_builder, "_require_binary"),
        (archive_builder, "_require_postgres_clients"),
        (archive_builder.tempfile, "TemporaryDirectory"),
        (archive_builder, "DeploymentCapture"),
        (archive_builder, "_snapshot_payload"),
        (archive_builder, "_capture_objects"),
        (archive_builder, "build_content_ledger"),
        (archive_builder.subprocess, "run"),
        (archive_builder.storage, "upload_staging"),
        (archive_builder.storage, "upload_archive"),
        (artifact_ledger, "persist_pending"),
    ):
        monkeypatch.setattr(owner, name, forbidden(name))
    archive = SimpleNamespace(scope="deployment", id=uuid.uuid4())

    with pytest.raises(producer_capability.ProducerCapabilityRefused) as refused:
        archive_builder.build_archive(archive)

    assert refused.value.reason == "producer-capability-migration-version"
    assert recovery_checks == ["fully restored"]
    assert installation["marker"].read_bytes() == marker_before
