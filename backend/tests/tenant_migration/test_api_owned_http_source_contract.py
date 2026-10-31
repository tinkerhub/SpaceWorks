"""Adversarial supplied-source proofs; Root alone collects/runs this module."""
import ast

import pytest

from apps.tenant_migration.source_gate_api_owned_http_guards import validate_api_owned_http_boundaries
from tests.tenant_migration.api_owned_http_source_helpers import (
    APPS, EDGES, FILES, LATE, MIDDLEWARE, OWNERSHIP, ROUTES, SourceCopy,
    admission_mutation, consumed_mutation, declaration_mutation, expression,
    late_mutation, middleware_mutation, owner, post_mutation, route_mutation, view_file,
)


class SuppliedSourceRefusal(Exception):
    """The validator must use its caller's error type, not incidental parser errors."""


@pytest.fixture
def source(tmp_path):
    copied = SourceCopy(tmp_path / "backend/apps")
    assert len(FILES) == 14
    assert copied.root.resolve() != APPS.resolve()
    validate_api_owned_http_boundaries(copied.root, SuppliedSourceRefusal)
    return copied


def refuse(source, category):
    with pytest.raises(SuppliedSourceRefusal, match="QR API source contract: .*" + category):
        validate_api_owned_http_boundaries(source.root, SuppliedSourceRefusal)


@pytest.mark.parametrize("formatting", [False, True], ids=["unchanged", "ast-formatting"])
def test_current_supplied_tree_is_valid_without_source_hash_matching(source, formatting):
    for path in FILES:
        assert (source.root / path).read_bytes() == (APPS / path).read_bytes()
        if formatting:
            source.save(path, source.tree(path))
    if formatting:
        assert any((source.root / p).read_bytes() != (APPS / p).read_bytes() for p in FILES)
    validate_api_owned_http_boundaries(source.root, SuppliedSourceRefusal)


@pytest.mark.parametrize("route", [r[0] for r in ROUTES])
@pytest.mark.parametrize("defect", ["remove", "duplicate", "extra", "unpack", "shape", "owner"])
def test_literal_registry_is_exact_and_duplicate_checked_before_last_wins(source, route, defect):
    source.edit(OWNERSHIP, lambda t: declaration_mutation(t, route, defect))
    refuse(source, "duplicate/nonliteral API key" if defect in {"duplicate", "unpack"}
           else "API routes, tuple shapes or owners changed")


@pytest.mark.parametrize("route,package,klass,consumed", ROUTES)
@pytest.mark.parametrize("defect", ["missing", "duplicate", "callback", "class"])
def test_actual_named_url_and_as_view_expression_are_owned(source, route, package, klass, consumed, defect):
    source.edit(package + "/urls.py", lambda t: route_mutation(t, route, defect))
    refuse(source, "missing/duplicate URL" if defect in {"missing", "duplicate"} else "URL callback changed")


def test_cross_config_duplicate_name_is_also_rejected(source):
    path = source.root.parent / "config/urls.py"
    path.parent.mkdir()
    path.write_text('from django.urls import path\nurlpatterns = [path("other", other, name="qr-boxes")]\n')
    refuse(source, "missing/duplicate URL qr-boxes")


@pytest.mark.parametrize("route,package,klass,consumed", ROUTES)
@pytest.mark.parametrize("defect", ["remove", "substitute", "duplicate"])
def test_each_canonical_class_requires_its_own_unique_post(source, route, package, klass, consumed, defect):
    source.edit(view_file(package), lambda t: post_mutation(t, klass, defect))
    refuse(source, "substitutes its own POST" if defect == "substitute" else "missing/duplicate owner post")


@pytest.mark.parametrize("route,package,klass,consumed", ROUTES)
def test_url_facing_barrel_cannot_reexport_a_different_class(source, route, package, klass, consumed):
    def change(tree):
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
                   and any(a.name == klass for a in n.names)]
        node, = imports
        imported, = [a for a in node.names if a.name == klass]
        node.names.remove(imported)
        if not node.names:
            tree.body.remove(node)
        tree.body.append(ast.ImportFrom(module="unrelated", names=[ast.alias(name=klass)], level=0))
    source.edit(package + ("/api_views.py" if package == "boxes" else "/views.py"), change)
    refuse(source, "noncanonical import " + klass)


@pytest.mark.parametrize("route,package,klass,consumed", ROUTES)
def test_canonical_class_cannot_be_replaced_in_its_defining_module(source, route, package, klass, consumed):
    source.edit(view_file(package), lambda t: setattr(owner(t, klass), "name", "Unrelated" + klass))
    refuse(source, "missing/duplicate owner " + klass)


BINDINGS = (*ROUTES, ("qr-rebind-preflight", "boxes", "QrRebindTargetView", "preflight_rebind"))


@pytest.mark.parametrize("route,package,klass,consumed", BINDINGS)
@pytest.mark.parametrize("defect", ["removed", "wrong-alias", "conditional", "shadow"])
def test_post_must_consume_the_canonical_import_not_an_unused_correct_one(source, route, package, klass, consumed, defect):
    source.edit(view_file(package), lambda t: consumed_mutation(t, klass, consumed, defect))
    refuse(source, "shadowed import" if defect == "shadow" else "POST (lost consumed expression|owner call is conditional/deferred)")


def test_generation_service_barrel_must_export_the_actual_implementation(source):
    def change(tree):
        node, = [n for n in tree.body if isinstance(n, ast.ImportFrom)
                 and any(a.name == "generate_assets_with_qr" for a in n.names)]
        item, = [a for a in node.names if a.name == "generate_assets_with_qr"]
        item.asname = "unused_correct_generation"
        tree.body.append(ast.parse("from unrelated import generate_assets_with_qr").body[0])
    source.edit("operations/services.py", change)
    refuse(source, "noncanonical import generate_assets_with_qr")


@pytest.mark.parametrize("path,target,local", EDGES)
@pytest.mark.parametrize("defect", ["removed", "unrelated", "noop", "escaped"])
def test_all_nine_admission_edges_retain_real_work_inside_source_context(source, path, target, local, defect):
    source.edit(path, lambda t: admission_mutation(t, target, local, defect))
    refuse(source, "admission|QR source|POST lost consumed expression")


@pytest.mark.parametrize("path,target,local", [e for e in EDGES if e[1] in {
    "create_box_with_qr", "create_tool_qr", "revoke_qr_code", "generate_assets_with_qr", "AssetQrView.post",
}])
def test_audit_record_alone_cannot_escape_its_actual_admission(source, path, target, local):
    def change(tree):
        function = owner(tree, target)
        statements = [s for s in ast.walk(function) if isinstance(s, ast.Expr)
                      and isinstance(s.value, ast.Call) and ast.unparse(s.value.func) == "audit.record"]
        statement, = statements
        parent, = [n for n in ast.walk(function) if isinstance(getattr(n, "body", None), list) and statement in n.body]
        parent.body.remove(statement)
        if not parent.body:
            parent.body.append(ast.Pass())
        function.body.append(statement)
    source.edit(path, change)
    refuse(source, "write/yield escaped admission")


@pytest.mark.parametrize("path,target,local", EDGES)
def test_canonical_admission_imports_cannot_be_shadowed_or_left_unused(source, path, target, local):
    def change(tree):
        if local in {"qr_sources", "qr_write"} and path == "boxes/qr_admission.py":
            # Preserve the canonical function but substitute the binding actually used.
            tree.body.append(ast.parse(local + " = unrelated_boundary").body[0])
        else:
            imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                       and any((a.asname or a.name) == local for a in n.names)]
            node, = imports
            item, = [a for a in node.names if (a.asname or a.name) == local]
            item.asname = "unused_correct_" + local
            tree.body.append(ast.parse("from unrelated import boundary as " + local).body[0])
    source.edit(path, change)
    refuse(source, "noncanonical import|substituted local owner")


@pytest.mark.parametrize("defect", ["remove", "duplicate"])
def test_literal_declaration_itself_must_exist_once(source, defect):
    def change(tree):
        declaration, = [n for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "API_OWNED_HTTP_BOUNDARIES" for t in n.targets)]
        if defect == "remove":
            tree.body.remove(declaration)
        else:
            tree.body.append(ast.parse(ast.unparse(declaration)).body[0])
    source.edit(OWNERSHIP, change)
    refuse(source, "one literal API declaration required")


@pytest.mark.parametrize("before,after", [
    ("boundary_tenant_write(pk)", "unrelated_boundary(pk)"),
    ("stack.enter_context(boundary_tenant_write(pk))", "boundary_tenant_write(pk)"),
    ("stack.enter_context(boundary_tenant_write(pk))", "None"),
    ("sorted({int(pk) for pk in makerspace_ids})", "makerspace_ids"),
])
def test_qr_sources_consumes_and_retains_actual_sorted_tenant_contexts(source, before, after):
    source.replace("boxes/qr_admission.py", "qr_sources", before, after)
    refuse(source, "QR sources lost sorted retained tenant boundaries")


@pytest.mark.parametrize("relative,local", [
    ("boxes/urls.py", "path"), ("boxes/urls.py", "api_views"),
    ("operations/urls.py", "path"), ("operations/urls.py", "views"),
    ("boxes/api_views_qr.py", "APIView"), ("operations/views_qr_batches.py", "APIView"),
    ("boxes/qr_admission.py", "boundary_tenant_write"),
])
def test_route_class_and_leaf_boundary_bindings_cannot_be_shadowed(source, relative, local):
    source.edit(relative, lambda t: t.body.append(ast.parse(local + " = unrelated_operation").body[0]))
    refuse(source, "shadowed import " + local)


# Mutate actual expressions in the runtime proof, never fake resolver metadata.
RUNTIME_EXPRESSIONS = (
    ("api_owns_http_boundary", 'declaration is None or request.method != "POST"', "declaration is None", "non-POST"),
    ("api_owns_http_boundary", 'API_OWNED_HTTP_BOUNDARIES.get(getattr(match, "view_name", None))', "unrelated_registry.get(match.view_name)", "declaration mutated or reused"),
    ("api_owns_http_boundary", "_validate_api_callback(match.func, view_class)", "unrelated_callback_check(match.func, view_class)", "callback validation removed"),
    ("api_owns_http_boundary", "not callable(owner) or bound is not owner", "not callable(owner)", "missing rejecting check"),
    ("api_owns_http_boundary", 'bound is not import_module("apps.operations.services")', "False", "missing rejecting check"),
    ("api_owns_http_boundary", "post.__globals__[parts[0]]", "unrelated_globals[parts[0]]", "dataflow"),
    ("_api_post", 'vars(view_class)["post"]', 'getattr(view_class, "post")', "dataflow"),
)
CLASS_TERMS = (
    "not isinstance(view_class, type)", "not issubclass(view_class, APIView)",
    "view_class.__module__ != module_name", "view_class.__qualname__ != class_name",
    "import_string(alias) is not view_class",
)
POST_TERMS = (
    "not isfunction(post)", "post.__module__ != module_name",
    'post.__qualname__ != f"{class_name}.post"', 'post.__code__.co_qualname != f"{class_name}.post"',
    "post.__globals__ is not vars(import_module(module_name))",
)
CALLBACK_TERMS = (
    "not isfunction(actual)", "actual.__code__ is not reference.__code__",
    "actual.__globals__ is not reference.__globals__", "actual.__defaults__ != reference.__defaults__",
    "actual.__kwdefaults__ != reference.__kwdefaults__", "actual.view_class is not view_class",
    "actual.cls is not view_class", "actual.view_initkwargs != {}", "actual.initkwargs != {}",
    "getclosurevars(callback).nonlocals != wrapper_scope",
    "getclosurevars(core).nonlocals != getclosurevars(expected_core).nonlocals",
)
IDENTITY_EXPRESSIONS = tuple(
    (function, term, "False", "missing rejecting check")
    for function, terms in (("_api_post", CLASS_TERMS + POST_TERMS), ("_validate_api_callback", CALLBACK_TERMS))
    for term in terms
)


@pytest.mark.parametrize("target,before,after,category", RUNTIME_EXPRESSIONS + IDENTITY_EXPRESSIONS)
def test_runtime_proof_cannot_drop_post_alias_callback_or_consumed_identity(source, target, before, after, category):
    source.replace(OWNERSHIP, target, before, after)
    refuse(source, category)


@pytest.mark.parametrize("local", ["import_string", "import_module", "isfunction", "getclosurevars"])
def test_runtime_canonical_import_cannot_be_shadowed(source, local):
    source.edit(OWNERSHIP, lambda t: t.body.append(ast.parse(local + " = unrelated_operation").body[0]))
    refuse(source, "shadowed import " + local)


@pytest.mark.parametrize("defect", ["removed", "noop", "below-tenant", "early-tenant"])
def test_middleware_retains_p_around_dispatch_before_tenant_resolution(source, defect):
    source.edit(MIDDLEWARE, lambda t: middleware_mutation(t, defect))
    refuse(source, "middleware|tenant resolution precedes API ownership|dataflow")


@pytest.mark.parametrize("defect", ["owner-removed", "p-removed", "raise-removed", "return-first", "early-authority"])
def test_late_guard_revalidates_owner_and_p_before_return_or_authority(source, defect):
    source.edit(LATE, lambda t: late_mutation(t, defect))
    refuse(source, "late guard|late owner|missing rejecting check")


def test_late_guard_cannot_trust_an_unrelated_p_flag(source):
    source.replace(LATE, "assert_request_write_allowed", "not _unscoped_writer_owned.get()", "not unrelated_owned.get()")
    refuse(source, "missing rejecting check")


@pytest.mark.parametrize("path,target,local", [
    (MIDDLEWARE, "SourceMigrationGateMiddleware.__call__", "unscoped_writer_shared_boundary"),
    (MIDDLEWARE, "SourceMigrationGateMiddleware.__call__", "api_owns_http_boundary"),
    (LATE, "assert_request_write_allowed", "_unscoped_writer_owned"),
    (LATE, "assert_request_write_allowed", "api_owns_http_boundary"),
])
def test_middleware_and_late_guard_use_canonical_imports(source, path, target, local):
    source.edit(path, lambda t: owner(t, target).body.append(ast.parse(local + " = unrelated_operation").body[0]))
    refuse(source, "shadowed import")


def test_actual_global_http_guard_wires_api_validator_only_in_apps_dir_branch():
    tree = ast.parse((APPS / "tenant_migration/source_gate_http_guards.py").read_text())
    function = owner(tree, "validate_authenticated_http_boundary")
    branch, = [n for n in function.body if isinstance(n, ast.If)
               and ast.dump(n.test) == ast.dump(expression("Path(apps_dir).resolve() == APPS_DIR"))]
    imported, = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                 and n.module == "source_gate_api_owned_http_guards"]
    assert imported.level == 1 and len(imported.names) == 1
    assert imported.names[0].name == "validate_api_owned_http_boundaries" and imported.names[0].asname is None
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == "validate_api_owned_http_boundaries"]
    call, = calls
    assert imported in branch.body
    statement, = [s for s in branch.body if isinstance(s, ast.Expr) and s.value is call]
    assert branch.body.index(imported) < branch.body.index(statement)
    assert ast.dump(call) == ast.dump(expression("validate_api_owned_http_boundaries(apps_dir, error_class)"))
