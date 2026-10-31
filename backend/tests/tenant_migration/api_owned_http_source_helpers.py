"""Small edits of CURRENT real QR sources; never execute the supplied source tree."""
import ast
from copy import deepcopy
from pathlib import Path

APPS = Path(__file__).resolve().parents[2] / "apps"
OWNERSHIP = "tenant_migration/gate_http_ownership.py"
MIDDLEWARE = "tenant_migration/middleware.py"
LATE = "tenant_migration/gate_runtime.py"
FILES = (
    OWNERSHIP, MIDDLEWARE, LATE,
    "boxes/api_views_qr.py", "boxes/api_views.py", "boxes/urls.py",
    "boxes/qr_admission.py", "boxes/services.py", "boxes/rebind.py",
    "operations/views_qr_batches.py", "operations/views.py", "operations/urls.py",
    "operations/services.py", "operations/services_qr_assets.py",
)
# Policy facts deliberately independent of the runtime registry and validator EXPECTED.
ROUTES = (
    ("qr-boxes", "boxes", "CreateBoxQrView", "create_box_with_qr"),
    ("qr-tools", "boxes", "CreateToolQrView", "create_tool_qr"),
    ("qr-scan", "boxes", "QrScanView", "admitted_qr"),
    ("qr-resolve", "boxes", "QrResolveView", "admitted_qr"),
    ("qr-revoke", "boxes", "QrRevokeView", "revoke_qr_code"),
    ("qr-rebind-target", "boxes", "QrRebindTargetView", "rebind_qr_target"),
    ("asset-generate", "operations", "AssetGenerateView", "services.generate_assets_with_qr"),
    ("asset-qr", "operations", "AssetQrView", "qr_write"),
)
# Nine admission edges, including qr_sources -> boundary_tenant_write.
EDGES = (
    ("boxes/services.py", "create_box_with_qr", "boundary_tenant_write"),
    ("boxes/qr_admission.py", "create_tool_qr", "qr_write"),
    ("boxes/qr_admission.py", "admitted_qr", "qr_write"),
    ("boxes/services.py", "revoke_qr_code", "qr_write"),
    ("boxes/rebind.py", "rebind_qr_target", "qr_write"),
    ("operations/services_qr_assets.py", "generate_assets_with_qr", "qr_write"),
    ("operations/views_qr_batches.py", "AssetQrView.post", "qr_write"),
    ("boxes/qr_admission.py", "qr_write", "qr_sources"),
    ("boxes/qr_admission.py", "qr_sources", "ExitStack"),
)


def expression(text):
    return ast.parse(text, mode="eval").body


def owner(tree, dotted):
    node = tree
    for name in dotted.split("."):
        matches = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name]
        assert len(matches) == 1, (dotted, name)
        node = matches[0]
    return node


def replace_expression(node, before, after):
    """Replace exactly one structural expression; assert mutation really happened."""
    expected, replacement = expression(before), expression(after)

    class Replace(ast.NodeTransformer):
        count = 0

        def visit(self, item):
            if ast.dump(item) == ast.dump(expected):
                self.count += 1
                return deepcopy(replacement)
            return super().visit(item)

    change = Replace()
    result = change.visit(node)
    assert change.count == 1, (before, change.count)
    return result


class SourceCopy:
    def __init__(self, root):
        self.root = root
        for relative in FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((APPS / relative).read_bytes())

    def tree(self, relative):
        return ast.parse((self.root / relative).read_text(encoding="utf-8-sig"))

    def save(self, relative, tree):
        ast.fix_missing_locations(tree)
        text = ast.unparse(tree) + "\n"
        ast.parse(text)  # A syntax error is a broken fixture, never a successful refusal.
        (self.root / relative).write_text(text, encoding="utf-8")

    def edit(self, relative, edit):
        tree = self.tree(relative)
        edit(tree)
        self.save(relative, tree)

    def replace(self, relative, target, before, after):
        self.edit(relative, lambda t: replace_expression(owner(t, target), before, after))


def view_file(package):
    return package + ("/api_views_qr.py" if package == "boxes" else "/views_qr_batches.py")


def declaration_mutation(tree, route, defect):
    declaration = next(n for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "API_OWNED_HTTP_BOUNDARIES" for t in n.targets))
    value = declaration.value
    index = next(i for i, k in enumerate(value.keys) if k.value == route)
    if defect == "remove":
        del value.keys[index], value.values[index]
    elif defect == "duplicate":
        # The last value stays correct: literal_eval/dict last-wins must not hide drift.
        value.keys.insert(index, ast.Constant(route))
        value.values.insert(index, ast.Constant("wrong earlier declaration"))
    elif defect == "extra":
        value.keys.append(ast.Constant("extra-write"))
        value.values.append(deepcopy(value.values[index]))
    elif defect == "unpack":
        value.keys.append(None)
        value.values.append(ast.Dict(keys=[], values=[]))
    elif defect == "shape":
        old = value.values[index]
        value.values[index] = ast.List(elts=old.elts, ctx=ast.Load())
    elif defect == "owner":
        value.values[index].elts[0] = ast.Constant("apps.unrelated.UnownedView")
    else:
        raise AssertionError(defect)


def route_mutation(tree, route, defect):
    urls = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "urlpatterns" for t in n.targets))
    call = next(n for n in urls.elts if any(k.arg == "name" and k.value.value == route for k in n.keywords))
    if defect == "missing":
        urls.elts.remove(call)
    elif defect == "duplicate":
        urls.elts.append(deepcopy(call))
    elif defect == "callback":
        call.args[1] = expression("unrelated_callback")
    elif defect == "class":
        call.args[1].func.value.attr = "UnrelatedView"
    else:
        raise AssertionError(defect)


def post_mutation(tree, klass, defect):
    node = owner(tree, klass)
    post = owner(node, "post")
    if defect == "remove":
        node.body.remove(post)
        if not node.body:
            node.body.append(ast.Pass())
    elif defect == "substitute":
        node.body.append(ast.parse("post = unrelated_post").body[0])
    elif defect == "duplicate":
        node.body.append(deepcopy(post))
    else:
        raise AssertionError(defect)


def consumed_mutation(tree, klass, consumed, defect):
    post = owner(tree, klass + ".post")
    calls = [n for n in ast.walk(post) if isinstance(n, ast.Call) and ast.unparse(n.func) == consumed]
    call, = calls
    if defect in {"removed", "wrong-alias"}:
        # Keep the correct import entirely intact, but no longer consume it.
        call.func = expression("unowned_operation")
    elif defect == "conditional":
        statement, = [s for s in post.body if any(n is call for n in ast.walk(s))]
        index = post.body.index(statement)
        post.body[index] = ast.If(test=ast.Constant(False), body=[statement], orelse=[])
    elif defect == "shadow":
        post.body.insert(0, ast.parse(consumed.split(".")[0] + " = unowned_operation").body[0])
    else:
        raise AssertionError(defect)
    if defect == "wrong-alias":
        tree.body.append(ast.parse("from unrelated import operation as unowned_operation").body[0])


def admission_mutation(tree, target, local, defect):
    node = owner(tree, target)
    context, = [n for n in node.body if isinstance(n, ast.With)
               and any(isinstance(i.context_expr, ast.Call) and ast.unparse(i.context_expr.func) == local for i in n.items)]
    index = node.body.index(context)
    if defect == "removed":
        node.body[index:index + 1] = context.body
    elif defect == "unrelated":
        context.items[0].context_expr.func = expression("unrelated_boundary")
    elif defect == "noop":
        body = context.body
        context.body = [ast.Pass()]
        node.body[index + 1:index + 1] = body
    elif defect == "escaped":
        # Move an actual write/yield outside the retained source context.
        if target == "qr_sources":
            statement = context.body.pop(0)  # sorted enter_context loop
        else:
            candidates = [s for s in context.body if any(
                isinstance(n, (ast.Yield, ast.YieldFrom))
                or (isinstance(n, ast.Call) and ast.unparse(n.func) in {
                    "audit.record", "_rebind_locked", "move_asset_across_makerspaces",
                }) for n in ast.walk(s))]
            assert candidates, target
            statement = candidates[-1]
            context.body.remove(statement)
        if not context.body:
            context.body = [ast.Pass()]
        node.body.insert(index + 1, statement)
    else:
        raise AssertionError(defect)


def middleware_mutation(tree, defect):
    node = owner(tree, "SourceMigrationGateMiddleware.__call__")
    attempt, = [n for n in node.body if isinstance(n, ast.Try)
                and any(isinstance(s, ast.If) and ast.unparse(s.test) == "api_owns_http_boundary(request, match)" for s in n.body)]
    branch = attempt.body[1]
    context = branch.body[0]
    if defect == "removed":
        branch.body = context.body
    elif defect == "noop":
        branch.body = [ast.With(items=context.items, body=[ast.Pass()]), *context.body]
    elif defect == "below-tenant":
        index = node.body.index(attempt)
        node.body[index], node.body[index + 1] = node.body[index + 1], attempt
    elif defect == "early-tenant":
        node.body.insert(node.body.index(attempt), ast.parse("unused = _makerspace_ids(request, match)").body[0])
    else:
        raise AssertionError(defect)


def late_mutation(tree, defect):
    node = owner(tree, "assert_request_write_allowed")
    branch, = [n for n in node.body if isinstance(n, ast.If)
               and ast.unparse(n.test) == "api_owns_http_boundary(request, match)"]
    if defect == "owner-removed":
        node.body.remove(branch)
    elif defect == "p-removed":
        branch.body.pop(0)
    elif defect == "raise-removed":
        branch.body[0].body = [ast.Pass()]
    elif defect == "return-first":
        branch.body.reverse()
    elif defect == "early-authority":
        resolution, = [n for n in node.body if isinstance(n, ast.Assign)
                       and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == "authoritative_route_resolution"]
        node.body.remove(resolution)
        node.body.insert(node.body.index(branch), resolution)
    else:
        raise AssertionError(defect)
