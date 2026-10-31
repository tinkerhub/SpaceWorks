"""Real local binary and PostgreSQL operations, executed only by the parent runner."""

import subprocess

from django.db import connections

from apps.backup.archive_payload import _postgres_environment
from apps.backup.postgres_client import client_binary


def clean_restore(path, database_name):
    subprocess.run([
        client_binary("pg_restore"), "--exit-on-error", "--clean", "--if-exists",
        "--no-owner", "--no-acl", f"--dbname={database_name}", str(path),
    ], env=_postgres_environment(), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def raw_row(database):
    with database.cursor() as cursor:
        cursor.execute("SELECT id, database_uuid::text, run_id::text, artifact_sha256, "
                       "capture_id::text, created_at FROM backup_deploymentdatabaseidentity")
        return cursor.fetchall()


def age_keypair(tmp_path):
    identity = tmp_path / "age-identity.txt"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    identity.chmod(0o600)
    public = subprocess.run(["age-keygen", "-y", str(identity)], check=True,
                            capture_output=True, text=True).stdout.strip()
    assert public.startswith("age1")
    return identity, public


def decrypt(build, identity, output):
    subprocess.run(["age", "-d", "-i", str(identity), "-o", str(output), str(build.encrypted)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert output.is_file()
    assert not build.encrypted.read_bytes().startswith(b"PGDMP")


def schema_counts(using, models):
    result = {}
    for model in models:
        table = model._meta.db_table
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", ["public." + table])
            assert cursor.fetchone()[0] is not None
        result[model._meta.label] = model.objects.using(using).count()
    return result
