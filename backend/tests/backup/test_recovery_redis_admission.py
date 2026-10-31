"""Actual inventory admission over synthetic read-only Docker inspect responses."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from apps.backup.host_restore_admission import _admit_implicit_redis, admit_configuration, inventory, no_database_sessions, reuse_redis_admission, target_identity
from apps.backup.host_restore_transport import RestoreHostError
from tests.backup.recovery_test_support import marker_rig, private
from tests.backup.recovery_transport_support import SyntheticTransport, VOLUME


def test_bundled_redis_real_shape_admitted_and_receipt_rebinds_fresh_transport(tmp_path):
    with marker_rig(tmp_path) as rig:
        t = SyntheticTransport(rig, tmp_path)
        admit_configuration(t)
        actual = inventory(t)
        assert t.redis_volume_identity == VOLUME
        receipt = tmp_path / "receipt"
        private(receipt / "admission-old.json", {"resolved": t.config, "actual": actual})
        fresh = SimpleNamespace(docker=t.docker)
        reuse_redis_admission(fresh, receipt)
        assert fresh.redis_volume_identity == VOLUME
        mounts = {"/data": deepcopy(t.container("redis")["Mounts"][0])}
        _admit_implicit_redis(fresh, t.config["services"]["redis"], t.image("redis:7-alpine"), mounts)
        assert mounts == {}
        assert all(args[:2] == ("volume", "inspect") for kind, args in t.events if kind == "docker" and args[0] == "volume")
        assert not any(args[0] in {"create", "rm", "prune"} for kind, args in t.events if kind == "docker")


@pytest.mark.parametrize("fault", ["image", "declared", "extra-image-volume", "bind", "readonly", "name",
    "uppercase", "volume-name", "driver", "scope", "options", "backing", "extra-mount", "replacement"])
def test_implicit_redis_refuses_any_unadmitted_shape(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        t = SyntheticTransport(rig, tmp_path)
        service = deepcopy(t.config["services"]["redis"])
        image = t.image("redis:7-alpine")
        mounts = {"/data": t.container("redis")["Mounts"][0]}
        if fault == "image": service["image"] = "redis:latest"
        elif fault == "declared": service["volumes"] = [{"target": "/data"}]
        elif fault == "extra-image-volume": image["Config"]["Volumes"]["/extra"] = {}
        elif fault == "bind": mounts["/data"]["Type"] = "bind"
        elif fault == "readonly": mounts["/data"]["RW"] = False
        elif fault == "name": mounts["/data"]["Name"] = "named-shared-volume"
        elif fault == "uppercase": mounts["/data"]["Name"] = VOLUME.upper()
        elif fault == "volume-name": t.volume_facts["Name"] = "f" * 64
        elif fault == "driver": t.volume_facts["Driver"] = "nfs"
        elif fault == "scope": t.volume_facts["Scope"] = "global"
        elif fault == "options": t.volume_facts["Options"] = {"type": "none", "o": "bind", "device": "/shared"}
        elif fault == "backing": t.volume_facts["Mountpoint"] = "/different"
        elif fault == "extra-mount": mounts["/extra"] = deepcopy(mounts["/data"])
        else: t.redis_volume_identity = "f" * 64
        with pytest.raises(RestoreHostError):
            _admit_implicit_redis(t, service, image, mounts)


@pytest.mark.parametrize("fault", ["candidate", "oneoff", "duplicate", "command", "env", "mount", "image"])
def test_actual_project_writer_inventory_must_equal_trusted_configuration(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        t = SyntheticTransport(rig, tmp_path)
        original = t.container
        def changed(role):
            row = original(role)
            if role == "backend":
                if fault == "candidate": row["Config"]["Labels"]["com.docker.compose.service"] = "candidate-backend"
                elif fault == "oneoff": row["Config"]["Labels"]["com.docker.compose.oneoff"] = "True"
                elif fault == "duplicate": row["Config"]["Labels"]["com.docker.compose.service"] = "worker"
                elif fault == "command": row["Config"]["Cmd"] = ["arbitrary", "writer"]
                elif fault == "env": row["Config"]["Env"].append("UNEXPLAINED=1")
                elif fault == "mount": row["Mounts"].append({"Destination": "/extra", "Type": "bind", "Source": "/private", "RW": True})
                else: row["Image"] = "unadmitted-image"
            return row
        t.container = changed
        with pytest.raises(RestoreHostError):
            inventory(t)
        assert not any(isinstance(event, str) and event.startswith(("stop:", "control:")) for event in t.events)


@pytest.mark.parametrize("fault", ["pointer", "generation", "worker-command", "required-mount", "external"])
def test_unsupported_configuration_is_refused_before_runtime_effects(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        t = SyntheticTransport(rig, tmp_path)
        if fault == "pointer": t.config["services"]["db"]["environment"]["POSTGRES_DB"] = "other"
        elif fault == "generation": t.config["services"]["worker"]["environment"]["SPACEWORKS_TASK_GENERATION"] = "other"
        elif fault == "worker-command": t.config["services"]["worker"]["command"] += ["-Q", "old"]
        elif fault == "required-mount": t.config["services"]["backend"]["volumes"][0]["read_only"] = False
        else:
            t.config["x-spaceworks-host-orchestration"]["scheduler"] = {"mode": "external", "host_gate_command": "fixed"}
        with pytest.raises(RestoreHostError):
            admit_configuration(t)


def test_unexplained_sql_sessions_and_transport_identity_disagreement_refuse(tmp_path):
    with marker_rig(tmp_path) as rig:
        t = SyntheticTransport(rig, tmp_path)
        actual_sql = t.sql
        t.sql = lambda command: "1" if "pg_stat_activity" in command else actual_sql(command)
        with pytest.raises(RestoreHostError, match="Unexplained"):
            no_database_sessions(t)
        t.sql = lambda command: json.dumps({"name": "other", "oid": 1, "uuid": "other", "system": "other"})
        with pytest.raises(RestoreHostError, match="disagree"):
            target_identity(t)
