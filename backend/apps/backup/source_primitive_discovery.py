"""Independent static census and conservative context/caller bindings."""

from collections import defaultdict
import importlib.util
from pathlib import Path
import sys

from .source_primitive_derived import validated_derived
from .source_primitive_fingerprint import (
    FINGERPRINT_VERSION, FORMAT_VERSION, PARSER_VERSION, PrimitiveSite,
    SourcePrimitiveCoverageError, digest,
)
from .source_primitive_python import scan_python
from .source_primitive_scope import collect_scope


def _foreign_scanner():
    # Only load the stdlib static helper, never an application's package init.
    helper = Path(__file__).resolve().parents[3] / "scripts/source_audit/foreign_scan.py"
    if not helper.is_file():
        helper = Path(__file__).resolve().parents[4] / "scripts/source_audit/foreign_scan.py"
    spec = importlib.util.spec_from_file_location("source_audit_foreign", helper)
    if spec is None or spec.loader is None:
        raise SourcePrimitiveCoverageError("missing foreign static parser")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.scan_foreign


def collect_source_primitives(root, *, node_command=("node",), derived=()):
    root = Path(root).resolve()
    if not isinstance(node_command, (tuple, list)) or not node_command:
        raise SourcePrimitiveCoverageError("node_command must be an argument vector")
    if any(not isinstance(arg, str) or not arg for arg in node_command):
        raise SourcePrimitiveCoverageError("invalid Node argument vector")
    inventory, sources = collect_scope(root)
    excluded = validated_derived(root, derived)
    observations, calls, symbols = [], [], {
        "<parser-runtime>": {"python_ast": list(sys.version_info[:2])},
    }
    foreign = None
    for path, (language, text) in sorted(sources.items()):
        if path in excluded:
            continue
        try:
            if language == "python":
                result = scan_python(text, path)
            elif language in {"shell", "typescript", "container", "sql"}:
                if foreign is None:
                    foreign = _foreign_scanner()
                result = foreign(root / path, path, text, tuple(node_command), root)
            else:
                result = {"sites": [{
                    "owner": "<unit>", "line": 1, "column": 0,
                    "category": "unresolved_dynamic", "shape": digest(text),
                    "unresolved": ["whole-source-input-or-unsupported-grammar"],
                }], "calls": [], "symbols": {}, "dependencies": []}
        except (SyntaxError, UnicodeError, OSError, ValueError, RuntimeError) as exc:
            # Do not leak parser excerpts, literals, commands or credentials.
            raise SourcePrimitiveCoverageError(
                f"static parse failed: {path} ({type(exc).__name__})"
            ) from None
        for fact in result["sites"]:
            observations.append({**fact, "path": path})
        for call in result["calls"]:
            calls.append({**call, "path": path})
        symbols[path] = {"symbols": result["symbols"],
                         "dependencies": sorted(result["dependencies"])}
    calls.sort(key=lambda item: (item["path"], item["line"], item["column"],
                                 item["owner"], item["target"]))
    source_rows = [row for row in inventory if row.get("language")]
    corpus_digest = digest(source_rows)
    caller_digest, dependency_digest = digest(calls), digest(symbols)
    bodies = {row["path"]: row["digest"] for row in source_rows}
    vectors = defaultdict(list)
    observations.sort(key=lambda item: (item["path"], item["owner"], item["line"],
                                        item["column"], item["category"], item["shape"]))
    for fact in observations:
        vectors[(fact["path"], fact["owner"])].append(digest(fact))
    counters, sites = defaultdict(int), []
    dependencies = (
        f"corpus:{corpus_digest}", f"all-call-edges:{caller_digest}",
        f"all-symbols-imports-constants:{dependency_digest}",
    )
    for fact in observations:
        key = (fact["path"], fact["owner"], fact["category"])
        counters[key] += 1
        symbol = f"{fact['path']}::{fact['owner']}::{fact['category']}:{counters[key]}"
        context = {
            "format_version": FORMAT_VERSION, "parser_version": PARSER_VERSION,
            "fingerprint_version": FINGERPRINT_VERSION,
            "body_digest": bodies[fact["path"]], "corpus_digest": corpus_digest,
            "caller_digest": caller_digest, "dependency_digest": dependency_digest,
            "owner_symbols_digest": digest(symbols[fact["path"]]),
            "unresolved": sorted(fact.get("unresolved", [])),
        }
        vector = tuple(vectors[(fact["path"], fact["owner"])])
        fingerprint = digest({"site": fact, "context": context, "vector": vector,
                              "derived": list(derived)})
        sites.append(PrimitiveSite(
            symbol, fact["path"], fact["owner"], fact["category"], fact["line"],
            fact["column"], fact["shape"], fingerprint, context, dependencies,
            vector, tuple(sorted(fact.get("unresolved", []))), str(root),
        ))
    return {"sites": sites, "scope": inventory, "call_index": calls,
            "symbol_index": symbols, "derived": list(derived), "review_root": str(root)}


def discover_whole_source_primitives(root, *, node_command=("node",)):
    return collect_source_primitives(root, node_command=node_command)["sites"]
