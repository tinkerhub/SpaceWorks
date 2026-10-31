"""Bounded source inspection of the eight QR API owners and their admission edges."""

import ast
from pathlib import Path

from .source_gate_ast import all_functions, parents, trees


BOX = "apps.boxes."
OPS = "apps.operations."
QR = BOX + "qr_admission."
TENANT = "apps.tenant_migration."
# Independent policy facts: never import the runtime declaration being inspected.
EXPECTED = {
    "qr-boxes": (BOX + "api_views_qr.CreateBoxQrView", BOX + "api_views.CreateBoxQrView",
                 (("create_box_with_qr", BOX + "services.create_box_with_qr"),)),
    "qr-tools": (BOX + "api_views_qr.CreateToolQrView", BOX + "api_views.CreateToolQrView",
                 (("create_tool_qr", QR + "create_tool_qr"),)),
    "qr-scan": (BOX + "api_views_qr.QrScanView", BOX + "api_views.QrScanView",
                (("admitted_qr", QR + "admitted_qr"),)),
    "qr-resolve": (BOX + "api_views_qr.QrResolveView", BOX + "api_views.QrResolveView",
                   (("admitted_qr", QR + "admitted_qr"),)),
    "qr-revoke": (BOX + "api_views_qr.QrRevokeView", BOX + "api_views.QrRevokeView",
                  (("revoke_qr_code", BOX + "services.revoke_qr_code"),)),
    "qr-rebind-target": (BOX + "api_views_qr.QrRebindTargetView", BOX + "api_views.QrRebindTargetView",
                         (("preflight_rebind", BOX + "rebind.preflight_rebind"),
                          ("rebind_qr_target", BOX + "rebind.rebind_qr_target"))),
    "asset-generate": (OPS + "views_qr_batches.AssetGenerateView", OPS + "views.AssetGenerateView",
                       (("services.generate_assets_with_qr", OPS + "services_qr_assets.generate_assets_with_qr"),)),
    "asset-qr": (OPS + "views_qr_batches.AssetQrView", OPS + "views.AssetQrView",
                 (("qr_write", QR + "qr_write"),)),
}


def same(node, source):
    if node is None:
        return False
    # Reparse expressions so Store/Load contexts do not affect target comparisons.
    actual = ast.parse(ast.unparse(node), mode="eval").body
    return ast.dump(actual) == ast.dump(ast.parse(source, mode="eval").body)


def require(condition, error_class, detail):
    if not condition:
        raise error_class("QR API source contract: " + detail)


def unique(body, kind, name, error_class):
    found = [n for n in body if isinstance(n, kind) and n.name == name]
    require(len(found) == 1, error_class, "missing/duplicate owner " + name)
    return found[0]


def source_tree(apps_dir, module):
    return ast.parse((Path(apps_dir) / (module.removeprefix("apps.").replace(".", "/") + ".py"))
                     .read_text(encoding="utf-8-sig"))


def require_local_owner(tree, name, error_class):
    node = unique(tree.body, (ast.FunctionDef, ast.AsyncFunctionDef), name, error_class)
    require(isinstance(node, ast.FunctionDef), error_class, "asynchronous replacement of owner " + name)
    require(not any((isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id == name)
                    or (isinstance(n, (ast.Import, ast.ImportFrom))
                        and any((a.asname or a.name) == name for a in n.names))
                    for n in ast.walk(tree)), error_class, "substituted local owner " + name)
    return node


def require_binding(tree, module, local, canonical, error_class, function=None):
    """Inspect one known import, including local imports; refuse shadowed bindings."""
    nodes = list(tree.body) + (list(ast.walk(function)) if function else [])
    matches = []
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = ".".join(module.split(".")[:-node.level]) + ("." + base if base else "")
            for alias in node.names:
                if (alias.asname or alias.name) == local:
                    matches.append(base + "." + alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) == local:
                    matches.append(alias.name if alias.asname else alias.name.split(".")[0])
    require(matches == [canonical], error_class, "noncanonical import " + local)
    # No later assignment, argument, definition or wildcard may replace this import.
    chain = parents(tree)
    for scope in (tree, function):
        if scope is None:
            continue
        for node in ast.walk(scope):
            if scope is tree and node is not tree:
                # Descendants of functions/classes are checked only in the consumed owner.
                ancestor = chain.get(node)
                nested = False
                while ancestor is not None:
                    if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        nested = True
                        break
                    ancestor = chain.get(ancestor)
                if nested:
                    continue
            require(not (isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
                         and node.id == local)
                    and not (isinstance(node, ast.arg) and node.arg == local)
                    and not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                             and node.name == local)
                    and not (isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names)),
                    error_class, "shadowed import " + local)


def validate_declaration(tree, error_class):
    assignments = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
                   and isinstance(n.ctx, ast.Store) and n.id == "API_OWNED_HTTP_BOUNDARIES"]
    declarations = [n.value for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "API_OWNED_HTTP_BOUNDARIES"
                            for t in n.targets)]
    require(len(assignments) == len(declarations) == 1 and isinstance(declarations[0], ast.Dict),
            error_class, "one literal API declaration required")
    declaration = declarations[0]
    keys = [k.value for k in declaration.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    # Before literal_eval/dict conversion: duplicate keys and ** unpacking must fail.
    require(len(keys) == len(declaration.keys) == len(set(keys)), error_class, "duplicate/nonliteral API key")
    try:
        actual = ast.literal_eval(declaration)
    except (ValueError, TypeError, SyntaxError):
        actual = None
    require(actual == EXPECTED, error_class, "API routes, tuple shapes or owners changed")
    references = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
                  and isinstance(n.ctx, ast.Load) and n.id == "API_OWNED_HTTP_BOUNDARIES"]
    require(len(references) == 1, error_class, "API declaration mutated or reused outside exact lookup")


def validate_routes(apps_dir, error_class):
    routes = {}
    for path, module, tree in trees(apps_dir):
        if not path.name.startswith("urls"):
            continue
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            for kw in call.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    routes.setdefault(kw.value.value, []).append((module, tree, call))
    config = Path(apps_dir).parent / "config" / "urls.py"
    if config.exists():
        tree = ast.parse(config.read_text(encoding="utf-8-sig"))
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            for kw in call.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    routes.setdefault(kw.value.value, []).append(("config.urls", tree, call))
    posts = {}
    for route, (canonical, barrel, bindings) in EXPECTED.items():
        require(len(routes.get(route, [])) == 1, error_class, "missing/duplicate URL " + route)
        module, tree, call = routes[route][0]
        alias_module, class_name = barrel.rsplit(".", 1)
        local = "api_views" if route.startswith("qr-") else "views"
        require(module == alias_module.rsplit(".", 1)[0] + ".urls" and len(call.args) == 2
                and same(call.func, "path") and same(call.args[1], f"{local}.{class_name}.as_view()"),
                error_class, "URL callback changed: " + route)
        require_binding(tree, module, "path", "django.urls.path", error_class)
        require_binding(tree, module, local, alias_module, error_class)
        require_binding(source_tree(apps_dir, alias_module), alias_module, class_name, canonical, error_class)
        owner_module = canonical.rsplit(".", 1)[0]
        owner_tree = source_tree(apps_dir, owner_module)
        klass = unique(owner_tree.body, ast.ClassDef, class_name, error_class)
        post = unique(klass.body, (ast.FunctionDef, ast.AsyncFunctionDef), "post", error_class)
        require(isinstance(post, ast.FunctionDef), error_class, "asynchronous API POST replacement")
        require(not any(isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id == "post"
                        for statement in klass.body if statement is not post for n in ast.walk(statement)),
                error_class, "class substitutes its own POST")
        require_binding(owner_tree, owner_module, "APIView", "rest_framework.views.APIView", error_class)
        require(any(same(b, "APIView") for b in klass.bases), error_class, "API class base changed")
        posts[canonical] = post
        for expression, owner in bindings:
            implementation, function_name = owner.rsplit(".", 1)
            implementation_tree = source_tree(apps_dir, implementation)
            require_local_owner(implementation_tree, function_name, error_class)
            calls = [n for n in ast.walk(post) if isinstance(n, ast.Call) and same(n.func, expression)]
            require(len(calls) == 1, error_class, "POST lost consumed expression " + expression)
            chain = parents(post)
            statement = calls[0]
            while chain.get(statement) is not post and statement in chain:
                statement = chain[statement]
            require(isinstance(statement, (ast.Assign, ast.With)), error_class, "POST owner call is conditional/deferred")
            local = expression.split(".")[0]
            target = OPS + "services" if "." in expression else owner
            require_binding(owner_tree, owner_module, local, target, error_class, post)
            if "." in expression:
                require_binding(source_tree(apps_dir, target), target, expression.split(".")[1], owner, error_class)
    return posts


def _within(node, context, parent_map):
    while node in parent_map:
        node = parent_map[node]
        if node is context:
            return True
    return False


def validate_admission(apps_dir, posts, error_class):
    functions = all_functions(apps_dir)
    edges = (
        (BOX + "services.create_box_with_qr", "boundary_tenant_write(box.makerspace_id)",
         TENANT + "gate_runtime.boundary_tenant_write"),
        (QR + "create_tool_qr", "qr_write([makerspace_id])", QR + "qr_write"),
        (QR + "admitted_qr", "qr_write([initial.makerspace_id])", QR + "qr_write"),
        (BOX + "services.revoke_qr_code", "qr_write([initial.makerspace_id])", QR + "qr_write"),
        (BOX + "rebind.rebind_qr_target", "qr_write(makerspace_ids)", QR + "qr_write"),
        (OPS + "services_qr_assets.generate_assets_with_qr", "qr_write([initial.makerspace_id])", QR + "qr_write"),
        (OPS + "views_qr_batches.AssetQrView.post", "qr_write([initial_makerspace_id])", QR + "qr_write"),
        (QR + "qr_write", "qr_sources(makerspace_ids)", QR + "qr_sources"),
    )
    for target, expression, canonical in edges:
        class_path = target.removesuffix(".post")
        node = posts.get(class_path) if target.endswith(".post") else functions.get(target)
        require(node is not None, error_class, "missing admission owner " + target)
        module = (class_path if target.endswith(".post") else target).rsplit(".", 1)[0]
        tree = source_tree(apps_dir, module)
        if not target.endswith(".post"):
            require_local_owner(tree, target.rsplit(".", 1)[1], error_class)
            require(all(same(d, "contextmanager") for d in node.decorator_list),
                    error_class, "admission owner acquired an outer wrapper")
        local = expression.split("(", 1)[0]
        if canonical not in {QR + "qr_write", QR + "qr_sources"} or module != QR.rstrip("."):
            require_binding(tree, module, local, canonical, error_class, node)
        else:
            require_local_owner(tree, local, error_class)
        contexts = [n for n in node.body if isinstance(n, ast.With)
                    and any(same(i.context_expr, expression) for i in n.items)]
        require(len(contexts) == 1, error_class, "admission context changed: " + target)
        context = contexts[0]
        if target in {BOX + "services.create_box_with_qr", QR + "qr_write"}:
            require(len(context.items) == 2 and same(context.items[1].context_expr, "transaction.atomic()"),
                    error_class, "admission no longer surrounds atomic commit")
            require_binding(tree, module, "transaction", "django.db.transaction", error_class)
        else:
            require(len(context.items) == 1, error_class, "admission context acquired an extra wrapper")
        parent_map = parents(node)
        # Real writes/yields, not an unused with block, must remain under admission.
        protected = [n for n in ast.walk(node) if isinstance(n, (ast.Yield, ast.YieldFrom))
                     or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                         and n.func.attr in {"save", "create", "get_or_create", "select_for_update", "record"})
                     or (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                         and n.func.id in {"fresh_qr", "_rebind_locked", "move_asset_across_makerspaces",
                                           "_create_asset_qr", "box_write_makerspace"})]
        require(bool(protected) and all(_within(n, context, parent_map) for n in protected),
                error_class, "write/yield escaped admission: " + target)
    sources = unique(source_tree(apps_dir, QR.rstrip(".")).body, ast.FunctionDef, "qr_sources", error_class)
    require(len(sources.body) == 1 and isinstance(sources.body[0], ast.With)
            and len(sources.body[0].items) == 1
            and same(sources.body[0].items[0].context_expr, "ExitStack()")
            and same(sources.body[0].items[0].optional_vars, "stack"), error_class, "QR source stack changed")
    body = sources.body[0].body
    require(len(body) == 2 and isinstance(body[0], ast.For)
            and same(body[0].target, "pk")
            and same(body[0].iter, "sorted({int(pk) for pk in makerspace_ids})")
            and len(body[0].body) == 1 and not body[0].orelse
            and isinstance(body[0].body[0], ast.Expr)
            and same(body[0].body[0].value, "stack.enter_context(boundary_tenant_write(pk))")
            and isinstance(body[1], ast.Expr) and isinstance(body[1].value, ast.Yield),
            error_class, "QR sources lost sorted retained tenant boundaries")
    tree = source_tree(apps_dir, QR.rstrip("."))
    require_binding(tree, QR.rstrip("."), "boundary_tenant_write", TENANT + "gate_runtime.boundary_tenant_write", error_class)
    require_binding(tree, QR.rstrip("."), "ExitStack", "contextlib.ExitStack", error_class)
    for name in ("qr_sources", "qr_write", "admitted_qr"):
        require(any(same(d, "contextmanager") for d in functions[QR + name].decorator_list),
                error_class, "QR admission lost contextmanager: " + name)
    require_binding(tree, QR.rstrip("."), "contextmanager", "contextlib.contextmanager", error_class)
