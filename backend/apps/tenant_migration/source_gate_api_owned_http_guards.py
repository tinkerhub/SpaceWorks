"""Static QR HTTP delegation contract; inspect supplied sources, never import owners."""

import ast

from .source_gate_api_owned_bindings import (
    TENANT, require, require_binding, require_local_owner, same, source_tree, unique,
    validate_admission, validate_declaration, validate_routes,
)


OWNERSHIP = TENANT + "gate_http_ownership"


def _body(function):
    return [n for n in function.body if not (isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]


def _assignment(node, target, value, error_class):
    require(isinstance(node, ast.Assign) and len(node.targets) == 1
            and same(node.targets[0], target) and same(node.value, value),
            error_class, "ownership dataflow changed: " + target)


def _refusal(node, condition, error_class, exception="ValueError"):
    require(isinstance(node, ast.If) and same(node.test, condition) and not node.orelse
            and len(node.body) == 1 and isinstance(node.body[0], ast.Raise)
            and isinstance(node.body[0].exc, ast.Call)
            and same(node.body[0].exc.func, exception), error_class, "missing rejecting check: " + condition)


def _return(node, value, error_class):
    require(isinstance(node, ast.Return) and (node.value is None if value is None else same(node.value, value)),
            error_class, "ownership return changed")


def _runtime_owner(tree, error_class):
    node = unique(tree.body, ast.FunctionDef, "api_owns_http_boundary", error_class)
    body = _body(node)
    require(len(body) == 4, error_class, "API ownership dispatch structure changed")
    _assignment(body[0], "declaration", 'API_OWNED_HTTP_BOUNDARIES.get(getattr(match, "view_name", None))', error_class)
    require(isinstance(body[1], ast.If) and not body[1].orelse and len(body[1].body) == 1
            and same(body[1].test, 'declaration is None or request.method != "POST"'),
            error_class, "API ownership must decline undeclared/non-POST routes")
    _return(body[1].body[0], "False", error_class)
    attempt = body[2]
    require(isinstance(attempt, ast.Try) and len(attempt.handlers) == 1 and not attempt.orelse
            and not attempt.finalbody and len(attempt.body) == 4,
            error_class, "API ownership validation/failure structure changed")
    handler = attempt.handlers[0]
    require(same(handler.type, "Exception") and handler.name == "exc" and len(handler.body) == 1
            and isinstance(handler.body[0], ast.Raise) and same(handler.body[0].cause, "exc")
            and isinstance(handler.body[0].exc, ast.Call)
            and same(handler.body[0].exc.func, "SourceMigrationGateUnavailable"),
            error_class, "API ownership drift must fail closed")
    _assignment(attempt.body[0], "(canonical, alias, bindings)", "declaration", error_class)
    _assignment(attempt.body[1], "(view_class, post)", "_api_post(canonical, alias)", error_class)
    require(isinstance(attempt.body[2], ast.Expr)
            and same(attempt.body[2].value, "_validate_api_callback(match.func, view_class)"),
            error_class, "resolved callback validation removed")
    loop = attempt.body[3]
    require(isinstance(loop, ast.For) and same(loop.target, "(expression, owner_path)")
            and same(loop.iter, "bindings") and not loop.orelse and len(loop.body) == 5,
            error_class, "consumed-owner comparison loop changed")
    _assignment(loop.body[0], "owner", "import_string(owner_path)", error_class)
    _assignment(loop.body[1], "parts", 'expression.split(".")', error_class)
    _assignment(loop.body[2], "bound", "post.__globals__[parts[0]]", error_class)
    dotted = loop.body[3]
    require(isinstance(dotted, ast.If) and same(dotted.test, "len(parts) == 2")
            and not dotted.orelse and len(dotted.body) == 2,
            error_class, "generation consumed-module resolution changed")
    _refusal(dotted.body[0], 'bound is not import_module("apps.operations.services")', error_class)
    _assignment(dotted.body[1], "bound", "getattr(bound, parts[1])", error_class)
    _refusal(loop.body[4], "not callable(owner) or bound is not owner", error_class)
    _return(body[3], "True", error_class)
    for local, canonical in (("import_string", "django.utils.module_loading.import_string"),
                             ("import_module", "importlib.import_module"),
                             ("SourceMigrationGateUnavailable", TENANT + "gate_errors.SourceMigrationGateUnavailable")):
        require_binding(tree, OWNERSHIP, local, canonical, error_class, node)


def _runtime_post(tree, error_class):
    node = unique(tree.body, ast.FunctionDef, "_api_post", error_class)
    body = _body(node)
    require(len(body) == 7, error_class, "canonical API POST validation structure changed")
    _assignment(body[1], "(module_name, class_name)", 'canonical.rsplit(".", 1)', error_class)
    _assignment(body[2], "view_class", "import_string(canonical)", error_class)
    _refusal(body[3], 'not isinstance(view_class, type) or not issubclass(view_class, APIView) '
             'or view_class.__module__ != module_name or view_class.__qualname__ != class_name '
             'or import_string(alias) is not view_class', error_class)
    _assignment(body[4], "post", 'vars(view_class)["post"]', error_class)
    _refusal(body[5], 'not isfunction(post) or post.__module__ != module_name '
             'or post.__qualname__ != f"{class_name}.post" '
             'or post.__code__.co_qualname != f"{class_name}.post" '
             'or post.__globals__ is not vars(import_module(module_name))', error_class)
    _return(body[6], "(view_class, post)", error_class)
    require_binding(tree, OWNERSHIP, "APIView", "rest_framework.views.APIView", error_class, node)
    require_binding(tree, OWNERSHIP, "isfunction", "inspect.isfunction", error_class, node)
    require_binding(tree, OWNERSHIP, "import_string", "django.utils.module_loading.import_string", error_class, node)
    require_binding(tree, OWNERSHIP, "import_module", "importlib.import_module", error_class, node)


def _runtime_callback(tree, error_class):
    node = unique(tree.body, ast.FunctionDef, "_validate_api_callback", error_class)
    body = _body(node)
    require(len(body) == 7, error_class, "callback validation structure changed")
    _assignment(body[1], "expected", "APIView.as_view.__func__(view_class)", error_class)
    _assignment(body[2], "(core, expected_core)", "(callback.__wrapped__, expected.__wrapped__)", error_class)
    loop = body[3]
    require(isinstance(loop, ast.For) and same(loop.target, "(actual, reference)")
            and same(loop.iter, "((callback, expected), (core, expected_core))")
            and not loop.orelse and len(loop.body) == 1, error_class, "callback/core validation removed")
    _refusal(loop.body[0], 'not isfunction(actual) or actual.__code__ is not reference.__code__ '
             'or actual.__globals__ is not reference.__globals__ '
             'or actual.__defaults__ != reference.__defaults__ '
             'or actual.__kwdefaults__ != reference.__kwdefaults__ '
             'or actual.view_class is not view_class or actual.cls is not view_class '
             'or actual.view_initkwargs != {} or actual.initkwargs != {}', error_class)
    _assignment(body[4], "expected_wrapper_scope", "getclosurevars(expected).nonlocals", error_class)
    _assignment(body[5], "wrapper_scope", '{key: core if value is expected_core else value '
                'for key, value in expected_wrapper_scope.items()}', error_class)
    _refusal(body[6], 'getclosurevars(callback).nonlocals != wrapper_scope '
             'or getclosurevars(core).nonlocals != getclosurevars(expected_core).nonlocals', error_class)
    for local, canonical in (("APIView", "rest_framework.views.APIView"),
                             ("getclosurevars", "inspect.getclosurevars"), ("isfunction", "inspect.isfunction")):
        require_binding(tree, OWNERSHIP, local, canonical, error_class, node)


def _middleware(apps_dir, error_class):
    module = TENANT + "middleware"
    tree = source_tree(apps_dir, module)
    klass = unique(tree.body, ast.ClassDef, "SourceMigrationGateMiddleware", error_class)
    node = unique(klass.body, ast.FunctionDef, "__call__", error_class)
    # This branch must be a direct try before tenant discovery, never a nested/dead check.
    body = _body(node)
    attempts = [(i, n) for i, n in enumerate(body) if isinstance(n, ast.Try)
                and any(isinstance(c, ast.If) and same(c.test, "api_owns_http_boundary(request, match)")
                        for c in n.body)]
    require(len(attempts) == 1, error_class, "middleware lost verified API owner branch")
    index, attempt = attempts[0]
    require(len(attempt.body) == 2 and isinstance(attempt.body[0], ast.ImportFrom)
            and not attempt.orelse and not attempt.finalbody,
            error_class, "middleware owner validation must precede dispatch")
    require(len(attempt.handlers) == 2, error_class, "middleware must render owner failures")
    for handler, exception, response in zip(attempt.handlers,
            ("SourceMigrationGateClosed", "SourceMigrationGateUnavailable"),
            ("_locked_response(exc)", "_unavailable_response(exc)")):
        require(same(handler.type, exception) and handler.name == "exc" and len(handler.body) == 1,
                error_class, "middleware owner refusal handler changed")
        _return(handler.body[0], response, error_class)
    branch = attempt.body[1]
    require(not branch.orelse and len(branch.body) == 1 and isinstance(branch.body[0], ast.With),
            error_class, "middleware API owner lost retained P")
    context = branch.body[0]
    require(len(context.items) == 1
            and same(context.items[0].context_expr, "unscoped_writer_shared_boundary()")
            and len(context.body) == 1, error_class, "middleware P must surround dispatch")
    _return(context.body[0], "self.get_response(request)", error_class)
    require(index + 1 < len(body), error_class, "missing tenant discovery after API owner")
    _assignment(body[index + 1], "makerspace_ids", "_makerspace_ids(request, match)", error_class)
    # No earlier tenant resolution is allowed in an assignment, nested branch or try.
    require(not any(isinstance(n, ast.Call) and same(n.func, "_makerspace_ids")
                    for s in body[:index] for n in ast.walk(s)),
            error_class, "tenant resolution precedes API ownership")
    require_binding(tree, module, "api_owns_http_boundary", OWNERSHIP + ".api_owns_http_boundary", error_class, node)
    require_binding(tree, module, "unscoped_writer_shared_boundary",
                    TENANT + "gate_locks.unscoped_writer_shared_boundary", error_class, node)


def _late_guard(apps_dir, error_class):
    module = TENANT + "gate_runtime"
    tree = source_tree(apps_dir, module)
    node = unique(tree.body, ast.FunctionDef, "assert_request_write_allowed", error_class)
    body = _body(node)
    matches = [(i, n) for i, n in enumerate(body) if isinstance(n, ast.If)
               and same(n.test, "api_owns_http_boundary(request, match)")]
    require(len(matches) == 1, error_class, "late guard lost same API owner validation")
    index, branch = matches[0]
    require(not branch.orelse and len(branch.body) == 2, error_class, "late owner branch changed")
    _refusal(branch.body[0], "not _unscoped_writer_owned.get()", error_class, "SourceMigrationGateUnavailable")
    _return(branch.body[1], None, error_class)
    # Before revalidation only the safe-method return, imports and match binding may run.
    safe = body[0]
    require(isinstance(safe, ast.If) and same(safe.test, 'request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}')
            and len(safe.body) == 1 and not safe.orelse, error_class, "late safe-method restriction changed")
    _return(safe.body[0], None, error_class)
    prefix = body[1:index]
    assignments = [s for s in prefix if isinstance(s, ast.Assign)]
    require(len(assignments) == 1 and all(isinstance(s, (ast.ImportFrom, ast.Assign)) for s in prefix),
            error_class, "late guard resolves/returns before revalidating ownership")
    _assignment(assignments[0], "match", 'getattr(request, "resolver_match", None)', error_class)
    resolutions = [i for i, s in enumerate(body) if any(isinstance(n, ast.Call)
                   and same(n.func, "authoritative_route_resolution") for n in ast.walk(s))]
    require(len(resolutions) == 1 and resolutions[0] > index, error_class, "late authoritative resolution reordered")
    for local, canonical in (("api_owns_http_boundary", OWNERSHIP + ".api_owns_http_boundary"),
                             ("_unscoped_writer_owned", TENANT + "gate_locks._unscoped_writer_owned"),
                             ("SourceMigrationGateUnavailable", TENANT + "gate_errors.SourceMigrationGateUnavailable")):
        require_binding(tree, module, local, canonical, error_class, node)


def validate_api_owned_http_boundaries(apps_dir, error_class):
    """Fail closed on drift of the bounded QR route, binding and P → N contracts."""
    tree = source_tree(apps_dir, OWNERSHIP)
    for name in ("api_owns_http_boundary", "_api_post", "_validate_api_callback"):
        function = require_local_owner(tree, name, error_class)
        require(not function.decorator_list, error_class, "runtime ownership acquired a wrapper")
    validate_declaration(tree, error_class)
    posts = validate_routes(apps_dir, error_class)
    validate_admission(apps_dir, posts, error_class)
    _runtime_owner(tree, error_class)
    _runtime_post(tree, error_class)
    _runtime_callback(tree, error_class)
    _middleware(apps_dir, error_class)
    _late_guard(apps_dir, error_class)
