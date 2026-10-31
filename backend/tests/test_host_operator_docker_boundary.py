"""Statement regression guard, not a formal RCE/reflection proof.

All production sources remain data: no host module, loader or script is executed.
Computed/reflected imports remain outside this static guard's guarantee; host
ownership, isolated launch and socket permissions remain runtime authority.
"""

import ast
from dataclasses import replace
import hashlib
from pathlib import Path
import re

import pytest

from tests.host_operator_boundary_helpers import (
    read_sources, scan_docker_boundary, validated_docker_exemptions,
)

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = "scripts/restore.sh"
CONTROLLER = "scripts/restore-host.py"
TRANSPORT = "backend/apps/backup/host_restore_transport.py"
EXACT_TWO = {TRANSPORT, "backend/apps/backup/host_restore_configuration.py"}
OPERATORS = ("transport", "configuration", "admission", "files", "prepare", "lifecycle", "resume")


@pytest.fixture(scope="module")
def snapshot():
    return read_sources(ROOT)


@pytest.fixture(scope="module")
def docker_call():
    """Consume the existing guard's regex literal rather than invent another scan."""
    tree = ast.parse((ROOT / "backend/tests/test_host_update_boundary.py").read_text(encoding="utf-8-sig"))
    test = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "test_the_web_process_never_shells_out_to_docker")
    call = next(node.value for node in test.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "docker_call" for target in node.targets))
    assert isinstance(call, ast.Call) and ast.unparse(call.func) == "re.compile"
    return re.compile(ast.literal_eval(call.args[0]))


def _text(sources, path):
    return sources[path].data.decode("utf-8-sig")


def _put(sources, path, text):
    sources[path] = replace(sources.get(path, sources[CONTROLLER]), data=text.encode())


def _edit(sources, path, old, new):
    text = _text(sources, path)
    assert text.count(old) == 1, (path, old)
    _put(sources, path, text.replace(old, new, 1))


def _manifest(sources, mutate=None):
    """Read/edit the actual wrapper's literal; never call its private validator."""
    wrapper = _text(sources, WRAPPER)
    guard = wrapper.split('python3 -I -B - "$ROOT" <<\'PY_GUARD\'\n', 1)[1].split("\nPY_GUARD\n", 1)[0]
    node = next(node.value for node in ast.parse(guard).body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "EXPECTED" for target in node.targets))
    declared = ast.literal_eval(node)
    if mutate is not None:
        mutate(declared)
        _edit(sources, WRAPPER, ast.get_source_segment(guard, node), repr(declared))
    return declared


def _rehash(sources, path):
    _manifest(sources, lambda declared: declared.update({path: hashlib.sha256(sources[path].data).hexdigest()}))


def test_current_full_checkout_boundary(snapshot, docker_call):
    assert {"backend/config/settings.py", "backend/scripts/bootstrap_host_orchestration.py",
            CONTROLLER} <= snapshot.keys()
    assert (ROOT / "scripts/update.sh").is_file()
    assert len(_manifest(snapshot)) == 25
    assert validated_docker_exemptions(snapshot) == EXACT_TWO
    offenders, scanned = scan_docker_boundary(snapshot, docker_call)
    assert scanned > 100  # Preserve the original app-walk floor.
    assert offenders == []
    assert {path for path, record in snapshot.items() if path.startswith("backend/apps/")
            and "/migrations/" not in path and docker_call.search(record.data.decode("utf-8-sig"))} == EXACT_TWO


# Seven real modules, with bounded import forms; no Cartesian syntax expansion.
@pytest.mark.parametrize("name,statement", [
    ("transport", "import apps.backup.host_restore_{name} as operator"),
    ("configuration", "from {relative}host_restore_{name} import ConfigurationTransition as operator"),
    ("admission", "from {relative} import host_restore_{name} as operator"),
    ("files", "from apps.backup.host_restore_{name} import seal_file as operator"),
    ("prepare", "__import__('apps.backup.host_restore_{name}')"),
    ("lifecycle", "import importlib as loader\nloader.import_module('apps.backup.host_restore_{name}')"),
    ("resume", "from importlib import import_module as load\nload('.host_restore_{name}', package='apps.backup')"),
    ("transport", "__import__(name='apps.backup', fromlist=('host_restore_{name}',))"),
    ("files", "__import__('host_restore_{name}', globals(), locals(), (), {level})"),
])
@pytest.mark.parametrize("caller,relative,level", [
    ("backend/apps/backup/views_restore.py", ".", 1),
    ("backend/apps/backup/tasks.py", ".", 1),
    ("backend/apps/backup/management/commands/backup_control.py", "...", 3),
])
def test_runtime_callers_cannot_import_operators(snapshot, caller, relative, level, name, statement):
    sources = dict(snapshot)
    _put(sources, caller, _text(sources, caller) + "\n" + statement.format(name=name, relative=relative, level=level) + "\n")
    with pytest.raises(AssertionError, match="^Incoming operator import: " + re.escape(caller) + "$"):
        validated_docker_exemptions(sources)


@pytest.mark.parametrize("name", OPERATORS)
def test_second_root_controller_has_no_import_exception(snapshot, name):
    sources = dict(snapshot)
    caller = "scripts/second-root-controller.py"
    _put(sources, caller, 'import os\nimport sys\nif sys.platform != "linux" or os.geteuid() != 0:\n'
         '    raise SystemExit(1)\n' + f"import apps.backup.host_restore_{name} as operator\n")
    with pytest.raises(AssertionError, match="^Incoming operator import: " + re.escape(caller) + "$"):
        validated_docker_exemptions(sources)


@pytest.mark.parametrize("path", [
    "backend/apps/accounts/admin.py", "backend/apps/backup/tasks.py", "backend/apps/backup/full_format.py",
    *(f"backend/apps/backup/host_restore_{name}.py" for name in OPERATORS if name not in {"transport", "configuration"}),
])
def test_other_apps_including_pinned_host_helpers_still_report_docker(snapshot, docker_call, path):
    sources = dict(snapshot)
    _put(sources, path, _text(sources, path) + "\nimport subprocess\nsubprocess.run(['docker', 'compose', 'up'])\n")
    if path in _manifest(sources):
        _rehash(sources, path)
    offenders, scanned = scan_docker_boundary(sources, docker_call)
    assert offenders == [path]
    assert scanned > 100


@pytest.mark.parametrize("change", ["wrong-digest", "missing-entry", "extra-entry", "wrong-path"])
def test_wrapper_closure_declaration_drift_refuses(snapshot, change):
    sources = dict(snapshot)
    def mutate(declared):
        if change == "wrong-digest":
            declared[TRANSPORT] = "0" * 64
        elif change == "missing-entry":
            declared.pop(TRANSPORT)
        elif change == "extra-entry":
            declared["backend/apps/backup/unreviewed.py"] = "0" * 64
        else:
            declared["backend/apps/backup/unreviewed.py"] = declared.pop(TRANSPORT)
    _manifest(sources, mutate)
    reason = "^Closure SHA differs: " + re.escape(TRANSPORT) + "$" if change == "wrong-digest" else "^$"
    with pytest.raises(AssertionError, match=reason):
        validated_docker_exemptions(sources)


def test_missing_closure_source_refuses(snapshot):
    sources = dict(snapshot)
    del sources[TRANSPORT]
    with pytest.raises(KeyError, match=re.escape(TRANSPORT)):
        validated_docker_exemptions(sources)


@pytest.mark.parametrize("facts", [{"canonical": False}, {"regular": False}, {"nlink": 2}])
def test_linked_nonregular_or_noncanonical_closure_source_refuses(snapshot, facts):
    sources = dict(snapshot)
    sources[TRANSPORT] = replace(sources[TRANSPORT], **facts)
    with pytest.raises(AssertionError, match="^Unsafe source: " + re.escape(TRANSPORT) + "$"):
        validated_docker_exemptions(sources)


def test_noncanonical_closure_key_refuses(snapshot):
    sources = dict(snapshot)
    sources["backend/apps/backup/../backup/host_restore_transport.py"] = sources.pop(TRANSPORT)
    with pytest.raises(AssertionError, match="^$"):
        validated_docker_exemptions(sources)


def test_checker_reviewed_literal_drift_refuses(snapshot):
    sources = dict(snapshot)
    _edit(sources, "scripts/check-restore-host-bundle.py", '"' + TRANSPORT + '"', '"backend/apps/backup/unreviewed.py"')
    with pytest.raises(AssertionError, match="^$"):
        validated_docker_exemptions(sources)


def test_non_inert_initializer_refuses_even_after_rehash(snapshot):
    sources = dict(snapshot)
    path = "backend/apps/backup/__init__.py"
    _put(sources, path, _text(sources, path) + "\nimport os\n")
    _rehash(sources, path)
    with pytest.raises(AssertionError, match="^Non-inert initializer: " + re.escape(path) + "$"):
        validated_docker_exemptions(sources)


def test_unreviewed_transitive_dependency_refuses_even_after_rehash(snapshot):
    sources = dict(snapshot)
    _put(sources, "backend/apps/backup/unreviewed.py", '"""Unreviewed dependency."""\n')
    _put(sources, CONTROLLER, _text(sources, CONTROLLER) + "\nimport apps.backup.unreviewed\n")
    _rehash(sources, CONTROLLER)
    with pytest.raises(AssertionError, match="^Controller closure differs: "):
        validated_docker_exemptions(sources)


@pytest.mark.parametrize("statement", ["from . import unreviewed", "from .unreviewed import dependency"])
def test_absolute_import_shadow_preserves_explicit_relative_rejection(snapshot, statement):
    # Keep only the reviewed bundle and its validators: no incidental live app
    # imports can turn the old resolver's false edge into an earlier failure.
    sources = {path: snapshot[path] for path in (
        *_manifest(snapshot), WRAPPER, "scripts/check-restore-host-bundle.py",
    )}
    _put(sources, "backend/apps/backup/apps.py", "from django.apps import AppConfig\n")
    # Python 3 does not resolve the 'apps' prefix of apps.backup.host_marker
    # relative to the importing backup package. This Django shadow stays outside.
    assert validated_docker_exemptions(sources) == EXACT_TWO

    unreviewed = "backend/apps/backup/unreviewed.py"
    _put(sources, unreviewed, "dependency = None\n")
    importer = "backend/apps/backup/host_marker.py"
    _put(sources, importer, _text(sources, importer) + "\ndef deferred_dependency():\n    " + statement + "\n")
    _rehash(sources, importer)
    # Rehashing clears the digest check, so refusal must identify this actual
    # deferred relative dependency in the controller closure, not the apps.py shadow.
    with pytest.raises(AssertionError, match="^Controller closure differs: " + re.escape(repr({unreviewed})) + "$"):
        validated_docker_exemptions(sources)


@pytest.mark.parametrize("old,new,reason", [
    ('    if sys.platform != "linux" or os.geteuid() != 0:\n        raise ValueError\n', "", "Host safety guard changed"),
    ('sys.platform != "linux" or os.geteuid() != 0', 'sys.platform != "linux"', "Host safety guard changed"),
    ("not stat.S_ISDIR(info.st_mode) or info.st_uid != 0", "not stat.S_ISDIR(info.st_mode)", "Host safety guard changed"),
    ("not stat.S_ISREG(info.st_mode) or info.st_uid != 0", "not stat.S_ISREG(info.st_mode)", "Host safety guard changed"),
    ("info.st_nlink != 1", "info.st_nlink != 2", "Host safety guard changed"),
    ("info.st_mode & 0o022):", "info.st_mode & 0o002):", "Host safety guard changed"),
    ("hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected", "False", "Host safety guard changed"),
    ('python3 -I -B - "$ROOT"', 'python3 -B - "$ROOT"', ""),
    ('python3 -I -B - "$ROOT"', 'python3 -I - "$ROOT"', ""),
    ('exec python3 -I -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" restore',
     'exec python3 -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" restore', ""),
    ('exec python3 -I -B -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" restore',
     'exec python3 -I -X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" restore', ""),
    ('-X pycache_prefix=/dev/null "$ROOT/scripts/restore-host.py" restore', '"$ROOT/scripts/restore-host.py" restore', ""),
])
def test_wrapper_protection_regressions_refuse(snapshot, old, new, reason):
    sources = dict(snapshot)
    _edit(sources, WRAPPER, old, new)
    with pytest.raises(AssertionError, match="^" + reason + "$"):
        validated_docker_exemptions(sources)


def test_wrapper_guard_moved_after_launch_refuses(snapshot):
    sources = dict(snapshot)
    wrapper = _text(sources, WRAPPER)
    start = wrapper.index('python3 -I -B - "$ROOT"')
    end = wrapper.index("\nPY_GUARD\n", start) + len("\nPY_GUARD\n")
    _put(sources, WRAPPER, wrapper[:start] + wrapper[end:] + wrapper[start:end])
    with pytest.raises(AssertionError, match="^Guard must run unconditionally before controller launch$"):
        validated_docker_exemptions(sources)


@pytest.mark.parametrize("change", ["removed", "uid-weakened", "moved"])
def test_controller_root_check_refuses_even_after_rehash(snapshot, change):
    sources = dict(snapshot)
    text = _text(sources, CONTROLLER)
    main = next(node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name == "main")
    check = next(node for node in main.body if isinstance(node, ast.If) and "os.geteuid()" in ast.unparse(node.test))
    block = "".join(text.splitlines(keepends=True)[check.lineno - 1:check.end_lineno])
    _edit(sources, CONTROLLER, block, block.replace(" or os.geteuid() != 0", "") if change == "uid-weakened" else "")
    if change == "moved":
        launch = "    transport = RestoreTransport(ROOT)\n"
        _edit(sources, CONTROLLER, launch, launch + block)
    _rehash(sources, CONTROLLER)
    reason = "Root check must precede transport" if change == "moved" else ""
    with pytest.raises(AssertionError, match="^" + reason + "$"):
        validated_docker_exemptions(sources)
