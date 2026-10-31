"""Syntactic candidates: classification is deliberately separate from approval."""

import ast

from .source_primitive_python_resolve import UNKNOWN, digest


SQL_CALLS = {"execute", "executemany", "executescript", "callproc", "raw", "extra", "RunSQL"}
SEMANTIC_CALLS = {"save", "update", "bulk_update", "bulk_create", "update_or_create"}
OBJECT_CALLS = {
    "put_object", "get_object", "delete_object", "delete_objects", "copy_object",
    "upload_file", "upload_fileobj", "download_file", "download_fileobj",
    "list_objects", "list_objects_v2", "head_object", "generate_presigned_url",
    "generate_presigned_post", "create_multipart_upload", "complete_multipart_upload",
    "abort_multipart_upload", "upload_part", "list_object_versions", "Bucket", "Object",
}
STORE_WORDS = {"storage", "s3", "bucket", "boto3", "boto", "minio", "object_store"}
NAMESPACES = ("evidence/", "backups/", "backup/", "tenant-migration/", "tenant_migration/",
              "manifests/", "staging/", "exports/", "private/")
META_FIELDS = {"meta", "metadata", "manifest", "authority_metadata"}


def spelling(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return spelling(node.value) + "." + node.attr
    if isinstance(node, ast.Call):
        return spelling(node.func) + "()"
    return ""


def words(value):
    return set(value.lower().replace("()", "").replace("_", ".").split("."))


def call_categories(node, resolved):
    lexical = spelling(node.func)
    leaf = resolved.split(".")[-1]
    leaves = set(leaf.split("|")) | {lexical.split(".")[-1]}
    categories = []
    if leaves & SQL_CALLS:
        categories.append("raw_sql")
    if leaves & SEMANTIC_CALLS:
        categories.append("mixed_semantic")
    if any(name.startswith("django.db.models.") and name.split(".")[-1] in {
            "ForeignKey", "OneToOneField", "ManyToManyField"}
           for name in resolved.split("|")):
        categories.append("model_declaration")
    if set(resolved.split("|")) & {
            "django.urls.path", "django.urls.re_path", "django.urls.include"}:
        categories.append("route_declaration")
    target_words = words(resolved + "." + lexical)
    if leaves & OBJECT_CALLS or (target_words & STORE_WORDS and leaves & {
        "save", "open", "delete", "exists", "url", "listdir", "size", "copy", "remove",
        "get", "put", "stat", "fput_object", "fget_object", "remove_object", "list_objects",
    }):
        categories.append("object_storage")
    if ("os.getenv" in resolved or "os.environ" in resolved or "django.conf.settings" in resolved
            or resolved.startswith(("environ.", "environs.", "decouple.config", "dotenv."))
            or lexical.startswith("settings.")):
        categories.append("settings_environment")
    if leaves & {"eval", "exec", "__import__", "import_module"}:
        categories.append("mixed_semantic")
    elif leaves & {"getattr", "setattr"}:
        if any(privileged_expression(arg) for arg in node.args):
            categories.append("mixed_semantic")
    return categories


def privileged_expression(node):
    for child in ast.walk(node):
        if isinstance(child, (ast.Name, ast.Attribute)):
            value = spelling(child).lower()
            if words(value) & (STORE_WORDS | {"settings", "cursor", "connection", "meta", "metadata"}):
                return True
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value in SQL_CALLS | OBJECT_CALLS | META_FIELDS | {"django.conf", "django.db", "boto3", "os"}:
                return True
    return False


def namespace_expression(node):
    if not isinstance(node, (ast.JoinedStr, ast.BinOp, ast.Call, ast.Constant)):
        return False
    return any(isinstance(child, ast.Constant) and isinstance(child.value, str)
               and any(word in child.value.lower() for word in NAMESPACES)
               for child in ast.walk(node))


def semantic_target(node):
    return any((isinstance(child, ast.Attribute) and child.attr in META_FIELDS)
               or (isinstance(child, ast.Name) and child.id in META_FIELDS)
               for child in ast.walk(node))


def candidate(node, owner, category, unresolved=()):
    return {"owner": owner, "line": getattr(node, "lineno", 1),
            "column": getattr(node, "col_offset", 0), "category": category,
            "shape": digest(node), "unresolved": sorted(set(unresolved))}
