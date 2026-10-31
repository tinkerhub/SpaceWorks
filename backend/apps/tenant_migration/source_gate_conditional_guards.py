"""Pin the five metadata/storage choices, their scope and preparation ordering.

Expression ASTs describe predicates and argument flow, not source formatting or
whole-body hashes. Ordinary service-boundary checks remain independently active.
"""

import ast


CONDITIONAL_WRITER_BOUNDARIES = {
    "apps.makerspaces.profile_services.save_profile": (
        "membership.makerspace_id", '"projects" in data', "tenant_write",
    ),
    "apps.machines.public_service_intake.submit_typed_request": (
        "makerspace.pk", "ids", "boundary_tenant_write",
    ),
    "apps.machines.public_printer_service.submit_request": (
        "makerspace.pk", "ids", "boundary_tenant_write",
    ),
    "apps.events.services_series.update_series": (
        "series.makerspace_id", "set(changes) & RECURRENCE_FIELDS", "boundary_tenant_write",
    ),
    "apps.admin_api.bulk_import_apply.apply_import": (
        "makerspace.pk",
        'any(item["action"] != "error" and item["data"].get("image_key", "") '
        'for item in preview["rows"])',
        "nullcontext",
    ),
}


def _shape(node):
    if isinstance(node, ast.AST):
        # Binding targets and expression uses have different load/store contexts.
        return type(node).__name__, tuple((field, _shape(value))
            for field, value in ast.iter_fields(node) if field != "ctx")
    if isinstance(node, list):
        return tuple(_shape(item) for item in node)
    return node


def _same(node, expression):
    return _shape(node) == _shape(ast.parse(expression, mode="eval").body)


def _calls(node, name):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)
            and (getattr(item.func, "id", None) or getattr(item.func, "attr", None)) == name]


def _require(condition, error, detail):
    if not condition:
        raise error(f"conditional service boundary drifted: {detail}")


def _one(nodes, error, detail):
    _require(len(nodes) == 1, error, detail)
    return nodes[0]


def _inside(scope, node):
    return any(item is node for item in ast.walk(scope))


def _assignment(node, name, error):
    stores = [item for item in ast.walk(node) if isinstance(item, ast.Name)
              and item.id == name and isinstance(item.ctx, ast.Store)]
    store = _one(stores, error, f"{node.name}: single {name} binding")
    return _one([item for item in ast.walk(node) if isinstance(item, ast.Assign)
                 and store in item.targets], error, f"{node.name}: {name} assignment")


def _with(statements, expression, error):
    return _one([item for item in statements if isinstance(item, ast.With)
                 and len(item.items) == 1 and _same(item.items[0].context_expr, expression)],
                error, f"with {expression}")


def _before(scope, earlier, later, error):
    first = _one([i for i, item in enumerate(scope.body) if _inside(item, earlier)], error, "earlier phase")
    last = _one([i for i, item in enumerate(scope.body) if _inside(item, later)], error, "later phase")
    _require(first < last, error, "preparation/verification must precede application atomic")


def _forwarded(call, name, expression, error):
    value = _one([kw.value for kw in call.keywords if kw.arg == name], error, f"forward {name}")
    _require(_same(value, expression), error, f"forward {name}={expression}")


def _conditional(node, scope, tenant, predicate, fallback, error):
    assignment = _assignment(node, "context", error)
    choice = assignment.value
    alternate = "None" if fallback == "nullcontext" else tenant
    _require(assignment in scope.body and isinstance(choice, ast.IfExp), error, node.name)
    _require(_same(choice.test, predicate)
             and _same(choice.body, f"storage_lifecycle({tenant})")
             and _same(choice.orelse, f"{fallback}({alternate})"), error, f"{node.name}: predicate/branches")
    owned = _with(scope.body, "context", error)
    _require(_same(owned.items[0].optional_vars, "guard"), error, "checked context ownership")
    bindings = [item for item in ast.walk(node) if isinstance(item, ast.Name)
                and item.id == "guard" and isinstance(item.ctx, ast.Store)]
    _require(bindings == [owned.items[0].optional_vars], error, "never replace the checked guard")
    _before(scope, assignment, owned, error)
    _require(len(_calls(node, "storage_lifecycle")) == 1, error, "single storage choice")
    _require(not any(_same(d, "transaction.atomic") or _same(d, "transaction.atomic()")
                     for d in node.decorator_list), error, "no outer atomic decorator")
    _require(all(_inside(owned, call) for call in _calls(node, "atomic")), error, "atomic outside boundary")
    return owned


def _verify(owned, predicate, error):
    branch = _one([item for item in owned.body if isinstance(item, ast.If)
                   and _same(item.test, predicate)], error, "conditional guard verification")
    verifies = _calls(owned, "verify")
    call = _one(verifies, error, "single outer guard verification")
    _require(_inside(branch, call) and _same(call, "guard.verify()") and not branch.orelse,
             error, "verify only an actual guard")
    return branch


def _intake(node, owned, typed, error):
    snapshot = _assignment(node, "ids", error)
    _require(snapshot in node.body and _same(snapshot.value, 'tuple(data.get("file_ids") or ())'),
             error, "immutable attachment snapshot")
    _before(node, snapshot, _assignment(node, "context", error), error)
    # The printer also uses file_ids as its error-dictionary key; only payload reads count.
    payload_reads = [call for call in ast.walk(node) if isinstance(call, ast.Call)
                     and isinstance(call.func, ast.Attribute) and _same(call.func.value, "data") and call.args
                     and isinstance(call.args[0], ast.Constant) and call.args[0].value == "file_ids"]
    _require(len(payload_reads) == 1 and _inside(snapshot, payload_reads[0])
             and not any(isinstance(item, ast.Subscript) and _same(item.value, "data")
                         and _same(item.slice, '"file_ids"') for item in ast.walk(node)),
             error, "never reread attachment IDs")
    empty = [item for item in owned.body if isinstance(item, ast.Assign)
             and any(_same(t, "prepared") for t in item.targets) and _same(item.value, "{}")]
    empty = _one(empty, error, "empty intake has no prepared objects")
    branch = _verify(owned, "ids", error)
    prepare = _one(_calls(node, "prepare_files"), error, "one attachment preparation")
    _require(_inside(branch, prepare) and _same(prepare, "prepare_files(makerspace.pk, ids, actor, guard)"),
             error, "prepare immutable IDs with checked guard")
    _require(any(isinstance(item, ast.Assign) and item.value is prepare
                 and len(item.targets) == 1 and _same(item.targets[0], "prepared") for item in branch.body),
             error, "retain prepared attachment map")
    _before(branch, prepare, _one(_calls(branch, "verify"), error, "verify prepared attachments"), error)
    atomic = _with(owned.body, "transaction.atomic()", error)
    _before(owned, empty, branch, error)
    _before(owned, branch, atomic, error)
    if typed:
        queues = _calls(node, "attachment_queue_id")
        _require(len(queues) == 2 and all(len(c.args) == 4 and _same(c.args[2], "ids") for c in queues),
                 error, "preflight and locked queue use immutable IDs")
        _require(sum(_inside(atomic, c) for c in queues) == 1, error, "locked queue recheck")
        locked = _one(_calls(node, "lock_attachments"), error, "locked attachment recheck")
        _require(_inside(atomic, locked) and _same(locked, "lock_attachments(space, actor, ids, queue)"),
                 error, "lock immutable attachment IDs")
    else:
        filters = [c for c in _calls(atomic, "filter") if any(k.arg == "id__in" for k in c.keywords)]
        locked = _one(filters, error, "printer attachment filter")
        _forwarded(locked, "id__in", "ids", error)
        _require(any(isinstance(item, ast.Compare) and _same(item, "len(files) != len(set(ids))")
                     for item in ast.walk(atomic)), error, "count immutable IDs")
    files = _assignment(node, "files", error)
    _require(_inside(atomic, files) and _inside(files.value, locked), error, "iterate locked attachments")
    finalize = _one(_calls(node, "finalize_file"), error, "attachment finalize")
    _one([item for item in ast.walk(atomic) if isinstance(item, ast.For)
          and _same(item.target, "file") and _same(item.iter, "files") and _inside(item, finalize)],
         error, "finalize only the locked attachments")
    _forwarded(finalize, "guard", "guard", error)
    _forwarded(finalize, "prepared", "prepared[file.pk]", error)


def _bulk(node, outer, owned, error):
    executable = [item for item in node.body if not (isinstance(item, ast.Expr)
                  and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str))]
    _require(executable == [outer], error, "bulk preview/admission/application require outer tenant boundary")
    preview = _one(_calls(node, "preview_import"), error, "bulk preview")
    _require(_same(preview, "preview_import(makerspace, rows, mapping, progress_callback)"),
             error, "preview callback inside outer boundary")
    admission = _one([item for item in outer.body if isinstance(item, ast.If)
                      and _same(item.test, 'not preview["valid"] and not allow_partial')], error, "parser admission")
    _require(len(admission.body) == 1 and isinstance(admission.body[0], ast.Return), error, "invalid preview return")
    _before(outer, preview, admission, error)
    _before(outer, admission, _assignment(node, "context", error), error)
    prepare = _one(_calls(node, "finalize_product_image"), error, "bulk image preparation")
    loop = _one([item for item in owned.body if isinstance(item, ast.For)
                 and _same(item.target, "item") and _same(item.iter, 'preview["rows"]')
                 and _inside(item, prepare)], error, "prepare normalized bulk rows")
    skip = _one([item for item in loop.body if isinstance(item, ast.If)
                 and _same(item.test, 'item["action"] == "error" or not key')], error, "skip ineligible image rows")
    _require(len(skip.body) == 1 and isinstance(skip.body[0], ast.Continue), error, "no empty-image storage calls")
    key = _assignment(node, "key", error)
    _require(key in loop.body and _same(key.value, 'item["data"].get("image_key", "")'), error, "normalized image key")
    _before(loop, key, skip, error)
    _before(loop, skip, prepare, error)
    atomic = _with(owned.body, "transaction.atomic()", error)
    _before(owned, prepare, atomic, error)
    verify = _verify(owned, "guard is not None", error)
    _before(owned, prepare, verify, error)
    _before(owned, verify, atomic, error)
    apply = _one(_calls(node, "_apply_import_row"), error, "bulk row application")
    _require(_inside(atomic, apply) and _same(apply,
             '_apply_import_row(actor, makerspace, item, preview["mapping"], prepared.get(item["row"]), guard)'),
             error, "prepared bulk row and guard forwarding")


def validate_conditional_service_boundaries(functions, error_class):
    for target, (tenant, predicate, fallback) in CONDITIONAL_WRITER_BOUNDARIES.items():
        node = functions.get(target)
        _require(node is not None, error_class, f"missing entrypoint {target}")
        scope = _with(node.body, "boundary_tenant_write(makerspace.pk)", error_class) if fallback == "nullcontext" else node
        owned = _conditional(node, scope, tenant, predicate, fallback, error_class)
        if node.name in {"submit_typed_request", "submit_request"}:
            _intake(node, owned, node.name == "submit_typed_request", error_class)
        elif node.name == "save_profile":
            atomic = _with(owned.body, "transaction.atomic()", error_class)
            projects = _one([item for item in atomic.body if isinstance(item, ast.If)
                             and _same(item.test, '"projects" in data')], error_class, "project presence branch")
            call = _one(_calls(node, "save_projects"), error_class, "project replacement")
            _require(_inside(projects, call) and _same(call, 'save_projects(profile, data["projects"], guard=guard)'),
                     error_class, "only the submitted project list can replace projects")
            _forwarded(call, "guard", "guard", error_class)
        elif node.name == "update_series":
            verify = _verify(owned, "guard is not None", error_class)
            call = _one(_calls(node, "_update_series"), error_class, "atomic series owner")
            _before(owned, verify, call, error_class)
            _require(_same(call, "_update_series(series, actor=actor, effective_from=effective_from, guard=guard, **changes)"),
                     error_class, "forward series changes into the atomic owner")
            _forwarded(call, "guard", "guard", error_class)
            inner = functions.get("apps.events.services_series._update_series")
            _require(inner is not None and any(_same(d, "transaction.atomic") for d in inner.decorator_list),
                     error_class, "series application remains atomic")
        else:
            _bulk(node, scope, owned, error_class)
