#!/usr/bin/env python3
"""Fixed maintenance probe for the bundled in-place restore controller only."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import uuid

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.backup.database_identity import query_live_database_identity
from apps.backup.full_restore_identity import capture_target_identity
from apps.backup.inplace_recovery_facts import query_recovery_proof


def probe(url):
    with psycopg2.connect(url) as database:
        database.autocommit = True
        live = query_live_database_identity(database)
        with database.cursor() as cursor:
            cursor.execute("SELECT host(inet_server_addr()), inet_server_port(), "
                           "COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()), false)")
            address, port, tls = cursor.fetchone()
        with database.cursor() as cursor:
            cursor.execute("SELECT mode, active_restore_id::text FROM backup_deploymentrecoverystate WHERE id=1")
            states = cursor.fetchmany(2)
        if len(states) != 1:
            raise RuntimeError("The existing deployment recovery singleton is required.")
        return {"recovery_state": {"mode": states[0][0], "active_restore": states[0][1]}, "identity": asdict(live), "target_record": capture_target_identity(database), "physical": {"address": address, "port": port, "tls": tls}}


def main():
    if os.geteuid() != 0 or len(sys.argv) not in {1, 2}:
        raise RuntimeError("Fixed bundled restore probe refused.")
    identifier = str(uuid.UUID(sys.argv[1])) if len(sys.argv) == 2 else None
    maintenance = probe(os.environ["DATABASE_URL"])
    application = probe(os.environ["SPACEWORKS_RUNTIME_DATABASE_URL"])
    if maintenance["physical"] != application["physical"] or maintenance["target_record"]["row"] != application["target_record"]["row"]:
        raise RuntimeError("Bundled restore database transports disagree.")
    for key in ("endpoint", "oid", "database_uuid", "run_id", "artifact_sha256", "capture_id"):
        if maintenance["identity"][key] != application["identity"][key]:
            raise RuntimeError("Bundled restore database identities disagree.")
    systems = {item["identity"]["system_identifier"] for item in (maintenance, application)} - {None}
    if len(systems) != 1:
        raise RuntimeError("Bundled restore system identity is unavailable or inconsistent.")
    maintenance["identity"]["system_identifier"] = systems.pop()
    if identifier:
        with psycopg2.connect(os.environ["DATABASE_URL"]) as database:
            maintenance["recovery_proof"] = query_recovery_proof(database, identifier)
    print(json.dumps(maintenance))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Fixed bundled restore database probe refused.") from None
