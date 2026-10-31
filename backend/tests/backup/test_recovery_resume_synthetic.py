"""Actual resume method/private receipt/marker; fixed SQL and Docker are synthetic."""

from copy import copy

import pytest

from apps.backup.host_marker import MarkerError, MarkerState, read_marker
from apps.backup.host_restore_resume import resume_host
from apps.backup.host_restore_transport import RestoreHostError
from tests.backup.recovery_test_support import RESTORE_ID, marker_rig, recovery_proof
from tests.backup.test_recovery_lifecycle_synthetic import operation


@pytest.mark.parametrize("fault", [None, "unacknowledged", "replacement-volume", "startup"])
def test_fresh_transport_reuses_private_volume_identity_and_exact_ack_before_writers(tmp_path, fault):
    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        op.restore("proceed")
        fresh = copy(op.t)
        del fresh.redis_volume_identity
        original_probe = fresh.probe
        def probe():
            value = original_probe()
            value["recovery_proof"] = recovery_proof(acknowledged=fault != "unacknowledged")
            return value
        fresh.probe = probe
        if fault == "replacement-volume":
            fresh.redis_name = "f" * 64
            fresh.volume_facts = dict(fresh.volume_facts, Name=fresh.redis_name,
                Mountpoint="/var/lib/docker/volumes/" + fresh.redis_name + "/_data")
        if fault == "startup":
            fresh.failure = "start:worker,beat"
        if fault:
            reason = {"unacknowledged": "recovered principal has not acknowledged",
                "replacement-volume": "identity changed",
                "startup": "synthetic transport failure"}[fault]
            with pytest.raises((RestoreHostError, MarkerError), match=reason):
                resume_host(fresh, rig.lock, RESTORE_ID)
            expected = MarkerState.RESTORE_BLOCKED if fault == "startup" else MarkerState.QUARANTINED_AFTER_CUTOVER
            assert read_marker(rig.marker).state == expected
            assert not fresh.running & {"worker", "beat"}
        else:
            resume_host(fresh, rig.lock, RESTORE_ID)
            assert fresh.redis_volume_identity == op.t.redis_volume_identity
            assert read_marker(rig.marker).state == MarkerState.ACKNOWLEDGED_NORMAL
            assert fresh.running & {"backend", "worker", "beat"} == {"backend", "worker", "beat"}


def test_recover_principal_fixed_child_also_closes_inheritable_authority_fds(tmp_path):
    import json
    import os
    import sys
    from apps.backup.host_restore_resume import recover_principal

    with marker_rig(tmp_path) as rig:
        op = operation(rig, tmp_path)
        op.restore("proceed")
        scripts = op.t.root / "scripts"
        scripts.mkdir()
        output = tmp_path / "child-fds.json"
        shim = scripts / "spaceworks-compose.sh"
        shim.write_text("#!" + sys.executable + "\n" + '''import json,os,sys
assert sys.argv[1:] == ['bundled','exec','-T','backend','python','manage.py','recover_superadmin','operator']
seen=[]
for fd in os.listdir('/proc/self/fd'):
    try:
        item=os.fstat(int(fd)); seen.append([item.st_dev,item.st_ino])
    except OSError: pass
with open(os.environ['RECOVERY_FD_REPORT'],'w') as out: json.dump(seen,out)
''')
        shim.chmod(0o755)
        op.t.environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "RECOVERY_FD_REPORT": str(output)}
        with (tmp_path / "another-authority").open("w") as extra:
            identities = {(os.fstat(h.fileno()).st_dev, os.fstat(h.fileno()).st_ino) for h in (rig.lock, extra)}
            os.set_inheritable(rig.lock.fileno(), True)
            os.set_inheritable(extra.fileno(), True)
            recover_principal(op.t, RESTORE_ID, "operator")
        assert not set(map(tuple, json.loads(output.read_bytes()))) & identities
        assert read_marker(rig.marker).state == MarkerState.QUARANTINED_AFTER_CUTOVER
