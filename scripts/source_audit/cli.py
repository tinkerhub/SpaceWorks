"""The CLI uses only stdlib helpers loaded without application package imports."""

import argparse
from collections import Counter
import importlib
import json
from pathlib import Path
import sys
import types


def load_helpers():
    location = Path(__file__).resolve().parents[2] / "backend/apps/backup"
    namespace = "_spaceworks_source_review"
    if namespace not in sys.modules:
        package = types.ModuleType(namespace)
        package.__path__ = [str(location)]
        sys.modules[namespace] = package
    return (
        importlib.import_module(f"{namespace}.source_primitive_discovery"),
        importlib.import_module(f"{namespace}.source_primitive_registry"),
        importlib.import_module(f"{namespace}.source_primitive_fingerprint"),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--emit-unreviewed", type=Path,
                        help="export a draft; never copies or creates approvals")
    parser.add_argument("--node-command", nargs=argparse.REMAINDER, default=["node"],
                        help="Node argument vector; put this option last (no shell evaluation)")
    args = parser.parse_args(argv)
    discovery, registry_api, metadata = load_helpers()
    try:
        root = args.root.resolve()
        if args.emit_unreviewed:
            census = discovery.collect_source_primitives(root, node_command=args.node_command)
            draft = registry_api.unreviewed_registry(census)
            # Do not overwrite an existing review ledger, even accidentally.
            with args.emit_unreviewed.open("x", encoding="utf-8") as handle:
                json.dump(draft, handle, indent=2, sort_keys=True)
                handle.write("\n")
            counts = Counter(site.category for site in census["sites"])
            print(json.dumps({"status": "UNREVIEWED", "sites": len(census["sites"]),
                              "scope_files": len(census["scope"]),
                              "call_edges": len(census["call_index"]),
                              "categories": dict(sorted(counts.items()))}, sort_keys=True))
            return 0
        ledger = args.registry or root / "docs/source-audit/registry.json"
        records = registry_api.load_registry(ledger)
        if isinstance(records, dict) and records.get("status") == "UNREVIEWED":
            raise metadata.SourcePrimitiveCoverageError("scope/corpus is UNREVIEWED")
        sites = registry_api.validate_whole_source_primitive_coverage(
            root, registry=records, node_command=args.node_command,
        )
        print(f"REVIEWED release-source coverage: {len(sites)} sites")
        return 0
    except (metadata.SourcePrimitiveCoverageError, OSError) as exc:
        # Exception messages from the pure guard contain identifiers, never excerpts.
        print(f"source review refused: {exc}", file=sys.stderr)
        return 1
