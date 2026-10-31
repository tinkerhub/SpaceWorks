"""Installed Compose producer + real admission over explicitly SYNTHETIC wire facts.

Parent command, from repository root on Linux with Python 3.12+ and pytest:
    cd backend && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --noconftest \
        -c /dev/null -q tests/backup/test_recovery_compose_inheritance.py

Requires docker + a system-installed Compose plugin supporting multiple --env-file
arguments and config --format json. No daemon/socket, database, provider or build.
Only JSON production is real here: parent separately probes real full host topology,
image/container facts and restore. These cases do not attest an installed root host.
The host-only command avoids unrelated Django/provider setup and test monkeypatches;
all imported production admission, topology and trust checks execute unchanged.
"""

from copy import deepcopy

import pytest

from apps.backup.host_restore_admission import admit_configuration, inventory
from apps.backup.host_restore_transport import RestoreHostError, trusted
from apps.backup.topology import TopologyConfigurationError
from tests.backup.recovery_compose_inheritance_support import (
    APP_ENTRYPOINT, APP_ROLES, DIGEST, RUNNING,
    SyntheticInspectTransport, render_committed_compose,
)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    return render_committed_compose(tmp_path_factory.mktemp("compose-inheritance"))


@pytest.fixture
def transport(rendered):
    return SyntheticInspectTransport(rendered)


def assert_admitted(transport):
    assert admit_configuration(transport) == DIGEST
    actual = inventory(transport)
    assert {row["Config"]["Labels"]["com.docker.compose.service"] for row in actual} == set(RUNNING)
    assert transport.redis_volume_identity == transport.volume["Name"]
    for role in APP_ROLES:
        assert transport.containers[role]["Config"]["Entrypoint"] == APP_ENTRYPOINT


def test_unmodified_actual_compose_json_reaches_both_production_admissions(transport):
    # No JSON reimplementation/normalization and no monkeypatch of either validator.
    for role in APP_ROLES:
        service = transport.config["services"][role]
        assert service.get("entrypoint") is None
        assert service["command"][:2] == ["--role", role]
    for role in ("db", "redis"):
        service = transport.config["services"][role]
        assert service.get("entrypoint") is None and service.get("command") is None
    assert_admitted(transport)
    # Nonempty independent image defaults, never null echoes from Compose.
    for role in ("db", "redis"):
        image = transport.images[transport.config["services"][role]["image"]]["Config"]
        actual = transport.containers[role]["Config"]
        assert actual["Entrypoint"] == image["Entrypoint"] and actual["Entrypoint"]
        assert actual["Cmd"] == image["Cmd"] and actual["Cmd"]


def test_explicit_null_app_entrypoints_inherit_image_for_all_three_roles(transport):
    # Deterministic variants of real producer output, not extra Compose proof.
    for role in APP_ROLES:
        transport.config["services"][role]["entrypoint"] = None
    assert_admitted(transport)


def test_absent_app_entrypoints_inherit_image_for_all_three_roles(transport):
    for role in APP_ROLES:
        transport.config["services"][role].pop("entrypoint", None)
    assert_admitted(transport)


def test_explicit_null_database_and_redis_argv_inherit_nonempty_image_defaults(transport):
    for role in ("db", "redis"):
        transport.config["services"][role].update(command=None, entrypoint=None)
    assert_admitted(transport)


def test_explicit_exact_app_entrypoint_remains_supported(transport):
    for role in APP_ROLES:
        transport.config["services"][role]["entrypoint"] = list(APP_ENTRYPOINT)
    assert_admitted(transport)


@pytest.mark.parametrize(("role", "entrypoint"), [
    ("backend", []), ("worker", ""), ("beat", ["sh", "-c", "custom-writer"]),
], ids=["empty-list", "empty-string", "custom-role-entrypoint"])
def test_explicit_app_entrypoint_overrides_are_not_image_inheritance(transport, role, entrypoint):
    transport.config["services"][role]["entrypoint"] = entrypoint
    with pytest.raises(RestoreHostError, match="role command"):
        admit_configuration(transport)


@pytest.mark.parametrize("command", [None, [], {"argv": "malformed"}], ids=["null", "empty-list", "mapping"])
def test_invalid_app_commands_refuse_topology_then_typed_role_admission(transport, command):
    transport.config["services"]["backend"]["command"] = command
    # The unchanged ordinary-writer declaration refuses first; do not bypass it.
    with pytest.raises(TopologyConfigurationError, match="writer rollout"):
        admit_configuration(transport)
    assert transport.calls == []
    # A second, coherent declared/discovered set reaches the actual role guard.
    # It must raise RestoreHostError, never TypeError or image-command inheritance.
    transport.config["x-spaceworks-host-orchestration"]["writer_services"] = ["worker", "beat"]
    with pytest.raises(RestoreHostError, match="role command"):
        admit_configuration(transport)


@pytest.mark.parametrize("fault", ["entrypoint", "oci-digest"])
def test_independently_inspected_app_image_must_still_match(transport, fault):
    image = transport.images[transport.config["services"]["backend"]["image"]]
    if fault == "entrypoint":
        image["Config"]["Entrypoint"] = ["sh", "-c", "unadmitted-image"]
    else:
        image["RepoDigests"] = ["example.invalid/spaceworks/backend@sha256:" + "0" * 64]
    with pytest.raises(RestoreHostError, match="digest and entrypoint"):
        admit_configuration(transport)
    with pytest.raises(RestoreHostError, match="entrypoint|OCI digest"):
        inventory(transport)


@pytest.mark.parametrize("field", ["Entrypoint", "Cmd"])
def test_independent_effective_container_argv_cannot_drift(transport, field):
    assert_admitted(transport)
    transport.containers["worker"]["Config"][field] = ["unadmitted-container-process"]
    with pytest.raises(RestoreHostError, match="process command"):
        inventory(transport)


@pytest.mark.parametrize(("role", "declared", "inspected"), [
    ("db", "command", "Cmd"), ("redis", "entrypoint", "Entrypoint"),
], ids=["command-empty-list", "entrypoint-empty-list"])
def test_explicit_empty_inventory_values_are_literal_not_truthiness_fallback(transport, role, declared, inspected):
    assert_admitted(transport)
    assert transport.containers[role]["Config"][inspected]
    transport.config["services"][role][declared] = []
    with pytest.raises(RestoreHostError, match="process command"):
        inventory(transport)
    # Inventory compares explicit [] literally in both directions. This is not
    # configuration admission of a custom PostgreSQL/Redis startup command.
    transport.containers[role]["Config"][inspected] = []
    inventory(transport)


def test_world_writable_host_authority_input_is_still_untrusted(tmp_path):
    path = tmp_path / "untrusted-authority"
    path.write_text("synthetic root authority negative\n", encoding="utf-8")
    path.chmod(0o666)
    with pytest.raises(RestoreHostError, match="untrusted"):
        trusted(path, private=True)


def test_topology_cannot_omit_the_actual_worker(transport):
    transport.config["x-spaceworks-host-orchestration"]["writer_services"] = ["backend", "beat"]
    with pytest.raises(TopologyConfigurationError, match="writer rollout"):
        admit_configuration(transport)
    assert transport.calls == []


def test_actual_container_image_id_cannot_differ_from_inspected_image(transport):
    admit_configuration(transport)
    transport.containers["beat"]["Image"] = "sha256:" + "0" * 64
    with pytest.raises(RestoreHostError, match="project image"):
        inventory(transport)


def test_host_mount_constraints_remain_in_configuration_and_inventory(transport):
    assert_admitted(transport)
    service = transport.config["services"]["backend"]
    marker = next(m for m in service["volumes"] if m["target"] == "/run/spaceworks-host")
    marker["read_only"] = False
    with pytest.raises(RestoreHostError, match="host authority mount"):
        admit_configuration(transport)
    marker["read_only"] = True
    actual = next(m for m in transport.containers["backend"]["Mounts"] if m["Destination"] == "/run/spaceworks-host")
    actual["Source"] = str(transport.host / "wrong-public")
    with pytest.raises(RestoreHostError, match="bind mount"):
        inventory(transport)


def test_pointer_generation_and_actual_environment_constraints_remain(transport):
    assert_admitted(transport)
    env = transport.config["services"]["worker"]["environment"]
    before = deepcopy(env)
    env["SPACEWORKS_DB_POINTER_GENERATION"] = "8"
    with pytest.raises(RestoreHostError, match="producers disagree"):
        admit_configuration(transport)
    env.clear()
    env.update(before)
    transport.containers["worker"]["Config"]["Env"].append("UNEXPLAINED=synthetic")
    with pytest.raises(RestoreHostError, match="process environment"):
        inventory(transport)
