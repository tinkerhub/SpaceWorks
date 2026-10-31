"""Validate exclusive service-owned routes without weakening other HTTP fences."""

import ast
from collections import Counter
from pathlib import Path

from .gate_http_ownership import SERVICE_OWNED_HTTP_BOUNDARIES
from .source_gate_ast import all_functions
from .source_gate_service_guards import calls_named


def validate_service_owned_http_boundaries(apps_dir, error_class):
    functions = all_functions(apps_dir)
    paths = list(Path(apps_dir).rglob("urls*.py"))
    config_urls = Path(apps_dir).parent / "config" / "urls.py"
    if config_urls.exists():
        paths.append(config_urls)
    routes = {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = next((kw.value for kw in call.keywords if kw.arg == "name"), None)
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                routes.setdefault(name.value, []).append((path, tree, call))
    registry = Path(apps_dir) / "tenant_migration" / "gate_http_ownership.py"
    tree = ast.parse(registry.read_text(encoding="utf-8-sig"))
    declaration = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "SERVICE_OWNED_HTTP_BOUNDARIES"
                               for t in node.targets))
    keys = [key.value for key in declaration.keys if isinstance(key, ast.Constant)]
    if len(keys) != len(declaration.keys) or any(count != 1 for count in Counter(keys).values()):
        raise error_class("duplicate or nonliteral service-owned HTTP boundary")
    for route, (handler, service) in SERVICE_OWNED_HTTP_BOUNDARIES.items():
        found = routes.get(route.removeprefix("admin:"), [])
        if len(found) != 1 or handler not in functions or service not in functions:
            raise error_class(f"stale/missing/duplicate service-owned route: {route}")
        path, tree, route_call = found[0]
        module, leaf = handler.rsplit(".", 1)
        exact_import = any(isinstance(node, ast.ImportFrom) and node.module == module
                           and any(item.name == leaf and item.asname is None for item in node.names)
                           for node in tree.body)
        expected_module = {
            "admin:makerspaces_modulepurgereceipt_retry_cleanup": "urls_admin_module_purge_receipts.py",
            "admin:makerspaces_makerspace_purge_confirmed": "urls_admin_purge.py",
            "admin:makerspaces_purgereceipt_retry_cleanup": "urls_admin_purge_receipts.py",
        }.get(route)
        if (path.name != expected_module or not exact_import
                or len(route_call.args) < 2
                or not calls_named(tree, "admin_view")
                or not calls_named(tree, "non_atomic_requests")
                or not calls_named(tree, leaf)):
            raise error_class(f"service-owned route lost its protected handler: {route}")
        owner = functions[handler]
        if (not any(getattr(item, "id", None) == "require_POST" for item in owner.decorator_list)
                or not calls_named(owner, service.rsplit(".", 1)[-1])
                or not calls_named(functions[service], "purge_boundary")):
            raise error_class(f"service-owned route lost its exclusive service: {route}")
