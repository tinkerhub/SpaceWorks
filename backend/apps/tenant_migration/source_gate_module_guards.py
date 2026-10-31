"""Concrete module-purge, install, counter and supervised rollback call contracts."""

import ast
from pathlib import Path


def _calls(node, name):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)
            and (getattr(item.func, "id", None) or getattr(item.func, "attr", None)) == name]


def _methods(path, klass):
    tree = ast.parse(Path(path).read_text())
    owner = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == klass), None)
    return {n.name: n for n in owner.body if isinstance(n, ast.FunctionDef)} if owner else {}


def _inside_with(owner, boundary, name):
    for item in ast.walk(owner):
        if isinstance(item, ast.With) and any(_calls(expr.context_expr, boundary) for expr in item.items):
            body = ast.Module(body=item.body, type_ignores=[])
            if _calls(body, name):
                return True
    return False


def validate_module_cleanup_boundaries(apps_dir, functions, error_class):
    root = Path(apps_dir)

    def require(value, message):
        if not value:
            raise error_class(message)

    required = {"apps.makerspaces.module_install._apply", "apps.makerspaces.module_purge_receipts.execute_cleanup",
                "apps.backup.tasks.cleanup_expired_restore_rollbacks_task"}
    required.update(f"apps.backup.rollback_cleanup.{name}" for name in (
        "cleanup_rollback_objects", "cleanup_expired_rollback_objects", "_cleanup_expired", "_cleanup_restore",
    ))
    required.update(f"apps.makerspaces.module_install.{name}" for name in ("install_module", "uninstall_module", "apply_profile"))
    require(required <= functions.keys(), "a concrete module cleanup/install/rollback owner disappeared")
    for target in ("apps.makerspaces.module_purge.purge_module", "apps.makerspaces.module_purge_receipts.retry_cleanup"):
        node = functions.get(target)
        require(node is not None, f"module purge entry disappeared: {target}")
        boundaries = _calls(node, "purge_boundary")
        require(len(boundaries) == 1 and any(kw.arg == "all_tenants" and isinstance(kw.value, ast.Constant)
                and kw.value.value is True for kw in boundaries[0].keywords), f"module purge lost all-tenant exclusion: {target}")
        require(_inside_with(node, "purge_boundary", "execute_cleanup") and not _calls(node, "storage_lifecycle"),
                f"module cleanup lost its outer exclusive owner: {target}")
        require(_calls(node, "validate_receipt") and _calls(node, "validate_receipt")[0].lineno < boundaries[0].lineno,
                f"raw receipt must be bounded before advisory locks: {target}")
    for name in ("install_module", "uninstall_module", "apply_profile"):
        target = f"apps.makerspaces.module_install.{name}"
        require(_inside_with(functions[target], "boundary_tenant_write", "select_for_update"),
                f"module install lock ordering drifted: {target}")
        for item in ast.walk(functions[target]):
            if isinstance(item, ast.With) and any(_calls(expr.context_expr, "atomic") for expr in item.items):
                names = [(getattr(expr.context_expr.func, "id", None) or getattr(expr.context_expr.func, "attr", None))
                         for expr in item.items if isinstance(expr.context_expr, ast.Call)]
                require(names[:2] == ["boundary_tenant_write", "atomic"], f"module install boundary must precede SQL: {target}")
    apply = functions["apps.makerspaces.module_install._apply"]
    require(_calls(apply, "enabling_modules") and _calls(apply, "save")
            and _calls(apply, "enabling_modules")[0].lineno < _calls(apply, "save")[0].lineno,
            "module enable lost receipt invalidation before save")
    for target in ("cleanup_rollback_objects", "cleanup_expired_rollback_objects"):
        node = functions[f"apps.backup.rollback_cleanup.{target}"]
        require(_inside_with(node, "deployment_operation_lock", "unscoped_writer_shared_boundary"),
                f"rollback cleanup lost its actual outer host lock: {target}")
    require(_inside_with(functions["apps.backup.rollback_cleanup.cleanup_rollback_objects"],
                         "unscoped_writer_shared_boundary", "_cleanup_restore"),
            "direct rollback cleanup lost its retained outer unscoped fence")
    for name in ("_cleanup_restore", "_cleanup_expired"):
        node = functions[f"apps.backup.rollback_cleanup.{name}"]
        _validate_rollback_loop(node, require)
    _validate_rollback_outcomes(root, functions, require)
    command = _methods(root / "backup/management/commands/backup_control.py", "Command")
    require("handle" in command and _calls(command["handle"], "cleanup_rollback_objects"),
            "standalone rollback cleanup lost its actual fenced service caller")
    barrel = ast.parse((root / "backup/object_restore.py").read_text())
    imported = {item.name for node in barrel.body if isinstance(node, ast.ImportFrom)
                and node.module == "apps.backup.rollback_cleanup" for item in node.names}
    require({"cleanup_rollback_objects", "cleanup_expired_rollback_objects"} <= imported,
            "rollback cleanup public reexports drifted")
    task = functions["apps.backup.tasks.cleanup_expired_restore_rollbacks_task"]
    require(_calls(task, "cleanup_expired_rollback_objects"), "rollback expiry task lost its actual fenced owner")
    script = root.parent.parent / "scripts/restore.sh"
    require(script.is_file() and not any(line.lstrip().startswith("control cleanup-rollback ") for line in script.read_text().splitlines()),
            "supervised restore must retain rollback rows until standalone fenced cleanup")
    admin = _methods(root / "makerspaces/admin_capabilities.py", "MakerspaceCapabilityAdminMixin")
    require({"changeform_view", "save_model"} <= admin.keys(), "capability admin owner disappeared")
    require(_inside_with(admin["changeform_view"], "boundary_tenant_write", "changeform_view")
            and _calls(admin["save_model"], "assert_boundary_held")
            and _calls(admin["save_model"], "enabling_modules"),
            "capability admin lost its actual form boundary and save assertion")
    counter = _methods(root / "makerspaces/management/commands/recompute_storage.py", "Command")
    _validate_storage_counter(counter, require)
    execute = functions["apps.makerspaces.module_purge_receipts.execute_cleanup"]
    require(_inside_with(execute, "synchronous_cleanup", "settle")
            and _inside_with(execute, "atomic", "settle")
            and _inside_with(execute, "atomic", "record"),
            "module final graph/accounting/checkpoint/audit transaction drifted")


def _validate_storage_counter(counter, require):
    require({"handle", "_recompute", "_admit", "_commit"} <= counter.keys(), "storage counter owner disappeared")
    boundaries = _calls(counter["handle"], "fanout_tenant_write")
    require(len(boundaries) == 1 and any(
        kw.arg == "exclusive" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in boundaries[0].keywords
    ) and _inside_with(counter["handle"], "fanout_tenant_write", "_recompute"),
        "storage recomputation requires literal exclusive=True around its actual scan")
    require(_inside_with(counter["handle"], "fanout_tenant_write", "assert_no_inprogress"),
            "storage recomputation lost its module-purge preflight and warning disposition")
    scan, admit, commit = (counter[name] for name in ("_recompute", "_admit", "_commit"))
    for name in ("assert_boundary_held", "assert_no_inprogress", "servable_queryset"):
        require(_calls(admit, name), f"storage admission lost {name}")
    normal = ast.parse(
        "not DeploymentRecoveryState.objects.filter(pk=1, mode=DeploymentRecoveryState.Mode.NORMAL).exists()",
        mode="eval",
    ).body
    require(any(isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(normal)
                and len(node.body) == 1 and isinstance(node.body[0], ast.Raise)
                for node in admit.body), "storage admission must refuse a missing/non-normal recovery singleton")
    reload = ast.parse("makerspace = servable_queryset().filter(pk=makerspace_id).first()").body[0]
    require(any(ast.dump(node) == ast.dump(reload) for node in admit.body),
            "storage admission must reload the servable tenant under exclusion")
    require(_calls(scan, "_admit") and _calls(scan, "_sum") and len(_calls(scan, "_commit")) == 1
            and _calls(scan, "_admit")[0].lineno < _calls(scan, "_sum")[0].lineno < _calls(scan, "_commit")[0].lineno,
            "storage scan must reload/admit before HEADs and commit only after summing")
    for name in ("_admit", "_exclusive_boundary_connection", "execute", "commit"):
        require(len(_calls(commit, name)) == 1, f"storage commit lost its single {name} step")
    require(_calls(commit, "_admit")[0].lineno < _calls(commit, "_exclusive_boundary_connection")[0].lineno
            < _calls(commit, "execute")[0].lineno < _calls(commit, "commit")[0].lineno,
            "storage final admission/ownership/write/commit ordering drifted")
    expected_owner = ast.parse("lock_connection = _exclusive_boundary_connection(makerspace_id)").body[0]
    require(any(ast.dump(node) == ast.dump(expected_owner) for node in commit.body),
            "storage counter must use the actual context-owned exclusive connection")
    require(_inside_with(commit, "cursor", "execute")
            and ast.dump(_calls(commit, "cursor")[0].func) == ast.dump(ast.parse("lock_connection.cursor", mode="eval").body)
            and ast.dump(_calls(commit, "commit")[0].func) == ast.dump(ast.parse("lock_connection.commit", mode="eval").body),
            "storage setter and commit must use the retained lock backend")
    execute = _calls(commit, "execute")[0]
    require(ast.dump(execute.func) == ast.dump(ast.parse("cursor.execute", mode="eval").body)
            and any(isinstance(node, ast.With) and any(
                isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == "cursor"
                and isinstance(item.context_expr, ast.Call)
                and ast.dump(item.context_expr.func) == ast.dump(ast.parse("lock_connection.cursor", mode="eval").body)
                for item in node.items
            ) and execute in ast.walk(node) for node in ast.walk(commit)),
            "storage setter must execute on the retained connection's actual cursor")
    sql = """UPDATE makerspaces_makerspace SET storage_bytes_used = %s
             WHERE id = %s AND EXISTS (SELECT 1 FROM backup_deploymentrecoverystate
             WHERE id = 1 AND mode = 'normal')"""
    # Normalize whitespace only; identifiers, recovery predicate and bound values
    # remain a concrete contract rather than accepting arbitrary SQL plumbing.
    require(len(execute.args) == 2 and isinstance(execute.args[0], ast.Constant)
            and isinstance(execute.args[0].value, str)
            and " ".join(execute.args[0].value.split()).replace("( ", "(").replace(" )", ")") == " ".join(sql.split())
            and ast.dump(execute.args[1]) == ast.dump(ast.parse("[total, makerspace_id]", mode="eval").body),
            "storage counter lost its constant bound setter/recovery singleton predicate")
    rowcount = ast.dump(ast.parse("cursor.rowcount != 1", mode="eval").body)
    require(any(isinstance(node, ast.If) and ast.dump(node.test) == rowcount
                and len(node.body) == 1 and isinstance(node.body[0], ast.Raise)
                and execute.lineno < node.lineno < _calls(commit, "commit")[0].lineno
                for node in ast.walk(commit)), "storage counter must refuse unless exactly one row changed")
    require(not _calls(scan, "update") and not _calls(commit, "update"),
            "storage counter must not SET through a separate ORM connection")


def _validate_rollback_loop(node, require):
    # The general fan-out guard separately requires the actual skip-and-count
    # context and its first-statement continue. Here every delete must belong to
    # that context, or the explicit global-row branch owned by outer lock zero.
    guarded = set()
    for owner in ast.walk(node):
        if isinstance(owner, ast.With) and any(_calls(item.context_expr, "fanout_tenant_write") for item in owner.items):
            body = ast.Module(body=owner.body, type_ignores=[])
        elif isinstance(owner, ast.If) and ast.dump(owner.test) == ast.dump(ast.parse("row.makerspace_id is None", mode="eval").body):
            body = ast.Module(body=owner.body, type_ignores=[])
        else:
            continue
        deletes = _calls(body, "_delete_bytes")
        if deletes:
            frozen = _calls(body, "_frozen")
            require(frozen and frozen[0].lineno < min(item.lineno for item in deletes),
                    "rollback cleanup lost frozen-intent exclusion before bytes")
            guarded.update(id(item) for item in deletes)
    deletes = _calls(node, "_delete_bytes")
    require(deletes and all(id(item) in guarded for item in deletes),
            "rollback byte cleanup escaped the tenant fan-out or global-row boundary")
    require(_inside_with(node, "fanout_tenant_write", "_settle"),
            "rollback settlement lost its retained tenant boundary")


def _outcome_before(body, argument, targets, require):
    expected = ast.dump(ast.parse(argument, mode="eval").body)
    guards = []
    for statement in body:
        value = getattr(statement, "value", None)
        if isinstance(statement, (ast.Expr, ast.Assign)) and isinstance(value, ast.Call):
            if isinstance(value.func, ast.Name) and value.func.id == "require_cleanup_outcome":
                guards.append(value)
    require(len(guards) == 1 and len(guards[0].args) == 1 and not guards[0].keywords
            and ast.dump(guards[0].args[0]) == expected,
            "rollback cleanup lost its unconditional fresh outcome check")
    guard = guards[0]
    owner = ast.Module(body=body, type_ignores=[])
    for target in targets:
        calls = _calls(owner, target)
        require(calls and all(guard.lineno < call.lineno for call in calls),
                f"rollback outcome must precede {target}")
    return guard


def _validate_rollback_outcomes(root, functions, require):
    prefix = "apps.backup.rollback_cleanup."
    qualifier = "apps.backup.rollback_cleanup_outcomes.require_cleanup_outcome"
    require({qualifier, prefix + "_delete_bytes", prefix + "_settle"} <= functions.keys(),
            "actual rollback outcome owner disappeared")
    tree = ast.parse((root / "backup/rollback_cleanup.py").read_text())
    require(any(isinstance(node, ast.ImportFrom) and node.module == "apps.backup.rollback_cleanup_outcomes"
                and any(item.name == "require_cleanup_outcome" and item.asname is None for item in node.names)
                for node in tree.body), "rollback outcome check lost its actual companion import")
    outcome = functions[qualifier]
    # Pin the actual read-only DB owner, rather than a fixture helper or cached stage.
    reads = {ast.dump(node) for node in ast.walk(outcome) if isinstance(node, ast.Call)}
    for expression in (
        'DeploymentRecoveryState.objects.filter(pk=1).only("mode", "active_restore_id").first()',
        'RestoreOperation.objects.filter(pk=restore_id).only("stage").first()',
        'RestoreOperation.objects.filter(pk=state.active_restore_id).values_list("stage", flat=True).first()',
    ):
        require(ast.dump(ast.parse(expression, mode="eval").body) in reads,
                "rollback outcome lost a fresh recovery/selected/active DB read")
    require(not any(_calls(outcome, name) for name in (
        "load", "get_or_create", "update", "save", "delete", "client", "delete_all_versions",
    )), "rollback outcome authority must remain read-only")
    direct = functions[prefix + "cleanup_rollback_objects"]
    boundary = next((node for node in ast.walk(direct) if isinstance(node, ast.With)
                     and any(_calls(item.context_expr, "unscoped_writer_shared_boundary") for item in node.items)), None)
    require(boundary is not None, "rollback direct outcome lost its unscoped boundary")
    _outcome_before(boundary.body, "restore.pk", ("_cleanup_restore",), require)
    delete = functions[prefix + "_delete_bytes"]
    _outcome_before(delete.body, "row.restore_id", ("bucket_name", "client", "delete_all_versions", "delete_object"), require)
    require(not any(isinstance(node, ast.Attribute) and node.attr == "stage" for node in ast.walk(delete)),
            "rollback deletion must rely on the fresh outcome, never a cached stage")
    settle = functions[prefix + "_settle"]
    atomic = next((node for node in ast.walk(settle) if isinstance(node, ast.With)
                   and any(_calls(item.context_expr, "atomic") for item in node.items)), None)
    require(atomic is not None, "rollback settlement lost its transaction")
    guard = _outcome_before(atomic.body, "locked.restore_id", ("free_storage", "delete"), require)
    for name in ("select_for_update", "_binding", "_frozen"):
        calls = _calls(atomic, name)
        require(calls and all(call.lineno < guard.lineno for call in calls),
                "rollback outcome settlement check must follow the locked binding check")
    require(not any(_calls(atomic, name) for name in ("client", "delete_all_versions", "delete_object")),
            "rollback settlement cannot perform provider I/O")
    expiry = functions[prefix + "_cleanup_expired"]
    loop = next((node for node in expiry.body if isinstance(node, ast.For)), None)
    require(loop is not None and isinstance(loop.body[0], ast.Try), "rollback expiry lost its per-row refusal boundary")
    _outcome_before(loop.body[0].body, "row.restore_id", ("_delete_bytes", "_settle", "_frozen"), require)
