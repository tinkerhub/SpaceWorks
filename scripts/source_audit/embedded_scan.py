"""Pure syntax inspection for interpreter-declared embedded payloads.

Unknown languages are review facts, never exclusions. This scanner intentionally
does not import application modules or evaluate expressions.
"""
import ast
import hashlib
import re


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scan_embedded(language, text, owner, first_line=1):
    result = {"sites": [], "calls": [], "symbols": {owner: digest(text)}, "dependencies": []}

    def emit(node, category, unresolved=()):
        result["sites"].append({"owner": owner,
            "line": first_line + getattr(node, "lineno", 1) - 1,
            "column": getattr(node, "col_offset", 0), "category": category,
            "shape": digest(ast.dump(node, include_attributes=True)) if node else digest(text),
            "unresolved": list(unresolved)})

    if language == "sql":
        emit(None, "raw_sql")
        return result
    if language != "python":
        emit(None, "unresolved_dynamic", ("unsupported_embedded_language",))
        return result
    try:
        tree = ast.parse(text)
    except SyntaxError:
        emit(None, "unresolved_dynamic", ("embedded_python_syntax_error",))
        return result
    aliases = {}

    def name(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return name(node.value) + "." + node.attr
        return "<dynamic>"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            for alias in node.names:
                target = (module + "." if module else "") + alias.name
                aliases[alias.asname or alias.name] = target
                result["dependencies"].append(target)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases[target.id] = name(node.value)
                if isinstance(target, ast.Attribute) and target.attr in {"meta", "metadata"}:
                    emit(node, "mixed_semantic")
        if isinstance(node, ast.Call):
            target = name(node.func)
            result["calls"].append({"owner": owner, "target": target,
                "line": first_line + node.lineno - 1, "column": node.col_offset})
            leaf = target.rsplit(".", 1)[-1]
            if leaf in {"execute", "executemany", "executescript", "raw", "RunSQL"}:
                emit(node, "raw_sql")
            if leaf in {"put_object", "copy_object", "delete_object", "upload_file", "download_file"}:
                emit(node, "object_storage")
            if leaf in {"save", "update", "bulk_update", "bulk_create"}:
                emit(node, "mixed_semantic")
            if "<" in target or leaf in {"eval", "exec", "getattr", "setattr", "__import__"}:
                emit(node, "unresolved_dynamic", ("opaque_embedded_python_call",))
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            target = name(node.value)
            if re.search(r"(?:^|\.)(?:settings|environ)(?:\.|$)", target):
                emit(node, "settings_environment")
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            if re.search(r"(?:evidence|backup|tenant|private|uploads)/", ast.dump(node)):
                emit(node, "generated_path")
    # Embedded Python's scope and alias analysis is deliberately not inherited as
    # authority: the exact complete payload requires an explicit direct review.
    emit(None, "unresolved_dynamic", ("embedded_python_whole_context",))
    result["dependencies"] = sorted(set(result["dependencies"]))
    return result
