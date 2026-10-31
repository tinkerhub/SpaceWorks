"""Pure AST source facts. These facts do not establish runtime authorization."""

import ast
import hashlib
import json

from .source_primitive_python_kinds import (
    OBJECT_CALLS, SQL_CALLS, call_categories, candidate, namespace_expression, semantic_target,
)
from .source_primitive_python_resolve import (
    UNKNOWN, assign_names, bound_names, digest, expression_name, import_bindings,
    local_bindings, merge_names, module_name, seed_names,
)


class _Scanner(ast.NodeVisitor):
    def __init__(self, tree, relative):
        self.module = module_name(relative)
        self.relative = relative
        self.owner = "<module>"
        self.names = seed_names(tree.body, self.module, relative)
        self.sites = []
        self.calls = []
        self.symbols = {}
        self.class_owners = set()
        self.dependencies = set()
        # Bind imported names, constants, and aliases even when the primitive's
        # own AST is unchanged. Values leave this module only as a digest.
        context = [digest(n) for n in tree.body if isinstance(
            n, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.AugAssign))]
        self.context = hashlib.sha256(json.dumps(context).encode()).hexdigest()
        self.symbols[self.module + ".<module>"] = digest(tree)

    def add(self, node, category, unresolved=()):
        self.sites.append(candidate(node, self.owner, category, unresolved))

    def visit(self, node):
        if namespace_expression(node):
            self.add(node, "generated_path")
        return super().visit(node)

    def visit_Import(self, node):
        self._import(node)

    def visit_ImportFrom(self, node):
        self._import(node)
        if any(alias.name == "*" for alias in node.names):
            self.add(node, "mixed_semantic", ["wildcard-import-bindings"])

    def _import(self, node):
        bindings = import_bindings(node, self.module, self.relative)
        self.names.update(bindings)
        self.dependencies.update(bindings.values())

    def visit_Call(self, node):
        target = expression_name(node.func, self.names)
        self.calls.append({"owner": self.owner, "target": target,
                           "line": node.lineno, "column": node.col_offset})
        unresolved = ["callee-or-receiver-unresolved"] if UNKNOWN in target else []
        if isinstance(node.func, (ast.Call, ast.Subscript, ast.Lambda)):
            unresolved.append("dynamic-callee")
        leaf = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if leaf in {"eval", "exec", "__import__", "import_module", "getattr", "setattr"}:
            unresolved.append("dynamic-reflection")
        if leaf in {"getattr", "setattr"} and any(
                "django.conf.settings" in expression_name(arg, self.names)
                or "os.environ" in expression_name(arg, self.names)
                or ".cursor" in expression_name(arg, self.names)
                or ".storage" in expression_name(arg, self.names) for arg in node.args):
            self.add(node, "mixed_semantic", unresolved)
        for category in call_categories(node, target):
            self.add(node, category, unresolved)
        for arg in node.args + [kw.value for kw in node.keywords]:
            self._escape(arg)
        self.generic_visit(node)

    def _escape(self, node):
        pending = [node]
        while pending:
            child = pending.pop()
            if isinstance(child, ast.Call):
                pending.extend(child.args + [kw.value for kw in child.keywords])
                continue
            pending.extend(ast.iter_child_nodes(child))
            if not isinstance(child, (ast.Name, ast.Attribute)):
                continue
            target = expression_name(child, self.names)
            if set(target.split(".")[-1].split("|")) & (SQL_CALLS | OBJECT_CALLS):
                self.add(child, "mixed_semantic", ["privileged-callable-escape"])

    def visit_Return(self, node):
        if node.value:
            self._escape(node.value)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        target = expression_name(node, self.names)
        if "django.conf.settings" in target or "os.environ" in target:
            self.add(node, "settings_environment")
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and self.names.get(node.id) in {"os.environ", "django.conf.settings"}:
            self.add(node, "settings_environment")

    def visit_Assign(self, node):
        self._assignment(node)

    def visit_AnnAssign(self, node):
        self._assignment(node)

    def visit_AugAssign(self, node):
        self._assignment(node)
        for name in bound_names(node.target):
            self.names[name] = UNKNOWN

    def visit_NamedExpr(self, node):
        self._assignment(node)

    def _assignment(self, node):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(semantic_target(target) for target in targets):
            self.add(node, "mixed_semantic", ["semantic-write-runtime-receiver"])
        value = getattr(node, "value", None)
        if value is not None and (any(isinstance(t, (ast.Attribute, ast.Subscript)) for t in targets)
                                  or isinstance(value, (ast.List, ast.Tuple, ast.Set, ast.Dict))):
            self._escape(value)
        self.generic_visit(node)
        assign_names(node, self.names)

    def visit_Delete(self, node):
        for target in node.targets:
            for name in bound_names(target):
                self.names[name] = UNKNOWN
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._definition(node)

    def visit_AsyncFunctionDef(self, node):
        self._definition(node)

    def visit_ClassDef(self, node):
        self._definition(node)

    def _definition(self, node):
        previous_owner, previous_names = self.owner, self.names
        owner = node.name if previous_owner == "<module>" else previous_owner + "." + node.name
        self.symbols[self.module + "." + owner] = hashlib.sha256(
            (digest(node) + self.context).encode()).hexdigest()
        for deco in node.decorator_list:
            self.visit(deco)
        if isinstance(node, ast.ClassDef):
            self.class_owners.add(owner)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
        else:
            for default in node.args.defaults + [n for n in node.args.kw_defaults if n is not None]:
                self.visit(default)
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                if arg.annotation:
                    self.visit(arg.annotation)
            if node.returns:
                self.visit(node.returns)
        self.owner = owner
        self.names = dict(previous_names)
        if not isinstance(node, ast.ClassDef):
            for name in local_bindings(node.body):
                self.names[name] = UNKNOWN
            args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            for arg in args:
                self.names[arg.arg] = "<parameter:" + arg.arg + ">"
            if previous_owner in self.class_owners:
                for arg in node.args.posonlyargs + node.args.args:
                    if arg.arg in {"self", "cls"}:
                        self.names[arg.arg] = self.module + "." + previous_owner
        self.names.update(seed_names(node.body, self.module, self.relative, owner))
        for statement in node.body:
            self.visit(statement)
        self.owner, self.names = previous_owner, previous_names

    def visit_Lambda(self, node):
        previous = self.names
        self.names = dict(previous)
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            self.names[arg.arg] = UNKNOWN
        self.visit(node.body)
        self.names = previous

    def _branches(self, branches):
        original = dict(self.names)
        results = []
        for body in branches:
            self.names = dict(original)
            for statement in body:
                self.visit(statement)
            results.append(self.names)
        self.names = original
        for result in results:
            self.names = merge_names(self.names, result)

    def visit_If(self, node):
        self.visit(node.test)
        self._branches([node.body, node.orelse])

    def visit_For(self, node):
        self.visit(node.iter)
        for name in bound_names(node.target):
            self.names[name] = UNKNOWN
        self._branches([node.body, node.orelse])

    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self.visit(node.test)
        self._branches([node.body, node.orelse])

    def visit_Try(self, node):
        # Handler and no-handler paths are both possibilities. Even bindings
        # common to several branches remain opaque unless all paths agree.
        self._branches([node.body + node.orelse] + [handler.body for handler in node.handlers])
        for handler in node.handlers:
            if handler.type:
                self.visit(handler.type)
            if handler.name:
                self.names[handler.name] = UNKNOWN
        for statement in node.finalbody:
            self.visit(statement)

    visit_TryStar = visit_Try

    def visit_With(self, node):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                resolved = expression_name(item.context_expr, self.names)
                for name in bound_names(item.optional_vars):
                    self.names[name] = resolved
        for statement in node.body:
            self.visit(statement)

    visit_AsyncWith = visit_With

    def visit_Match(self, node):
        self.visit(node.subject)
        for case in node.cases:
            for child in ast.walk(case.pattern):
                name = getattr(child, "name", None)
                if name:
                    self.names[name] = UNKNOWN
            if case.guard:
                self.visit(case.guard)
        self._branches([case.body for case in node.cases])


def scan_python(text: str, relative: str) -> dict:
    """Return deterministic source facts, raising SyntaxError on invalid syntax.

    Qualified call names are lexical candidates; unresolved receiver/alias facts
    require explicit whole-context review. No source code is executed/imported.
    """
    tree = ast.parse(text, filename=relative)
    scanner = _Scanner(tree, relative)
    scanner.visit(tree)
    sites = {json.dumps(site, sort_keys=True): site for site in scanner.sites}
    return {"sites": sorted(sites.values(), key=lambda s: (
                s["line"], s["column"], s["category"], s["owner"], s["shape"])),
            "calls": sorted(scanner.calls, key=lambda c: (c["line"], c["column"], c["target"])),
            "symbols": dict(sorted(scanner.symbols.items())),
            "dependencies": sorted(scanner.dependencies)}
