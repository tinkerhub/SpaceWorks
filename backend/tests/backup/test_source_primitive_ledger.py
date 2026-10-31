"""Normalized storage must reconstruct the exact explicit in-memory review."""

from copy import deepcopy
import hashlib
import json

import pytest

from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import SourcePrimitiveCoverageError, digest
from apps.backup.source_primitive_ledger import (
    TABLES, expand_entries, index_binding, validate_index_binding,
)
from apps.backup.source_primitive_registry import (
    assemble_reviewed_registry, load_registry, reconcile_registry,
)
from .source_primitive_helpers import (
    explicit_review, json_value, review_dict, review_options, sql_fixture, write_sources,
)


def test_many_sites_in_two_local_owners_intern_once_and_reduce_bytes(tmp_path):
    body = "from adapter import cursor\n"
    for owner in ("first", "second"):
        body += f"def {owner}():\n" + "    cursor.execute('DELETE FROM x')\n" * 16
    write_sources(tmp_path, {"owners.py": body})
    census = collect_source_primitives(tmp_path)
    sites = census["sites"]
    assert len(sites) == 32
    assert {(s.path, s.owner, s.category) for s in sites} == {
        ("owners.py", "first", "raw_sql"), ("owners.py", "second", "raw_sql"),
    }
    options = review_options(tmp_path)
    # Explicit inspection is restricted to these two known local fixture owners.
    reviews = [explicit_review(site, **options) for site in sites]
    ledger = assemble_reviewed_registry(census, reviews, reviewer=options["reviewer"],
                                       report=options["report"])
    tables = ledger["tables"]
    assert {name: len(tables[name]) for name in TABLES} == {
        "owners": 2, "contexts": 1, "site_vectors": 2, "dependencies": 1,
    }
    for entry in ledger["entries"]:
        site, evidence = entry["site"], entry["review"]["evidence"]
        for field in ("site_vector", "dependencies"):
            assert field not in site and field not in evidence
            assert evidence[field + "_ref"] == site[field + "_ref"]
        assert "context" not in site and "owner" not in site and "path" not in site
    records = [review_dict(review) for review in reviews]
    assert expand_entries(json_value(ledger), sites) == records
    reconcile_registry(census, json_value(ledger), production=True)
    flat = dict(ledger, entries=[dict(site=s.to_dict(), review=r)
                               for s, r in zip(sites, records, strict=True)])
    flat.pop("tables")
    assert len(json.dumps(ledger)) < 0.7 * len(json.dumps(flat))


@pytest.mark.parametrize("mutation", [
    "missing-table", "missing-reference", "unknown-reference", "tampered-value",
    "extra-reference", "duplicate-entry", "unknown-entry", "tampered-observation",
    "mismatched-evidence-reference", "unknown-evidence-reference", "unknown-format",
    "unreferenced-table-value", "wrong-table-shape", "inline-evidence-vector",
])
def test_missing_tampered_duplicate_or_unknown_references_refuse(tmp_path, mutation):
    census, _, baseline, _ = sql_fixture(tmp_path)
    ledger = deepcopy(baseline)
    site = ledger["entries"][0]["site"]
    evidence = ledger["entries"][0]["review"]["evidence"]
    if mutation == "missing-table":
        del ledger["tables"]["owners"]
    elif mutation == "missing-reference":
        del site["context_ref"]
    elif mutation == "unknown-reference":
        site["owner_ref"] = "0" * 64
    elif mutation == "tampered-value":
        ledger["tables"]["owners"][site["owner_ref"]]["path"] = "elsewhere.py"
    elif mutation == "extra-reference":
        site["mystery_ref"] = site["context_ref"]
    elif mutation == "duplicate-entry":
        ledger["entries"].append(deepcopy(ledger["entries"][0]))
    elif mutation == "unknown-entry":
        site["source_symbol"] = "unknown.py::owner::raw_sql:1"
    elif mutation == "tampered-observation":
        site["line"] += 1
    elif mutation == "mismatched-evidence-reference":
        evidence["site_vector_ref"] = "0" * 64
    elif mutation == "unknown-evidence-reference":
        evidence["mystery_ref"] = site["context_ref"]
    elif mutation == "unknown-format":
        ledger["ledger_format_version"] = "normalized-source-ledger-v999"
    elif mutation == "unreferenced-table-value":
        extra = {"path": "unused.py", "owner": "unused"}
        ledger["tables"]["owners"][digest(extra)] = extra
    elif mutation == "wrong-table-shape":
        ledger["tables"]["owners"] = []
    else:
        evidence["site_vector"] = list(census["sites"][0].site_vector)
    with pytest.raises(SourcePrimitiveCoverageError, match="normalized"):
        expand_entries(ledger, census["sites"])


def test_duplicate_intern_table_json_keys_fail_before_expansion(tmp_path):
    _, _, ledger, _ = sql_fixture(tmp_path)
    key, value = next(iter(ledger["tables"]["owners"].items()))
    pair = json.dumps(key) + ":" + json.dumps(value)
    path = tmp_path.parent / (tmp_path.name + "-duplicate.json")
    path.write_text('{"tables":{"owners":{' + pair + "," + pair + "}}}", encoding="utf-8")
    with pytest.raises(SourcePrimitiveCoverageError, match="duplicate registry JSON key"):
        load_registry(path)


@pytest.mark.parametrize("index_name", ["call_index", "symbol_index"])
def test_index_summary_uses_exact_canonical_sha_count_and_shape(tmp_path, index_name):
    census, _, ledger, _ = sql_fixture(tmp_path)
    value = census[index_name]
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    expected = {"sha256": hashlib.sha256(raw).hexdigest(), "count": len(value),
                "shape": "list" if isinstance(value, list) else "object"}
    assert ledger[index_name] == index_binding(value) == expected
    validate_index_binding(expected, value)
    changed = deepcopy(value)
    if isinstance(changed, list):
        changed.append(dict(path="caller.py", owner="bypass", target="owner.write", line=1, column=0))
    else:
        changed["new-symbol"] = {"symbols": {}, "dependencies": []}
    with pytest.raises(SourcePrimitiveCoverageError, match="index digest/shape/count"):
        validate_index_binding(expected, changed)


@pytest.mark.parametrize("mutation", ["hash", "count", "bool-count", "shape", "extra", "missing"])
def test_index_summary_rejects_tampered_and_unknown_fields(tmp_path, mutation):
    census, _, ledger, _ = sql_fixture(tmp_path)
    binding = deepcopy(ledger["call_index"])
    if mutation == "hash":
        binding["sha256"] = "0" * 64
    elif mutation == "count":
        binding["count"] += 1
    elif mutation == "bool-count":
        binding["count"] = True
    elif mutation == "shape":
        binding["shape"] = "object"
    elif mutation == "extra":
        binding["future"] = "unrecognized"
    else:
        del binding["sha256"]
    with pytest.raises(SourcePrimitiveCoverageError, match="index digest/shape/count"):
        validate_index_binding(binding, census["call_index"])


@pytest.mark.parametrize("version_field", [
    "format_version", "parser_version", "fingerprint_version", "ledger_format_version",
])
def test_unknown_ledger_or_detector_version_never_validates(tmp_path, version_field):
    census, _, ledger, _ = sql_fixture(tmp_path)
    ledger[version_field] = "unknown-future-version"
    with pytest.raises(SourcePrimitiveCoverageError, match="version|normalized"):
        reconcile_registry(census, ledger, production=True)


def test_mutated_caller_is_refused_even_when_only_index_summary_changes(tmp_path):
    census, _, ledger, _ = sql_fixture(tmp_path)
    changed = deepcopy(census)
    changed["call_index"].append(dict(path="new.py", owner="bypass", target="owner.write", line=1, column=0))
    assert changed["sites"] == census["sites"]
    with pytest.raises(SourcePrimitiveCoverageError, match="index digest/shape/count"):
        reconcile_registry(changed, ledger)
