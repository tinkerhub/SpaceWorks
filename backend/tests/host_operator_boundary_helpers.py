"""Source-only regression surface, not a reflection/RCE proof or root authority.

Computed dynamic imports are not generally decidable. Runtime host ownership and
socket permissions remain the authority; nothing here imports production code.
"""

import ast
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
import stat
from types import MappingProxyType

OPERATOR_PATHS = frozenset(
    f"backend/apps/backup/host_restore_{name}.py"
    for name in ("transport", "configuration", "admission", "files", "prepare", "lifecycle", "resume")
)
DOCKER_EXEMPTIONS = frozenset(
    f"backend/apps/backup/host_restore_{name}.py" for name in ("transport", "configuration")
)
CONTROLLER = "scripts/restore-host.py"
REVIEWED_PATHS = OPERATOR_PATHS | {CONTROLLER, "backend/apps/__init__.py", "backend/apps/backup/__init__.py"} | {
    f"backend/apps/backup/{name}.py" for name in (
        "full_format", "host_capability_journal", "host_capability_types", "host_marker",
        "host_marker_file", "host_pointer", "host_private_file", "host_run_ledger", "host_supervisor",
        "host_topology_record", "inplace_marker", "inplace_recovery_facts", "operation_lock",
        "restore_manifest_facts", "topology",
    )
}
SOURCE_ROOTS = ("backend/apps", "backend/config", "backend/scripts", "scripts")
GUARD_START = 'python3 -I -B - "$ROOT" <<\'PY_GUARD\'\n'
ROOT_TEST = 'sys.platform != "linux" or os.geteuid() != 0'


@dataclass(frozen=True)
class SourceFile:
    """Copied bytes and filesystem facts; replace entries in a copied map for Stage3."""

    data: bytes
    canonical: bool
    regular: bool
    nlink: int


def read_sources(root):
    """Read only the four source roots and wrapper; return an immutable snapshot."""
    paths = {path for name in SOURCE_ROOTS for path in (root / name).rglob("*.py")}
    paths.add(root / "scripts/restore.sh")
    result = {}
    for path in sorted(paths):
        info = path.lstat()
        parents = (root, *(parent for parent in path.parents if parent.is_relative_to(root)))
        canonical = (path.resolve() == path.absolute()
                     and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in parents))
        regular = stat.S_ISREG(info.st_mode)
        assert canonical and regular and info.st_nlink == 1, f"Unsafe source path: {path}"
        result[path.relative_to(root).as_posix()] = SourceFile(path.read_bytes(), canonical, regular, info.st_nlink)
    return MappingProxyType(result)


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _literal(tree, name):
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == name]
    stores = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
              and isinstance(node.ctx, ast.Store) and node.id == name]
    assert len(assignments) == len(stores) == 1, f"Ambiguous {name}"
    return assignments[0].value


def _wrapper_boundary(source):
    assert source.count(GUARD_START) == 1 and source.splitlines().count("PY_GUARD") == 1
    prefix, rest = source.split(GUARD_START)
    guard, suffix = rest.split("\nPY_GUARD\n")
    lines = lambda text: [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert lines(prefix) == [
        "set -euo pipefail", "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"',
    ], "Guard must run unconditionally before controller launch"
    launches = lines(suffix)
    assert launches[0] == 'case "${1:-}" in' and launches[-1] == "esac" and len(launches) == 6
    for line, (option, mode) in zip(launches[1:-1], (
        ("--import", "import"), ("--resume-host", "resume-host"),
        ("--recover-superadmin", "recover-superadmin"), ("*", "restore"),
    )):
        start = f'{option}) ' + ('shift; ' if option != '*' else '')
        assert line == start + f'exec python3 -I -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" {mode} "$@" ;;'
    tree = ast.parse(guard)
    expected = _literal(tree, "EXPECTED")
    assert isinstance(expected, ast.Dict) and len(expected.keys) == 25
    declared = ast.literal_eval(expected)
    assert set(declared) == REVIEWED_PATHS and len(declared) == 25
    assert all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in declared.values())
    # Match executable AST structure, including the actual safety expressions and
    # their loops. Constants elsewhere cannot satisfy these checks.
    imports = ast.parse("import hashlib\nimport os\nfrom pathlib import Path\nimport stat\nimport sys").body
    assert len(tree.body) == 8 and list(map(_dump, tree.body[:5])) == list(map(_dump, imports))
    assert tree.body[5].value is expected
    assert _dump(tree.body[6]) == _dump(ast.parse("root = Path(sys.argv[1])").body[0])
    guarded = tree.body[7]
    safety = ast.parse('''
if sys.platform != "linux" or os.geteuid() != 0:
    raise ValueError
directories = {root, *root.parents}
for relative in (*EXPECTED, "scripts/restore.sh"):
    directories.update((root / relative).parents)
for directory in directories:
    info = directory.lstat()
    temporary_ancestor = (directory == Path("/tmp") and directory in root.parents
                          and stat.S_IMODE(info.st_mode) == 0o1777)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or (info.st_mode & 0o022 and not temporary_ancestor)):
        raise ValueError
for relative in (*EXPECTED, "scripts/restore.sh"):
    info = (root / relative).lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_nlink != 1 or info.st_mode & 0o022):
        raise ValueError
for relative, expected in EXPECTED.items():
    if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
        raise ValueError
''').body
    assert isinstance(guarded, ast.Try) and not guarded.orelse and not guarded.finalbody
    assert list(map(_dump, guarded.body)) == list(map(_dump, safety)), "Host safety guard changed"
    assert len(guarded.handlers) == 1
    handler = guarded.handlers[0]
    assert _dump(handler.type) == _dump(ast.parse("(OSError, ValueError)", mode="eval").body)
    assert handler.name is None and len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise)
    failure = handler.body[0].exc
    assert isinstance(failure, ast.Call) and isinstance(failure.func, ast.Name) and failure.func.id == "SystemExit"
    assert len(failure.args) == 1 and isinstance(failure.args[0], ast.Constant) and not failure.keywords
    assert isinstance(failure.args[0].value, str) and _dump(handler.body[0].cause) == _dump(ast.Constant(None))
    return declared


def _imports(path, tree, sources):
    """Resolve local modules, package members/inits and literal dynamic targets."""
    package = path.removeprefix("backend/").split("/")[:-1]
    edges = set()

    def resolve(name):
        parts = name.split(".")
        stems = ["/".join(parts[:length]) for length in range(1, len(parts) + 1)]
        candidates = [f"{prefix}{stem}{ending}" for stem in stems
                      for prefix in ("backend/", "")
                      for ending in (".py", "/__init__.py")]
        for candidate in candidates:
            if candidate in sources:
                edges.add(candidate)
                edges.update(f"{parent}/__init__.py" for parent in PurePosixPath(candidate).parents
                             if f"{parent}/__init__.py" in sources)

    aliases = {"importlib"}
    functions = {"import_module"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "importlib")
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            functions.update(alias.asname or alias.name for alias in node.names if alias.name == "import_module")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolve(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = ".".join(package[:len(package) - node.level + 1]) if node.level else ""
            base = ".".join(filter(None, (base, node.module)))
            resolve(base)
            for alias in node.names:
                resolve(f"{base}.{alias.name}")
        elif isinstance(node, ast.Call):
            function = node.func
            builtin = isinstance(function, ast.Name) and function.id == "__import__"
            dynamic = (isinstance(function, ast.Name) and function.id in functions
                       or isinstance(function, ast.Attribute) and function.attr == "import_module"
                       and isinstance(function.value, ast.Name) and function.value.id in aliases)
            if not (builtin or dynamic):
                continue
            arguments = {keyword.arg: keyword.value for keyword in node.keywords}
            target = node.args[0] if node.args else arguments.get("name")
            if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
                continue
            name = target.value
            if name.startswith("."):
                anchor = node.args[1] if len(node.args) > 1 else arguments.get("package")
                if not isinstance(anchor, ast.Constant) or not isinstance(anchor.value, str):
                    continue
                level = len(name) - len(name.lstrip("."))
                name = ".".join(anchor.value.split(".")[:len(anchor.value.split(".")) - level + 1] + [name.lstrip(".")])
            if builtin:
                level = node.args[4] if len(node.args) > 4 else arguments.get("level")
                if isinstance(level, ast.Constant) and isinstance(level.value, int) and level.value:
                    name = ".".join(package[:len(package) - level.value + 1] + [name])
                members = node.args[3] if len(node.args) > 3 else arguments.get("fromlist")
                if isinstance(members, (ast.Tuple, ast.List)):
                    for member in members.elts:
                        if isinstance(member, ast.Constant) and isinstance(member.value, str):
                            resolve(f"{name}.{member.value}")
            resolve(name)
    return edges


def validated_docker_exemptions(sources):
    """Pure validation of copied source data; return exactly two paths on success.

    Stage3 can use dict(snapshot) and dataclasses.replace(record, data=...) to
    inject source mutations without importing host code or constructing a world.
    """
    for path, record in sources.items():
        assert str(PurePosixPath(path)) == path and not PurePosixPath(path).is_absolute() and ".." not in path.split("/")
        assert record.canonical and record.regular and record.nlink == 1, f"Unsafe source: {path}"
    text = lambda path: sources[path].data.decode("utf-8-sig")
    declared = _wrapper_boundary(text("scripts/restore.sh"))
    trees = {path: ast.parse(text(path), filename=path) for path in sources if path.endswith(".py")}
    reviewed = ast.literal_eval(_literal(trees["scripts/check-restore-host-bundle.py"], "REVIEWED_PATHS"))
    assert len(reviewed) == 25 and set(reviewed) == REVIEWED_PATHS
    assert OPERATOR_PATHS <= declared.keys()
    for path, digest in declared.items():
        assert hashlib.sha256(sources[path].data).hexdigest() == digest, f"Closure SHA differs: {path}"
    for path in ("backend/apps/__init__.py", "backend/apps/backup/__init__.py"):
        assert all(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                   and isinstance(node.value.value, str) for node in trees[path].body), f"Non-inert initializer: {path}"
    graph = {path: _imports(path, tree, sources) for path, tree in trees.items()}
    for path, edges in graph.items():
        assert path in OPERATOR_PATHS | {CONTROLLER} or not edges & OPERATOR_PATHS, f"Incoming operator import: {path}"
    closure, pending = set(), {CONTROLLER}
    while pending:
        path = pending.pop()
        closure.add(path)
        pending.update(graph[path] - closure)
    assert closure == REVIEWED_PATHS, f"Controller closure differs: {closure ^ REVIEWED_PATHS}"
    main = next(node for node in trees[CONTROLLER].body if isinstance(node, ast.FunctionDef) and node.name == "main")
    checks = [node for node in main.body if isinstance(node, ast.If)
              and _dump(node.test) == _dump(ast.parse(ROOT_TEST, mode="eval").body)]
    assert len(checks) == 1 and len(checks[0].body) == 1 and not checks[0].orelse
    refusal = checks[0].body[0]
    assert isinstance(refusal, ast.Raise) and isinstance(refusal.exc, ast.Call)
    assert isinstance(refusal.exc.func, ast.Name) and refusal.exc.func.id == "RestoreHostError"
    transports = [node for node in ast.walk(trees[CONTROLLER]) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "RestoreTransport"]
    main_nodes = set(ast.walk(main))
    assert transports and all(node in main_nodes and checks[0].end_lineno < node.lineno
                              for node in transports), "Root check must precede transport"
    return DOCKER_EXEMPTIONS


def scan_docker_boundary(sources, docker_call):
    """Use the existing guard's regex on the same snapshot Stage3 can mutate."""
    exemptions = validated_docker_exemptions(sources)
    offenders, scanned = [], 0
    for path, record in sources.items():
        if not path.startswith("backend/apps/") or not path.endswith(".py"):
            continue
        if any(part in {"__pycache__", "migrations"} for part in PurePosixPath(path).parts):
            continue
        scanned += 1
        if path not in exemptions and docker_call.search(record.data.decode("utf-8-sig")):
            offenders.append(path)
    return offenders, scanned
