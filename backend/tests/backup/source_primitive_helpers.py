"""Small explicit synthetic reviews; never approve or repair the real corpus.

Import only the production pure-static namespace. No Django, conftest, model,
source execution, mocked discovery or replacement foreign parser is needed.
"""

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import (
    PrimitiveSite, ReviewedEntry, ReviewEvidence, SourcePrimitiveCoverageError,
    reviewed_direct_entry,
)
from apps.backup.source_primitive_registry import (
    assemble_reviewed_registry, reconcile_registry,
    validate_whole_source_primitive_coverage,
)

ROOT = Path(__file__).resolve().parents[3]
SQL = "from adapter import cursor\ndef write():\n    cursor.execute('DELETE FROM x')\n"


def write_sources(root, files):
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def review_options(tmp_path):
    # Outside the scanned fixture: the report is evidence, not executable input.
    report = tmp_path.parent / (tmp_path.name + "-explicit-review.txt")
    report.write_text(
        "Synthetic review: adapter cursor mutation, explicit fixture ownership; "
        "all actual sites and unresolved receiver facts inspected. "
        "Runtime boundary: caller supplies the cursor; no runtime safety proof.\n",
        encoding="utf-8",
    )
    return dict(
        purpose="Exercise explicit deletion review in a disposable source fixture",
        domain="synthetic inventory owner", disposition="reviewed direct mutation",
        reviewer="stage3-fixture-reviewer", report=str(report),
        explanation="Inspected the complete synthetic owner, imports and site vector",
        runtime_boundary="Caller supplies adapter cursor; review confers no runtime authorization",
    )


def explicit_review(site, *, purpose, domain, disposition, reviewer, report,
                    explanation, runtime_boundary, facts=()):
    """Caller chooses ONE actual site and supplies every review decision."""
    assert isinstance(site, PrimitiveSite)
    entry = reviewed_direct_entry(
        site, purpose=purpose, owner=domain, disposition=disposition,
        reviewer=reviewer, report=report,
        evidence=dict(explanation=explanation, unresolved_facts=tuple(facts),
                      runtime_boundary=runtime_boundary),
    )
    assert isinstance(entry, ReviewedEntry)
    assert isinstance(entry.evidence, ReviewEvidence)
    return entry


def sql_fixture(tmp_path):
    """Exactly one known site, explicitly reviewed; valid before any mutation."""
    write_sources(tmp_path, {"owner.py": SQL})
    census = collect_source_primitives(tmp_path)
    assert [(s.path, s.owner, s.category) for s in census["sites"]] == [
        ("owner.py", "write", "raw_sql"),
    ]
    site, = census["sites"]
    options = review_options(tmp_path)
    entry = explicit_review(site, **options)
    ledger = assemble_reviewed_registry(
        census, [entry], reviewer=options["reviewer"], report=options["report"],
    )
    assert validate_whole_source_primitive_coverage(tmp_path, ledger) == census["sites"]
    return census, entry, ledger, options


def json_value(value):
    return json.loads(json.dumps(value))


def review_dict(entry):
    return json_value(asdict(entry))


def save_registry(path, ledger):
    path.write_text(json.dumps(ledger), encoding="utf-8")
    return path


def cli(root, *args, timeout=120):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_source_primitives.py"),
         "--root", str(root), *map(str, args)],
        text=True, capture_output=True, check=False, timeout=timeout,
    )


def assert_node20():
    result = subprocess.run(
        ["node", "-p", "process.versions.node"], text=True, capture_output=True,
        check=True, timeout=20,
    )
    assert result.stdout.strip().split(".")[0] == "20", (
        "Run foreign-source proofs inside the Python 3.12 / Node 20 tooling environment"
    )
    assert (ROOT / "frontend/node_modules/typescript/lib/typescript.js").is_file()
