"""Foreign-source adapter; stdlib only, with an argv-based TypeScript worker.

All returned source content is represented by hashes. No source file is executed;
only the repository's locked TypeScript parser tooling is imported by Node.
"""
import json
import importlib
import re
import shlex
import subprocess
import sys
import types
from pathlib import Path

# The backend loads this file directly without importing an application package.
# Give the helpers a private namespace package, without modifying sys.path or
# relying on the caller's working directory/import setup.
_PACKAGE = "_spaceworks_source_audit_helpers"
if _PACKAGE not in sys.modules:
    _package = types.ModuleType(_PACKAGE)
    _package.__path__ = [str(Path(__file__).parent)]
    sys.modules[_PACKAGE] = _package
_embedded = importlib.import_module(_PACKAGE + ".embedded_scan")
digest, scan_embedded = _embedded.digest, _embedded.scan_embedded
scan_shell = importlib.import_module(_PACKAGE + ".shell_scan").scan_shell


def _empty(text, owner="<module>"):
    return {"sites": [], "calls": [], "symbols": {owner: digest(text)}, "dependencies": []}


def _fact(result, owner, line, text, reason):
    result["sites"].append({"owner": owner, "line": line, "column": 0,
        "category": "unresolved_dynamic", "shape": digest(text), "unresolved": [reason]})


def _merge(result, data):
    for key in ("sites", "calls", "dependencies"):
        result[key].extend(data[key])
    result["symbols"].update(data["symbols"])


def _javascript(text, relative, node_command, root):
    if not node_command or not all(isinstance(value, str) and value for value in node_command):
        raise ValueError("source audit requires a nonempty Node command argument vector")
    helper = Path(__file__).with_name("parse_typescript.mjs")
    parser_root = root.resolve()
    if not (parser_root / "frontend/node_modules/typescript/lib/typescript.js").is_file():
        parser_root = Path(__file__).resolve().parents[2]
    request = json.dumps({"text": text, "path": relative, "root": str(parser_root)})
    try:
        completed = subprocess.run([*node_command, str(helper)], input=request,
            text=True, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"TypeScript parser unavailable for {relative}") from error
    try:
        parsed = json.loads(completed.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError(f"invalid TypeScript parser response for {relative}") from error
    if completed.returncode or parsed.get("error"):
        # Diagnostics contain only numeric codes/offsets; never surface parser
        # stderr, which may quote source constants in an exception message.
        raise ValueError(f"TypeScript syntax/parser failure for {relative}")
    if not all(isinstance(parsed.get(key), kind) for key, kind in (
            ("sites", list), ("calls", list), ("symbols", dict), ("dependencies", list))):
        raise ValueError(f"invalid TypeScript parser metadata for {relative}")
    parsed["dependencies"].append("frontend/package-lock.json")
    parsed["symbols"]["<parser>"] = digest(parsed.pop("parser"))
    return parsed


def _container(text, relative, embedded):
    result = _empty(text)
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        first = index + 1
        instruction = lines[index]
        index += 1
        while instruction.rstrip().endswith("\\") and index < len(lines):
            instruction = instruction.rstrip()[:-1] + lines[index]
            index += 1
        match = re.match(r"\s*(RUN|CMD|ENTRYPOINT|SHELL|ENV|ARG|COPY|ADD)\s+(.*)",
            instruction, re.I | re.S)
        if not match:
            continue
        kind, body = match.group(1).upper(), match.group(2)
        owner = f"<docker:{kind}@{first}>"
        if kind in {"ENV", "ARG"}:
            result["sites"].append({"owner": owner, "line": first, "column": 0,
                "category": "settings_environment", "shape": digest(body), "unresolved": []})
            continue
        if kind in {"COPY", "ADD"}:
            _fact(result, owner, first, body, "container_source_input_binding")
            continue
        if body.lstrip().startswith("["):
            try:
                argv = json.loads(body)
                if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
                    raise ValueError("non-string argv")
                body = shlex.join(argv)
            except ValueError:
                _fact(result, owner, first, body, "unsupported_container_exec_array")
                continue
        # Docker heredocs are instruction bodies and must be consumed with the
        # RUN unit, not misclassified as separate Docker instructions.
        markers = re.findall(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z_0-9]*)", body)
        for marker in markers:
            while index < len(lines):
                current = lines[index]
                body += current
                index += 1
                if current.strip() == marker:
                    break
        _merge(result, scan_shell(body, owner, first, embedded))
    _fact(result, "<module>", 1, text, "container_whole_context_review_required")
    return result


def _yaml(text, embedded):
    result = _empty(text)
    lines = text.splitlines(keepends=True)
    index = 0
    pattern = r"^(\s*)(?:-\s*)?(run|command|entrypoint|script|args)\s*:\s*(.*)$"
    while index < len(lines):
        first, line = index + 1, lines[index]
        index += 1
        match = re.match(pattern, line.rstrip("\r\n"), re.I)
        if not match:
            continue
        indent, key, body = len(match.group(1)), match.group(2), match.group(3)
        owner = f"<yaml:{key}@{first}>"
        if body.startswith(("|", ">")) or not body:
            content = []
            while index < len(lines):
                current = lines[index]
                current_indent = len(current) - len(current.lstrip())
                if current.strip() and current_indent <= indent:
                    break
                content.append(current)
                index += 1
            nonempty = [len(value) - len(value.lstrip()) for value in content if value.strip()]
            strip = min(nonempty, default=0)
            # Folded scalars have different semantics; enumerate the literal
            # commands and require explicit whole-context review of folding.
            if body.startswith(">"):
                _fact(result, owner, first, "".join(content), "yaml_folded_command")
            body = "".join(value[strip:] for value in content)
            start = first + 1
        else:
            start = first
            if body.startswith("["):
                try:
                    argv = json.loads(body)
                    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
                        raise ValueError("non-string argv")
                    body = shlex.join(argv)
                except ValueError:
                    _fact(result, owner, first, body, "yaml_nonliteral_command_array")
            elif body.startswith(("'", '"')):
                try:
                    body = shlex.split(body)[0]
                except (ValueError, IndexError):
                    _fact(result, owner, first, body, "yaml_quoted_command_grammar")
        if "${{" in body or re.search(r"(?:^|\s)[*&!][A-Za-z_]", body):
            _fact(result, owner, first, body, "yaml_dynamic_command_or_tag")
        _merge(result, scan_shell(body, owner, start, embedded))
    # A stdlib line recognizer cannot prove arbitrary YAML alias/merge/tag
    # semantics. Preserve an explicit file-wide review obligation even if no
    # familiar executable key was recognized.
    _fact(result, "<module>", 1, text, "yaml_whole_context_review_required")
    return result


def scan_foreign(path: Path, relative: str, text: str,
                 node_command: tuple[str, ...], root: Path) -> dict:
    """Return deterministic candidates/call vectors for non-Python source.

    Unsupported syntax is a named fact requiring direct review; invalid TS/JS
    syntax is a fatal parser error, never parser recovery accepted as coverage.
    """
    def embedded(body, owner, first):
        data = _javascript(body, relative + ".embedded.js", node_command, root)
        data["symbols"] = {owner + "." + name: value for name, value in data["symbols"].items()}
        for key in ("sites", "calls"):
            for entry in data[key]:
                entry["owner"] = owner + "." + entry["owner"]
                entry["line"] += first - 1
        return data

    suffix = path.suffix.lower()
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}:
        result = _javascript(text, relative, node_command, root)
    elif suffix in {".sh", ".bash", ".zsh"}:
        result = scan_shell(text, embedded=embedded)
    elif suffix == ".sql":
        result = scan_embedded("sql", text, "<sql>")
    elif suffix in {".yml", ".yaml"}:
        result = _yaml(text, embedded)
    elif path.name.lower().startswith("dockerfile") or suffix == ".dockerfile":
        result = _container(text, relative, embedded)
    else:
        result = _empty(text)
        _fact(result, "<module>", 1, text, "unsupported_source_language")
    result["dependencies"] = sorted(set(result["dependencies"]))
    result["sites"].sort(key=lambda item: (item["line"], item["column"], item["category"], item["shape"]))
    result["calls"].sort(key=lambda item: (item["line"], item["column"], item["target"]))
    return result
