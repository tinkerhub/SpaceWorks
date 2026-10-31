"""Narrow privileged mode admission must precede any maintenance connection."""

import pytest

from tests.backup.full_backup_bootstrap_helpers import load_bootstrap


@pytest.mark.parametrize("mode,grants", [("unknown", "1"), ("true", "1"), ("1", ""), ("1", "0")])
def test_unknown_identity_mode_or_nonfixed_dispatch_refuses_before_connect(monkeypatch, mode, grants):
    bootstrap = load_bootstrap()
    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SPACEWORKS_RESTORE_IDENTITY", mode)
    monkeypatch.setenv("SPACEWORKS_GRANTS_ONLY", grants)
    monkeypatch.setenv("DATABASE_URL", "postgres://maintenance.invalid/unused")
    monkeypatch.setenv("SPACEWORKS_RUNTIME_DATABASE_URL", "postgres://runtime:fixture@unused/unused")

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid mode attempted a database connection")

    monkeypatch.setattr(bootstrap.psycopg2, "connect", forbidden)
    with pytest.raises(RuntimeError, match="fixed grants-only"):
        bootstrap.main()


def test_identity_restore_cannot_select_an_alternate_database(monkeypatch):
    bootstrap = load_bootstrap()
    monkeypatch.setenv("SPACEWORKS_RESTORE_IDENTITY", "1")
    monkeypatch.setenv("SPACEWORKS_GRANT_DATABASE_NAME", "different_database")
    with pytest.raises(RuntimeError, match="cannot select a different"):
        bootstrap._grant_only("not-connected", "not-parsed")
