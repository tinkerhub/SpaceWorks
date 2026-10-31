"""Read-only AST controls supplement the actual PostgreSQL/HTTP boundary proofs."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def function(filename, name, class_name=None):
    tree = ast.parse((ROOT / "apps/tenant_migration" / filename).read_text())
    body = tree.body if class_name is None else next(
        node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)


def calls(node):
    return [ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)]


def test_api_delegation_precedes_tenant_resolution_and_only_retains_p_around_dispatch():
    dispatch = function("middleware.py", "__call__", "SourceMigrationGateMiddleware")
    owned = next(node for node in ast.walk(dispatch) if isinstance(node, ast.If)
                 and isinstance(node.test, ast.Call)
                 and ast.unparse(node.test.func) == "api_owns_http_boundary")
    assert len(owned.body) == 1 and isinstance(owned.body[0], ast.With)
    retained = owned.body[0]
    assert [ast.unparse(item.context_expr) for item in retained.items] == [
        "unscoped_writer_shared_boundary()",
    ]
    assert len(retained.body) == 1 and isinstance(retained.body[0], ast.Return)
    assert ast.unparse(retained.body[0].value) == "self.get_response(request)"
    resolution = next(node for node in ast.walk(dispatch) if isinstance(node, ast.Call)
                      and ast.unparse(node.func) == "_makerspace_ids")
    assert owned.end_lineno < resolution.lineno
    assert not set(calls(owned)) & {"shared_boundary", "boundary_tenant_write", "_makerspace_ids"}


def test_late_api_guard_revalidates_and_reads_contextvar_before_ordinary_resolution():
    late = function("gate_runtime.py", "assert_request_write_allowed")
    owned = next(node for node in late.body if isinstance(node, ast.If)
                 and isinstance(node.test, ast.Call)
                 and ast.unparse(node.test.func) == "api_owns_http_boundary")
    assert "_unscoped_writer_owned.get" in calls(owned)
    assert "SourceMigrationGateUnavailable" in calls(owned)
    assert isinstance(owned.body[-1], ast.Return)
    assert not set(calls(owned)) & {"assert_write_allowed", "authoritative_route_resolution"}
    resolution = next(node for node in ast.walk(late) if isinstance(node, ast.Call)
                      and ast.unparse(node.func) == "authoritative_route_resolution")
    assert owned.end_lineno < resolution.lineno


def test_invalid_claim_cleanup_really_precedes_refused_qr_policy_in_authentication():
    tree = ast.parse((ROOT / "apps/accounts/authentication.py").read_text())
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "SpaceWorksJWTAuthentication")
    claim = next(node for node in klass.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_authenticate_claim")
    validation = next(node for node in ast.walk(claim) if isinstance(node, ast.Call)
                      and ast.unparse(node.func) == "validated_claim_session")
    cleanup = next(node for node in ast.walk(claim) if isinstance(node, ast.Call)
                   and ast.unparse(node.func) == "expire_claim_presence")
    refused = next(node for node in ast.walk(claim) if isinstance(node, ast.If)
                   and ast.unparse(node.test) == "isinstance(policy, Refused)")
    assert validation.lineno < cleanup.lineno < refused.lineno
