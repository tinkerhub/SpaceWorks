"""Structural contracts for the installed Python host controller and grants."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _function(tree, name):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                and node.name == name)


def _calls(node):
    return [ast.unparse(item.func) for item in ast.walk(node)
            if isinstance(item, ast.Call)]


def _tree(relative):
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"))


def _position(function, call):
    matches = [index for index, statement in enumerate(function.body)
               if call in _calls(statement)]
    assert len(matches) == 1, (function.name, call, matches)
    return matches[0]


def assert_restore_grant_edges():
    tree = _tree("backend/apps/backup/host_restore_lifecycle.py")
    decision, restore = (_function(tree, name) for name in ("decision", "restore"))
    inputs = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
              and ast.unparse(node.func) == "t.sql"
              and any(keyword.arg == "input_file" for keyword in node.keywords)]
    assert len(inputs) == 2
    assert "t.sql(RESTORE, input_file=source)" in ast.unparse(restore)
    assert "pg_restore --exit-on-error --single-transaction --no-owner --no-acl" in ast.unparse(decision)
    restore_command = next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == "RESTORE"
                                   for target in node.targets))
    assert '--clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' in restore_command
    # The preview sibling and replacement each provision privileged grants before
    # any later Django call. A grant refusal propagates; no rollback/restart lane.
    for function, following in ((decision, "t.control"), (restore, "t.control")):
        sql = [node for node in function.body if isinstance(node, ast.With)
               and "t.sql" in _calls(node) and "input_file=source" in ast.unparse(node)]
        assert len(sql) == 1
        index = function.body.index(sql[0])
        grant = function.body[index + 1]
        if function is restore:
            assert isinstance(grant, ast.Assign)  # fixed target + operation identity
            grant = function.body[index + 2]
        assert isinstance(grant, ast.Expr) and isinstance(grant.value, ast.Call)
        assert ast.unparse(grant.value.func) == "t.grants"
        later = function.body[function.body.index(grant) + 1:]
        assert any(following in _calls(node) for node in later)
        assert not any("t.control" in _calls(node) for node in
                       function.body[index + 1:function.body.index(grant)])
        assert not any(isinstance(node, ast.Try) for node in ast.walk(function))
    assert "temporary_database=name" in ast.unparse(decision)
    assert "identity=json.dumps(identity).encode()" in ast.unparse(restore)
    assert "legacy=i.kind != FULL_FORMAT" in ast.unparse(restore)
    assert _position(restore, "t.grants") < next(
        index for index, node in enumerate(restore.body)
        if "t.control('rehydrate'" in ast.unparse(node))
    assert _position(restore, "self.marker.begin") < _position(restore, "t.grants")
    assert _position(restore, "config.install") < _position(restore, "t.grants")
    # Failure retains the block and shuts down writers; it cannot restore SQL or
    # release services. Explicit harmless abort has its own positive proof path.
    failure = _function(tree, "retain_failure")
    assert "stop_current_writers" in _calls(failure)
    assert not {"self.t.sql", "self.t.compose", "self.marker.complete"} & set(_calls(failure))
    abort = _function(tree, "finish_abort")
    restart = next(
        index for index, node in enumerate(abort.body)
        if "self.t.compose('up'" in ast.unparse(node))
    guards = [node for node in abort.body[:restart] if isinstance(node, ast.If)]
    assert len(guards) == 3
    assert all(len(node.body) == 1 and isinstance(node.body[0], ast.Raise)
               and not node.orelse for node in guards)
    for required in ("proof['mode']", "proof['active_restore']", "proof['stage']", "proof['decision']"):
        assert required in ast.unparse(guards[0].test)
    assert "('normal', None, 'aborted', 'abort')" in ast.unparse(guards[0].test)
    for required in ("self.t.validate() != self.old_facts", "self.old_environment", "self.t.config"):
        assert required in ast.unparse(guards[1].test)
    assert "read_marker" in _calls(guards[2]) and "target_identity" in _calls(guards[2])
    assert "self.old_marker" in ast.unparse(guards[2].test)
    assert "self.identity" in ast.unparse(guards[2].test)


def assert_privileged_grant_bootstrap():
    helper = _function(_tree("backend/apps/backup/host_restore_transport.py"), "grants")
    assert ast.unparse(helper.body[0]) == (
        "args = ['run', '--rm', '--no-deps', '-T', '-e', 'SPACEWORKS_GRANTS_ONLY=1']"
    )
    for declaration in ("SPACEWORKS_RESTORE_IDENTITY=1", "SPACEWORKS_RESTORE_LEGACY_IDENTITY=1",
                        "SPACEWORKS_GRANT_DATABASE_NAME={temporary_database}"):
        assert declaration in ast.unparse(helper)
    assert ast.unparse(helper.body[-1]) == (
        "return self.compose(*args, 'orchestration-ready', input_bytes=identity)"
    )
    assert len(helper.body) == 5
    for node, condition, flag in zip(helper.body[1:4],
            ("identity is not None", "legacy", "temporary_database"),
            ("SPACEWORKS_RESTORE_IDENTITY=1", "SPACEWORKS_RESTORE_LEGACY_IDENTITY=1",
             "SPACEWORKS_GRANT_DATABASE_NAME={temporary_database}"), strict=True):
        assert isinstance(node, ast.If) and ast.unparse(node.test) == condition
        assert len(node.body) == 1 and isinstance(node.body[0], ast.AugAssign)
        assert flag in ast.unparse(node.body[0]) and not node.orelse
    assert not any(isinstance(node, ast.Try) for node in ast.walk(helper))
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        ready = compose.split("\n  orchestration-ready:\n", 1)[1].split("\n  worker:", 1)[0]
        if filename.endswith("prod.yml"):
            assert "<<: *host-bootstrap" in ready
            ready = compose.split("x-host-bootstrap: &host-bootstrap\n", 1)[1].split("\nservices:", 1)[0]
        assert 'user: "0:0"' in ready
        assert 'entrypoint: ["python", "/app/scripts/bootstrap_host_orchestration.py"]' in ready
        assert "DATABASE_URL:" in ready and "SPACEWORKS_RUNTIME_DATABASE_URL:" in ready
    tree = ast.parse((ROOT / "backend/scripts/bootstrap_host_orchestration.py").read_text())
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                   ((isinstance(node, ast.ImportFrom) and (node.module or "").startswith("django")) or
                    (isinstance(node, ast.Import) and any(alias.name.startswith("django") for alias in node.names)))
                   for node in ast.walk(tree))
    main = _function(tree, "main")
    gates = [node for node in main.body if isinstance(node, ast.If)
             and ast.unparse(node.test) == "os.environ.get('SPACEWORKS_GRANTS_ONLY') == '1'"]
    assert len(gates) == 1
    gate = gates[0]
    assert ast.unparse(gate.test) == "os.environ.get('SPACEWORKS_GRANTS_ONLY') == '1'"
    assert _calls(gate) == ["os.environ.get", "_grant_only"]
    assert isinstance(gate.body[-1], ast.Return) and not gate.orelse
    assert main.body.index(gate) < next(index for index, node in enumerate(main.body)
                                      if "validate_scheduler_environment" in _calls(node))
    grant = _function(tree, "_grant_only")
    calls = _calls(grant)
    for call in ("psycopg2.connect", "GrantTarget", "provision_runtime_role", "apply_grant_state"):
        assert call in calls
    assert "provision_runtime_role(cursor, target, runtime_password)" in ast.unparse(grant)
    assert "apply_grant_state(cursor, target, MarkerState.NORMAL)" in ast.unparse(grant)
    handler = next(node for node in ast.walk(grant) if isinstance(node, ast.ExceptHandler))
    assert any(isinstance(node, ast.Raise) for node in handler.body)
    imports = next(node for node in tree.body if isinstance(node, ast.ImportFrom)
                   and node.module == "apps.backup.database_grants")
    assert {"provision_runtime_role", "apply_grant_state"} <= {alias.name for alias in imports.names}
    service = ast.parse((ROOT / "backend/apps/backup/database_grants.py").read_text())
    provision = ast.unparse(_function(service, "provision_runtime_role"))
    apply = ast.unparse(_function(service, "apply_grant_state"))
    assert "CREATE ROLE {} NOLOGIN PASSWORD %s" in provision
    assert "_assert_narrow_runtime_role(cursor, target.runtime_role)" in provision
    assert "GRANT CONNECT ON DATABASE {} TO {}" in apply
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}" in apply


def assert_legacy_compound_refusal():
    wrapper = (ROOT / "scripts/restore.sh").read_text(encoding="utf-8")
    assert '"$ROOT/scripts/restore-host.py" import "$@"' in wrapper
    assert '"$ROOT/scripts/restore-host.py" restore "$@"' in wrapper
    tree = _tree("backend/apps/backup/backup_control_preflight.py")
    preflight = _function(tree, "run_restore_preflight")
    compound = next(node for node in preflight.body if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "kind == 'compound'")
    assert len(compound.body) == 1 and not compound.orelse
    assert ast.unparse(compound.body[0]) == "raise CommandError(COMPOUND_UNSUPPORTED)"
    assert preflight.body.index(compound) < _position(preflight, "_validate_legacy")
    assert "compound_host_unsupported" in (ROOT / "backend/apps/backup/full_format.py").read_text()
    assert ast.unparse(preflight.body[-1]) == (
        "return 'full-preflight-ok' if kind == 'full' else 'preflight-ok'"
    )
    inputs = _tree("backend/apps/backup/host_restore_prepare.py")
    route = ast.unparse(_function(inputs, "require_route"))
    assert "kind == FULL_FORMAT and facts.get('archive_protocol_version') == FULL_PROTOCOL" in route
    init = _function(inputs, "__init__")
    text = ast.unparse(init)
    assert text.index("self.kind != FULL_FORMAT") < text.index("'import_backup_archive'")
    assert "result.splitlines()[-1] != 'import-preflight-ok'" in text
    preflight = ast.unparse(_function(inputs, "preflight"))
    assert "expected = 'full-preflight-ok' if self.kind == FULL_FORMAT else 'preflight-ok'" in preflight
    assert "self.transport.control(*args).splitlines()[-1] != expected" in preflight
    # Both archive construction and lifecycle admission stay under the root lock.
    main = _function(_tree("scripts/restore-host.py"), "main")
    lock = next(node for node in main.body if isinstance(node, ast.With)
                and "host_operation_lock" in _calls(node))
    calls = _calls(lock)
    for call in ("read_marker", "admit_configuration", "inventory", "target_identity",
                 "RestoreInputs", "InplaceRestore", "operation.decision", "operation.restore"):
        assert call in calls
    assert "operation.retain_failure" in calls
