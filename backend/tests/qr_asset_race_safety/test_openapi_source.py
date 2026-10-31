"""Read only the actual AssetQr annotation, without schema/type generation."""
import ast
from pathlib import Path


def asset_post():
    path = Path(__file__).resolve().parents[2] / "apps/operations/views_qr_batches.py"
    tree = ast.parse(path.read_text())
    view = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                and node.name == "AssetQrView")
    return next(node for node in view.body if isinstance(node, ast.FunctionDef) and node.name == "post")


def test_actual_asset_qr_post_has_typed_source_423_and_503():
    post = asset_post()
    annotation = next(node for node in post.decorator_list if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == "extend_schema")
    responses = next(keyword.value for keyword in annotation.keywords if keyword.arg == "responses")
    entries = {key.value: value for key, value in zip(responses.keys, responses.values)
               if isinstance(key, ast.Constant)}
    for status, code in ((423, "tenant_migration_quiesced"),
                         (503, "tenant_migration_gate_unavailable")):
        response = entries[status]
        assert isinstance(response, ast.Call) and response.func.id == "OpenApiResponse"
        assert isinstance(response.args[0], ast.Name) and response.args[0].id == "ErrorSerializer"
        description = next(keyword.value.value for keyword in response.keywords
                           if keyword.arg == "description")
        assert code in description


def test_asset_qr_itself_retains_source_admission_around_locks_and_audit():
    # HTTP middleware also admits writes. Bind this service boundary explicitly so
    # that middleware coverage cannot hide accidental removal of qr_write here.
    post = asset_post()
    boundary = next(node for node in post.body if isinstance(node, ast.With))
    assert len(boundary.items) == 1
    admission = boundary.items[0].context_expr
    assert ast.unparse(admission) == "qr_write([initial_makerspace_id])"
    calls = [node for node in ast.walk(boundary) if isinstance(node, ast.Call)]
    module = next(node for node in calls if ast.unparse(node.func) == "require_module_locked")
    assert ast.unparse(module) == "require_module_locked(initial_makerspace_id, 'asset_units', no_key=True)"
    qr = next(node for node in calls if ast.unparse(node.func) == "QrCode.objects.select_for_update")
    asset = next(node for node in calls if ast.unparse(node.func) == "InventoryAsset.objects.select_for_update")
    audit = next(node for node in calls if ast.unparse(node.func) == "audit.record")
    assert module.lineno < qr.lineno < asset.lineno < audit.lineno
    final_actor = max(node.lineno for node in calls
                      if ast.unparse(node.func) == "current_qr_actor")
    permission = next(node for node in calls if ast.unparse(node.func) == "require_action")
    assert asset.lineno < final_actor < permission.lineno < audit.lineno
