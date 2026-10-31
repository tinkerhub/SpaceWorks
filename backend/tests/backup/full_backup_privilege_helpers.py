"""Test-only function ACL hardening, bounded to the active disposable test DB."""

from contextlib import contextmanager

import psycopg2
from psycopg2 import sql


FUNCTION = "pg_catalog.pg_control_system()"


def _acl(cursor):
    cursor.execute(
        "SELECT p.proacl::text, r.rolname, p.proowner "
        "FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE p.oid = 'pg_catalog.pg_control_system()'::regprocedure"
    )
    raw, owner, owner_oid = cursor.fetchone()
    cursor.execute(
        "SELECT a.grantor, a.grantee, a.privilege_type, a.is_grantable "
        "FROM pg_proc p, LATERAL "
        "aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a "
        "WHERE p.oid = 'pg_catalog.pg_control_system()'::regprocedure "
        "ORDER BY 1, 2, 3, 4"
    )
    return {"raw": raw, "owner": owner, "owner_oid": owner_oid, "grants": cursor.fetchall()}


@contextmanager
def hardened_control_acl(database):
    """Revoke only PUBLIC EXECUTE, then restore its exact prior grant semantics.

    Function ACLs are database-local. Refuse non-test names, unsupported grantors,
    or a connection without owner authority *before* changing anything. Preserve
    all other grantees (including pg_monitor), grantors and grant options. NULL
    proacl and explicit acldefault are compared as the same effective ACL.
    """
    __tracebackhide__ = True
    owner = None
    try:
        owner = psycopg2.connect(**database.get_connection_params())
        owner.autocommit = True
        with owner.cursor() as cursor:
            cursor.execute("SELECT current_database(), r.oid, r.rolsuper "
                           "FROM pg_roles r WHERE rolname = current_user")
            name, actor_oid, superuser = cursor.fetchone()
            if name != database.settings_dict["NAME"] or not name.startswith("test_"):
                raise RuntimeError("function-acl: requires the isolated test_ database")
            before = _acl(cursor)
            if actor_oid != before["owner_oid"] and not superuser:
                raise RuntimeError("function-acl: requires function owner authority")
            public = [grant for grant in before["grants"] if grant[1] == 0]
            if len(public) > 1 or any(
                grant[0] != before["owner_oid"] or grant[2] != "EXECUTE" for grant in public
            ):
                raise RuntimeError("function-acl: unsupported PUBLIC grant provenance")
            evidence = {"before": before}
            changed = False
            try:
                if public:
                    cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(before["owner"])))
                    cursor.execute(f"REVOKE EXECUTE ON FUNCTION {FUNCTION} FROM PUBLIC RESTRICT")
                    changed = True
                    cursor.execute("RESET ROLE")
                hardened = _acl(cursor)
                assert hardened["grants"] == [grant for grant in before["grants"] if grant[1] != 0]
                evidence["hardened"] = hardened
                yield evidence
            finally:
                # Do not rebuild the ACL: restore only the PUBLIC grant we removed.
                if changed:
                    cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(before["owner"])))
                    option = " WITH GRANT OPTION" if public[0][3] else ""
                    cursor.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO PUBLIC{option}")
                    cursor.execute("RESET ROLE")
                evidence["after"] = _acl(cursor)
                assert evidence["after"]["grants"] == before["grants"], "function-acl: restoration differs"
    except psycopg2.Error as exc:
        # Do not expose raw driver errors, connection parameters or credentials.
        raise RuntimeError(f"function-acl: {type(exc).__name__}") from None
    finally:
        if owner is not None:
            owner.close()
