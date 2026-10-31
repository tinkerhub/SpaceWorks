"""Negative drift proofs through fan-out discovery, using minimal real owners."""

import ast

import pytest

from apps.tenant_migration.source_gate_ast import APPS_DIR
from apps.tenant_migration.source_gate_fanout_guards import validate_fanout_gate_coverage
from apps.tenant_migration.source_gate_guards import (
    SourceGateCoverageError, validate_source_gate_coverage,
)


OWNERS = {
    "claim": ("accounts/claim_transition_gate.py", {
        "ClaimTransitionScopeChanged", "_membership_makerspace_ids",
        "claim_transition_gate", "assert_claim_transition_scope",
    }),
    "qr": ("boxes/qr_admission.py", {"qr_sources"}),
}


def _copy_owner(tmp_path, owner):
    relative, names = OWNERS[owner]
    tree = ast.parse((APPS_DIR / relative).read_text())
    if owner == "claim":
        nodes = [node for node in tree.body if isinstance(node, (ast.ImportFrom, ast.Assign))
                 or getattr(node, "name", None) in names]
    else:
        modules = {"contextlib", "apps.tenant_migration.gate_runtime"}
        nodes = [node for node in tree.body
                 if (isinstance(node, ast.ImportFrom) and node.module in modules)
                 or getattr(node, "name", None) in names]
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ast.unparse(ast.Module(body=nodes, type_ignores=[])) + "\n")
    return path


def _check(root):
    return validate_fanout_gate_coverage(
        root, participants={}, error_class=SourceGateCoverageError,
    )


def _replace(path, old, new):
    source = path.read_text()
    assert source.count(old) == 1, (old, source)
    source = source.replace(old, new)
    ast.parse(source)  # A syntax error cannot masquerade as a guard refusal.
    path.write_text(source)


def _acquisition(owner):
    return ("locks.enter_context(boundary_tenant_write(makerspace_id))"
            if owner == "claim" else "stack.enter_context(boundary_tenant_write(pk))")


@pytest.mark.parametrize("owner", OWNERS)
def test_real_minimal_atomic_owner_is_classified(tmp_path, owner):
    _copy_owner(tmp_path, owner)
    assert _check(tmp_path) == frozenset()


def test_atomic_classification_composes_with_real_total_coverage():
    coverage = validate_source_gate_coverage()
    assert set(coverage) == {"tasks", "webhooks", "http", "lifecycle", "objects", "fanouts"}
    assert all(coverage.values())


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("drift", [
    "partial", "unsorted", "reordered", "boundary-removed", "early-yield",
    "early-release", "swallowed-refusal",
])
def test_atomic_acquisition_drift_refuses_via_fanout(tmp_path, owner, drift):
    path = _copy_owner(tmp_path, owner)
    acquire = _acquisition(owner)
    stack = "locks" if owner == "claim" else "stack"
    iterable = "sorted(makerspace_ids)" if owner == "claim" else "sorted({int(pk) for pk in makerspace_ids})"
    if drift in {"partial", "unsorted", "reordered"}:
        replacement = {"partial": iterable + "[:1]", "unsorted": "makerspace_ids",
                       "reordered": "reversed(" + iterable + ")"}[drift]
        _replace(path, iterable, replacement)
    elif drift == "boundary-removed":
        _replace(path, acquire, "pass")
    elif drift == "early-yield":
        _replace(path, acquire, "yield\n            " + acquire)
    elif drift == "early-release":
        _replace(path, acquire, acquire + "\n            " + stack + ".close()")
    else:
        _replace(path, acquire, "try:\n                " + acquire
                 + "\n            except SourceMigrationGateUnavailable:\n                pass")
    with pytest.raises(SourceGateCoverageError, match="atomic source admission"):
        _check(tmp_path)


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("local,module", [
    ("boundary_tenant_write", "apps.tenant_migration.gate_runtime"),
    ("ExitStack", "contextlib"), ("contextmanager", "contextlib"),
])
def test_canonical_import_substitution_refuses(tmp_path, owner, local, module):
    path = _copy_owner(tmp_path, owner)
    tree = ast.parse(path.read_text())
    imported = next(node for node in tree.body if isinstance(node, ast.ImportFrom)
                    and node.module == module)
    original = ast.unparse(imported)
    alias = next(alias for alias in imported.names if alias.name == local)
    alias.name, alias.asname = "substitute", local
    _replace(path, original, ast.unparse(imported))
    with pytest.raises(SourceGateCoverageError, match="noncanonical import"):
        _check(tmp_path)


@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize("binding", ["sorted", "boundary_tenant_write", "ExitStack", "contextmanager"])
@pytest.mark.parametrize("form", ["assignment", "conditional", "deferred-global"])
def test_shadowed_canonical_or_builtin_binding_refuses(tmp_path, owner, binding, form):
    path = _copy_owner(tmp_path, owner)
    suffix = {
        "assignment": f"{binding} = unsafe\n",
        "conditional": f"if injected:\n    {binding} = unsafe\n",
        "deferred-global": f"def substitute():\n    global {binding}\n    {binding} = unsafe\n",
    }[form]
    path.write_text(path.read_text() + suffix)
    with pytest.raises(SourceGateCoverageError, match="shadowed|noncanonical|rebinding"):
        _check(tmp_path)


@pytest.mark.parametrize("old,new", [
    ("if admitted[0] != user_id:", "if False:"),
    ("if admitted is not None:", "if False:"),
    ("makerspace_ids = _membership_makerspace_ids(user_id)", "makerspace_ids = frozenset()"),
    ("filter(user_id=user_id)", "filter(user_id=user_id, is_active=True)"),
    ("min(new_ids) < max(held_ids)", "min(new_ids) > max(held_ids)"),
    (" - {0}", ""),
    ("(user_id, makerspace_ids)", "(user_id, held_ids)"),
    ("_admitted_transition.reset(token)", "pass"),
    ("admitted is None or admitted[0] != user_id", "admitted is None"),
    (".issubset(admitted[1])", ".issuperset(admitted[1])"),
    ('default_code = \'identity_scope_changed\'', 'default_code = \'ignored\''),
    ("default=None", "default=()"),
])
def test_claim_nested_identity_complete_scope_order_and_reset_drift_refuse(tmp_path, old, new):
    path = _copy_owner(tmp_path, "claim")
    _replace(path, old, new)
    with pytest.raises(SourceGateCoverageError, match="atomic source admission|substituted"):
        _check(tmp_path)


@pytest.mark.parametrize("binding", [
    "APIException", "ContextVar", "MakerspaceMembership", "SourceMigrationGateUnavailable",
    "_retained_shared_lock_keys", "_boundary_shared_locks", "_admitted_transition",
    "_membership_makerspace_ids", "claim_transition_gate", "assert_claim_transition_scope",
    "ClaimTransitionScopeChanged", "frozenset", "min", "max", "__builtins__",
])
def test_claim_dependency_substitution_is_not_classified(tmp_path, binding):
    path = _copy_owner(tmp_path, "claim")
    path.write_text(path.read_text() + f"\n{binding} = unsafe\n")
    with pytest.raises(SourceGateCoverageError, match="shadowed|substituted"):
        _check(tmp_path)


@pytest.mark.parametrize("binding", ["int", "qr_sources", "__builtins__"])
def test_qr_integer_normalization_and_owner_binding_cannot_be_substituted(tmp_path, binding):
    path = _copy_owner(tmp_path, "qr")
    path.write_text(path.read_text() + f"\n{binding} = unsafe\n")
    with pytest.raises(SourceGateCoverageError, match="shadowed|substituted"):
        _check(tmp_path)


@pytest.mark.parametrize("gate", ["tenant_write", "boundary_tenant_write"])
@pytest.mark.parametrize("location", ["unknown.py", "accounts/claim_transition_gate.py", "boxes/qr_admission.py"])
def test_atomic_classification_never_exempts_a_new_raw_loop(tmp_path, gate, location):
    _copy_owner(tmp_path, "claim")
    _copy_owner(tmp_path, "qr")
    path = tmp_path / location
    source = path.read_text() if path.exists() else ""
    path.write_text(source + f"\ndef unknown(items):\n    for item in items:\n"
                    f"        with {gate}(item):\n            yield item\n")
    with pytest.raises(SourceGateCoverageError, match="skip-and-count"):
        _check(tmp_path)


@pytest.mark.parametrize("mutation", ["rename", "remove"])
def test_renamed_or_removed_known_owner_cannot_hide_its_raw_loop(tmp_path, mutation):
    path = _copy_owner(tmp_path, "qr")
    # Renaming loses the exemption; removing the boundary inside a known owner
    # must still fail even though generic fan-out discovery sees no gate call.
    if mutation == "rename":
        _replace(path, "def qr_sources(", "def unclassified_sources(")
        match = "skip-and-count"
    else:
        _replace(path, _acquisition("qr"), "pass")
        match = "atomic source admission"
    with pytest.raises(SourceGateCoverageError, match=match):
        _check(tmp_path)
