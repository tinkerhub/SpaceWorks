"""Bounded structural proofs for two retained, all-or-nothing admission loops.

These independent AST contracts pin executable ordering, not runtime source or
hashes. Formatting, comments and owner docstrings do not participate. Returning
the proven call nodes lets fan-out discovery keep rejecting every other raw loop.
This is source drift detection, not a proof against dynamic Python monkeypatching.
"""

import ast
from pathlib import Path

from .source_gate_api_owned_bindings import require_binding, require_local_owner


CLAIM = "apps.accounts.claim_transition_gate"
QR = "apps.boxes.qr_admission"
TENANT = "apps.tenant_migration."

# Complete membership scope, including inactive/revoked rows: no status predicate.
MEMBERSHIPS = '''
def _membership_makerspace_ids(user_id):
    return frozenset(
        MakerspaceMembership.objects.filter(user_id=user_id)
        .values_list("makerspace_id", flat=True)
    )
'''

# Nested reuse is identity-bound. Held keys constrain ordering but cannot replace
# the complete membership query. Every context survives the yield and reset.
CLAIM_GATE = '''
@contextmanager
def claim_transition_gate(user_id):
    admitted = _admitted_transition.get()
    if admitted is not None:
        if admitted[0] != user_id:
            raise SourceMigrationGateUnavailable("A different identity transition is active.")
        yield
        return
    makerspace_ids = _membership_makerspace_ids(user_id)
    held_ids = (_retained_shared_lock_keys() | frozenset(_boundary_shared_locks.get())) - {0}
    new_ids = makerspace_ids - held_ids
    if new_ids and held_ids and min(new_ids) < max(held_ids):
        raise SourceMigrationGateUnavailable(
            "Retry this identity transition from the central administration origin "
            "to preserve makerspace lock order."
        )
    with ExitStack() as locks:
        for makerspace_id in sorted(makerspace_ids):
            locks.enter_context(boundary_tenant_write(makerspace_id))
        token = _admitted_transition.set((user_id, makerspace_ids))
        try:
            yield
        finally:
            _admitted_transition.reset(token)
'''

# The post-row-lock check permits shrinkage only, never a newly discovered tenant.
CLAIM_SCOPE = '''
def assert_claim_transition_scope(user_id):
    admitted = _admitted_transition.get()
    if admitted is None or admitted[0] != user_id:
        raise SourceMigrationGateUnavailable("The identity transition has no source admission.")
    if not _membership_makerspace_ids(user_id).issubset(admitted[1]):
        raise ClaimTransitionScopeChanged()
'''

SCOPE_ERROR = '''
class ClaimTransitionScopeChanged(APIException):
    status_code = 409
    default_code = "identity_scope_changed"
    default_detail = "This identity's makerspace scope changed. Please retry."
'''

# Independent of validate_admission: its API-route and canonical-binding checks
# remain active. No route fixtures are required merely to classify this loop.
QR_GATE = '''
@contextmanager
def qr_sources(makerspace_ids):
    with ExitStack() as stack:
        for pk in sorted({int(pk) for pk in makerspace_ids}):
            stack.enter_context(boundary_tenant_write(pk))
        yield
'''


def _require(condition, error_class, detail):
    if not condition:
        raise error_class("atomic source admission contract: " + detail)


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _executable(node):
    """Copy a function without its leading documentation; retain all code."""
    node = ast.parse(ast.unparse(node)).body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)):
        node.body = node.body[1:]
    return node


def _prove_function(tree, name, expected, error_class):
    node = require_local_owner(tree, name, error_class)
    _require(_dump(_executable(node)) == _dump(ast.parse(expected).body[0]),
             error_class, "unsupported executable shape: " + name)
    return node


def _module_scope(tree):
    """Visit bindings at module scope, including conditional imports/definitions."""
    for node in ast.iter_child_nodes(tree):
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _module_scope(node)


def _binds(node, name):
    if isinstance(node, ast.Name):
        return node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == name
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return any((a.asname or (a.name.split(".")[0] if isinstance(node, ast.Import)
                                else a.name)) == name or a.name == "*" for a in node.names)
    # Exception and pattern bindings are strings rather than ast.Name stores.
    return ((isinstance(node, ast.ExceptHandler) and node.name == name)
            or (isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == name)
            or (isinstance(node, ast.MatchMapping) and node.rest == name))


def _binding(tree, module, local, canonical, error_class):
    require_binding(tree, module, local, canonical, error_class)
    _no_global_rebinding(tree, local, error_class)
    bindings = [n for n in _module_scope(tree) if _binds(n, local)]
    # The shared helper proves the canonical top-level import. This additional
    # census excludes conditional imports and string-valued binding substitutions.
    _require(len(bindings) == 1 and bindings[0] in tree.body
             and isinstance(bindings[0], (ast.Import, ast.ImportFrom)),
             error_class, "shadowed canonical import: " + local)


def _builtin(tree, name, error_class):
    _no_global_rebinding(tree, name, error_class)
    _require(not any(_binds(n, name) for n in _module_scope(tree)),
             error_class, "shadowed builtin: " + name)


def _local(tree, name, owner, error_class):
    # Keep the exact local function/context variable from being replaced by a
    # second module-level definition, import, deletion or conditional assignment.
    _no_global_rebinding(tree, name, error_class)
    bindings = [n for n in _module_scope(tree) if _binds(n, name)]
    _require(bindings == [owner], error_class, "substituted local binding: " + name)


def _no_global_rebinding(tree, name, error_class):
    _require(not any(isinstance(n, ast.Global) and name in n.names for n in ast.walk(tree)),
             error_class, "deferred global rebinding: " + name)


def _claim(tree, error_class):
    for name, expected in (("claim_transition_gate", CLAIM_GATE),
                           ("_membership_makerspace_ids", MEMBERSHIPS),
                           ("assert_claim_transition_scope", CLAIM_SCOPE)):
        node = _prove_function(tree, name, expected, error_class)
        _local(tree, name, node, error_class)
    declarations = [n for n in tree.body if isinstance(n, ast.Assign)
                    and _dump(n) == _dump(ast.parse(
                        '_admitted_transition = ContextVar("claim_transition_admission", default=None)'
                    ).body[0])]
    _require(len(declarations) == 1, error_class, "missing unique admission ContextVar")
    _local(tree, "_admitted_transition", declarations[0].targets[0], error_class)
    scope_errors = [n for n in tree.body if isinstance(n, ast.ClassDef)
                    and _dump(n) == _dump(ast.parse(SCOPE_ERROR).body[0])]
    _require(len(scope_errors) == 1, error_class, "missing canonical scope exception")
    _local(tree, "ClaimTransitionScopeChanged", scope_errors[0], error_class)
    for local, canonical in (
        ("APIException", "rest_framework.exceptions.APIException"),
        ("ContextVar", "contextvars.ContextVar"),
        ("MakerspaceMembership", "apps.makerspaces.models.MakerspaceMembership"),
        ("SourceMigrationGateUnavailable", TENANT + "gate_errors.SourceMigrationGateUnavailable"),
        ("_retained_shared_lock_keys", TENANT + "gate_locks._retained_shared_lock_keys"),
        ("_boundary_shared_locks", TENANT + "gate_runtime._boundary_shared_locks"),
    ):
        _binding(tree, CLAIM, local, canonical, error_class)
    for name in ("frozenset", "min", "max"):
        _builtin(tree, name, error_class)


def validate_atomic_admission(apps_dir, functions, error_class):
    """Return only proven raw calls; absent wrappers in synthetic trees are fine."""
    proven = set()
    for module, name, expected in ((CLAIM, "claim_transition_gate", CLAIM_GATE),
                                   (QR, "qr_sources", QR_GATE)):
        path = Path(apps_dir) / (module.removeprefix("apps.").replace(".", "/") + ".py")
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        if not any(_binds(n, name) for n in _module_scope(tree)):
            continue
        _builtin(tree, "__builtins__", error_class)
        owner = _prove_function(tree, name, expected, error_class)
        _local(tree, name, owner, error_class)
        if module == CLAIM:
            _claim(tree, error_class)
        for local, canonical in (("ExitStack", "contextlib.ExitStack"),
                                 ("contextmanager", "contextlib.contextmanager"),
                                 ("boundary_tenant_write", TENANT + "gate_runtime.boundary_tenant_write")):
            _binding(tree, module, local, canonical, error_class)
        for builtin in (("sorted", "int") if module == QR else ("sorted",)):
            _builtin(tree, builtin, error_class)
        discovered = functions.get(module + "." + name)
        _require(discovered is not None and _dump(discovered) == _dump(owner),
                 error_class, "discovery/owner mismatch: " + module + "." + name)
        proven.update(n for n in ast.walk(discovered) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name) and n.func.id == "boundary_tenant_write")
    return frozenset(proven)
