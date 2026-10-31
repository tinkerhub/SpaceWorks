"""Internal readable JSON layout; no shipped ledger migration is implied.

``ledger_format_version`` versions serialization independently of fingerprints.
Each entry has a ``site`` observation and an explicit ``review`` record. Owners
(path + lexical owner), contexts, site vectors and dependencies are interned in
four maps keyed by the existing ASCII canonical-JSON SHA-256. Review evidence
references the same vectors as its site. Expansion restores the original review
record for the existing validator; observations must exactly match discovery.
Call/symbol indexes retain their canonical digest, top-level shape and count;
the complete indexes remain in the in-memory census for direct context review.
Scope classifications, paths and source hashes remain fully readable in JSON.
"""

from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass
import re

from .source_primitive_fingerprint import (
    PrimitiveSite, ReviewedEntry, SourcePrimitiveCoverageError, digest,
)


LEDGER_FORMAT_VERSION = "normalized-source-ledger-v2"
TABLES = ("owners", "contexts", "site_vectors", "dependencies")
SITE_FIELDS = {field.name for field in fields(PrimitiveSite)} - {"review_root"}
REVIEW_FIELDS = {field.name for field in fields(ReviewedEntry)}
SITE_REFS = {"owner_ref", "context_ref", "site_vector_ref", "dependencies_ref"}


def _fail():
    # Never include source facts, literals or attacker-controlled values.
    raise SourcePrimitiveCoverageError("invalid normalized ledger reference/hash/shape")


def _json_value(value):
    if isinstance(value, PrimitiveSite):
        return _json_value(value.to_dict())
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def index_binding(value):
    """Commit to the exact existing canonical index, without serializing it twice."""
    if not isinstance(value, (list, dict)):
        _fail()
    return {"sha256": digest(value), "count": len(value),
            "shape": "list" if isinstance(value, list) else "object"}


def validate_index_binding(binding, actual):
    if (not isinstance(binding, dict) or set(binding) != {"sha256", "count", "shape"}
            or type(binding["count"]) is not int or binding != index_binding(actual)):
        raise SourcePrimitiveCoverageError("changed or missing dependency index digest/shape/count")


def _intern(tables, table, value):
    value = _json_value(value)
    key = digest(value)
    if key in tables[table] and tables[table][key] != value:
        _fail()
    tables[table][key] = value
    return key


def normalize_entries(sites, reviews):
    """Serialize supplied records only; this function never creates review decisions."""
    tables = {name: {} for name in TABLES}
    entries = []
    for site, review in zip(sites, reviews, strict=True):
        observation = _json_value(site)
        owner = {key: observation.pop(key) for key in ("path", "owner")}
        observation["owner_ref"] = _intern(tables, "owners", owner)
        for field, table in (("context", "contexts"), ("site_vector", "site_vectors"),
                             ("dependencies", "dependencies")):
            observation[field + "_ref"] = _intern(tables, table, observation.pop(field))
        record = _json_value(review)
        if not isinstance(record, dict) or set(record) - REVIEW_FIELDS:
            _fail()
        evidence = record.get("evidence")
        if isinstance(evidence, dict):
            for field, table in (("dependencies", "dependencies"),
                                 ("site_vector", "site_vectors")):
                if field not in evidence or field + "_ref" in evidence:
                    _fail()
                evidence[field + "_ref"] = _intern(tables, table, evidence.pop(field))
        entries.append({"site": observation, "review": record})
    return {"ledger_format_version": LEDGER_FORMAT_VERSION, "tables": tables,
            "entries": entries}


def _valid_value(table, value):
    if table == "owners":
        return (isinstance(value, dict) and set(value) == {"path", "owner"}
                and all(isinstance(item, str) and item for item in value.values()))
    if table == "contexts":
        return isinstance(value, dict)
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def expand_entries(ledger, actual_sites):
    """Validate every reference and reconstruct exact old-style review records."""
    if ledger.get("ledger_format_version") != LEDGER_FORMAT_VERSION:
        _fail()
    tables = ledger.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        _fail()
    for table, values in tables.items():
        if not isinstance(values, dict):
            _fail()
        for key, value in values.items():
            if (not isinstance(key, str) or not re.fullmatch("[0-9a-f]{64}", key)
                    or not _valid_value(table, value) or digest(value) != key):
                _fail()
    used = {name: set() for name in TABLES}

    def resolve(table, key):
        if not isinstance(key, str) or key not in tables[table]:
            _fail()
        used[table].add(key)
        return deepcopy(tables[table][key])

    entries = ledger.get("entries")
    if not isinstance(entries, list):
        _fail()
    actual = {site.source_symbol: site for site in actual_sites}
    records, seen = [], set()
    expected_fields = (SITE_FIELDS - {"path", "owner", "context", "dependencies",
                                      "site_vector"}) | SITE_REFS
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"site", "review"}:
            _fail()
        site, record = deepcopy(entry["site"]), deepcopy(entry["review"])
        if not isinstance(site, dict) or set(site) != expected_fields:
            _fail()
        refs = {field: site.pop(field) for field in SITE_REFS}
        site.update(resolve("owners", refs["owner_ref"]))
        for field, table in (("context", "contexts"), ("dependencies", "dependencies"),
                             ("site_vector", "site_vectors")):
            site[field] = resolve(table, refs[field + "_ref"])
        symbol = site.get("source_symbol")
        if not isinstance(symbol, str) or symbol in seen or symbol not in actual:
            _fail()
        seen.add(symbol)
        if digest(site) != digest(actual[symbol].to_dict()):
            raise SourcePrimitiveCoverageError("changed normalized site observation")
        if (not isinstance(record, dict) or set(record) - REVIEW_FIELDS
                or record.get("source_symbol") != symbol):
            _fail()
        evidence = record.get("evidence")
        if isinstance(evidence, dict):
            for field, table in (("dependencies", "dependencies"),
                                 ("site_vector", "site_vectors")):
                ref = field + "_ref"
                if (field in evidence or ref not in evidence
                        or evidence[ref] != refs[ref]):
                    _fail()
                evidence[field] = resolve(table, evidence.pop(ref))
            if any(key.endswith("_ref") for key in evidence):
                _fail()
        records.append(record)
    if any(set(tables[name]) != used[name] for name in TABLES):
        _fail()
    return records
