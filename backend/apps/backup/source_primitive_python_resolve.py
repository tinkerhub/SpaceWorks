"""Conservative lexical names for source review, never runtime Python resolution."""

import ast
import hashlib
from pathlib import PurePosixPath


UNKNOWN = "<unresolved>"


def digest(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def module_name(relative):
    parts = list(PurePosixPath(relative).with_suffix("").parts)
    if parts[:1] == ["backend"]:
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def expression_name(node, names, owner=""):
    if isinstance(node, ast.Name):
        return names.get(node.id, UNKNOWN)
    if isinstance(node, ast.Attribute):
        base = expression_name(node.value, names, owner)
        return f"{base}.{node.attr}"
    if isinstance(node, ast.Call):
        # Result provenance is useful for cursor()/client(), but is not proof
        # that an arbitrary returned object has the named runtime type.
        return expression_name(node.func, names, owner) + "()"
    return UNKNOWN


def import_bindings(node, module, relative):
    if isinstance(node, ast.Import):
        return {a.asname or a.name.split(".")[0]: a.name if a.asname else a.name.split(".")[0]
                for a in node.names}
    if not isinstance(node, ast.ImportFrom):
        return {}
    prefix = node.module or ""
    if node.level:
        package = module.split(".")
        if not relative.endswith("/__init__.py"):
            package = package[:-1]
        keep = max(0, len(package) - node.level + 1)
        prefix = ".".join(package[:keep] + ([prefix] if prefix else []))
    return {a.asname or a.name: f"{prefix}.{a.name}".strip(".")
            for a in node.names if a.name != "*"}


def bound_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for child in target.elts for name in bound_names(child)]
    return []


def seed_names(body, module, relative, prefix=""):
    result = {}
    for node in body:
        result.update(import_bindings(node, module, relative))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result[node.name] = ".".join(p for p in (module, prefix, node.name) if p)
    return result


def merge_names(left, right):
    result = {}
    for key in left.keys() | right.keys():
        one, two = left.get(key, UNKNOWN), right.get(key, UNKNOWN)
        if one == two:
            result[key] = one
        else:
            # Preserve candidate callable leaves across ambiguous paths, so a
            # conditional alias cannot erase the primitive's discovery fact.
            leaves = set(one.rsplit(".", 1)[-1].split("|")) | set(two.rsplit(".", 1)[-1].split("|"))
            result[key] = UNKNOWN + "." + "|".join(sorted(leaves))
    return result


def assign_names(node, names):
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    value = getattr(node, "value", None)
    resolved = expression_name(value, names)
    # Literal constants are bound by their digest in the enclosing symbol;
    # constants never become trusted callable names.
    for target in targets:
        for name in bound_names(target):
            names[name] = resolved


def local_bindings(body):
    """Names Python treats as local throughout one function's lexical body."""
    result, external = set(), set()

    class Locals(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                result.add(node.id)

        def visit_Import(self, node):
            result.update(a.asname or a.name.split(".")[0] for a in node.names)

        def visit_ImportFrom(self, node):
            result.update(a.asname or a.name for a in node.names)

        def visit_Global(self, node):
            external.update(node.names)

        visit_Nonlocal = visit_Global

        def visit_FunctionDef(self, node):
            result.add(node.name)

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

        def visit_Lambda(self, node):
            pass

    visitor = Locals()
    for node in body:
        visitor.visit(node)
    return result - external
