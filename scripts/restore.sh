#!/usr/bin/env bash
# Fixed source identity stays covered by the existing privileged-script capability.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -I -B - "$ROOT" <<'PY_GUARD'
import hashlib
import os
from pathlib import Path
import stat
import sys

# Transitive host code identity: regenerate deliberately after reviewed source edits.
EXPECTED = {
    "backend/apps/__init__.py": "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "backend/apps/backup/__init__.py": "87e7763152dbb2a14b12826c8015a1fa82467090df82e11e47622b6879f0fe75",
    "backend/apps/backup/full_format.py": "f180b8303143ae25c39c05e2cf38b60e43205dbe134564c1cc584d6156d325c3",
    "backend/apps/backup/host_capability_journal.py": "b251db0457f9bdd388d372d4fbad6b6384f4e6e1412d40bc2f9a523c24521ff8",
    "backend/apps/backup/host_capability_types.py": "aeac8a00a8fc7db6592f9b46a0eae1d074e81fd385765238681ebc807c6ac09c",
    "backend/apps/backup/host_marker.py": "18d032f4b347ddbe7831c0531e1252eba576e8de9ed8d8be19062ce218dee104",
    "backend/apps/backup/host_marker_file.py": "0c63f5a282ed89e12f1395b4a29eb9683068589ce934a144111beb82edc2900b",
    "backend/apps/backup/host_pointer.py": "d5343ce1c7a1143356b07b54afbdbd44a8f22a04dc1493ca65e93b6300e29b6f",
    "backend/apps/backup/host_private_file.py": "1e18213207aa6141e4a1e916aa6949bc905c57a6f881b18fa9cc30fc6accb40a",
    "backend/apps/backup/host_restore_admission.py": "9c5ad9f8662656bc73431f7706dceb813bccc5e061d234d5805faa4798c8937e",
    "backend/apps/backup/host_restore_configuration.py": "f01614e7691f7d486a49e81f72cf20ed2f223645675ea84a78fcd6dd545cb803",
    "backend/apps/backup/host_restore_files.py": "4adb25d8febcaf651813a186a1e3070723dcc53c650929b74dae1d3f7768e8cf",
    "backend/apps/backup/host_restore_lifecycle.py": "bb0887f7dc9ae063db5030b212dffa9d2c319ddae1b1bda8b136357755770cec",
    "backend/apps/backup/host_restore_prepare.py": "865e146e7814394d179577a767904cbeeb41bab043020bc1b8a1db589cab3c38",
    "backend/apps/backup/host_restore_resume.py": "469bf7bb3b2cb6de34d7323d2bc53e06a0e4842b34f3d73b4ada36bc4a755dc2",
    "backend/apps/backup/host_restore_transport.py": "c1dd16d552715272a8f4ae3a87c2b9af844d68a4a5d2a768eab840fdbe27e599",
    "backend/apps/backup/host_run_ledger.py": "2c4d747ad4554176bc25ff1e4da914a3a5852ccf7ed5326279788f0212e08dd7",
    "backend/apps/backup/host_supervisor.py": "95e62a71d3633fd372428100fd7e49ac410633dc497d94463844f1f67749f4ed",
    "backend/apps/backup/host_topology_record.py": "212533a4b0d8e4e2aa0491e46c58a265907732668e7560d7c4957ccdfdd98f28",
    "backend/apps/backup/inplace_marker.py": "026a817f3c857a00b09700955af9f22f5728e23b657bfcfc5f155178945b83ef",
    "backend/apps/backup/inplace_recovery_facts.py": "77cac93c564a700dd7321166582833772b4115262241ee5b4e81e89df855b3b9",
    "backend/apps/backup/operation_lock.py": "226cf543049dcca1ad26a0a31db47effd4347a8416ea10794c4a3f809fe110ce",
    "backend/apps/backup/restore_manifest_facts.py": "a78561210f21df1f192a2dc15aa81eb939da6fe8c99d4067648726b4d3baa459",
    "backend/apps/backup/topology.py": "8c5f31fe31eceb86d84b3d438b363657513a8c6abb73b8bc4ea22ccd65215048",
    "scripts/restore-host.py": "f971c644b459bddfe5c461f555f48936e963afa8abfcd384a894a44d2c9a12d3"
}
root = Path(sys.argv[1])
try:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError
    directories = {root, *root.parents}
    for relative in (*EXPECTED, "scripts/restore.sh"):
        directories.update((root / relative).parents)
    for directory in directories:
        info = directory.lstat()
        temporary_ancestor = (directory == Path("/tmp") and directory in root.parents
                              and stat.S_IMODE(info.st_mode) == 0o1777)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or (info.st_mode & 0o022 and not temporary_ancestor)):
            raise ValueError
    for relative in (*EXPECTED, "scripts/restore.sh"):
        info = (root / relative).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or info.st_mode & 0o022):
            raise ValueError
    for relative, expected in EXPECTED.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise ValueError
except (OSError, ValueError):
    raise SystemExit("Restore requires the complete matching root-owned protected Linux host bundle. Source identity, file or directory trust differs; no operation was started.") from None
PY_GUARD
# The guard attests source bytes; ignore pre-existing local bytecode as well.
case "${1:-}" in
  --import) shift; exec python3 -I -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" import "$@" ;;
  --resume-host) shift; exec python3 -I -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" resume-host "$@" ;;
  --recover-superadmin) shift; exec python3 -I -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" recover-superadmin "$@" ;;
  *) exec python3 -I -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" restore "$@" ;;
esac
