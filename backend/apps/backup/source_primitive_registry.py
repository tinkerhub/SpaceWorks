"""Strict reconciliation of explicit reviews against independent discovery."""

from dataclasses import asdict, is_dataclass
from copy import deepcopy
import json
from pathlib import Path

from .source_primitive_discovery import collect_source_primitives
from .source_primitive_fingerprint import (
    FINGERPRINT_VERSION, FORMAT_VERSION, PARSER_VERSION,
    SourcePrimitiveCoverageError, digest,
)
from .source_primitive_ledger import (
    LEDGER_FORMAT_VERSION, expand_entries, index_binding, normalize_entries,
    validate_index_binding,
)
from .source_primitive_reports import report_binding, review_fingerprint, validate_report


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourcePrimitiveCoverageError("duplicate registry JSON key")
        result[key] = value
    return result


def load_registry(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourcePrimitiveCoverageError("missing or invalid review registry JSON") from None


def _mapping(value):
    return asdict(value) if is_dataclass(value) else value


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_entry(site, entry, *, production):
    if not isinstance(entry, dict) or entry.get("status") != "REVIEWED":
        raise SourcePrimitiveCoverageError(f"unreviewed source: {site.source_symbol}")
    for key in ("purpose", "owner", "disposition", "reviewer", "report"):
        if not _nonempty(entry.get(key)):
            raise SourcePrimitiveCoverageError(f"invalid review {key}: {site.source_symbol}")
    if entry.get("review_mode") != "reviewed-direct":
        raise SourcePrimitiveCoverageError("unsupported inherited-boundary review mode")
    if production and entry["report"] == "explicit-caller-attestation":
        raise SourcePrimitiveCoverageError("production review needs actual review report")
    versions = {"format_version": FORMAT_VERSION, "parser_version": PARSER_VERSION,
                "fingerprint_version": FINGERPRINT_VERSION}
    if any(entry.get(key) != value for key, value in versions.items()):
        raise SourcePrimitiveCoverageError("review parser/fingerprint version mismatch")
    if entry.get("fingerprint") != site.fingerprint:
        raise SourcePrimitiveCoverageError(f"changed fingerprint: {site.source_symbol}")
    evidence = entry.get("evidence")
    if not isinstance(evidence, dict) or not _nonempty(evidence.get("explanation")):
        raise SourcePrimitiveCoverageError("missing explicit evidence explanation")
    expected = {
        "body_digest": site.context["body_digest"],
        "dependency_digest": site.context["dependency_digest"],
        "context_digest": digest(site.context),
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise SourcePrimitiveCoverageError("changed evidence body/dependency fingerprint")
    if (tuple(evidence.get("dependencies", ())) != site.dependencies
            or tuple(evidence.get("site_vector", ())) != site.site_vector):
        raise SourcePrimitiveCoverageError("incomplete dependency or actual-site vector")
    if (tuple(evidence.get("unresolved_facts", ())) != site.unresolved
            or not _nonempty(evidence.get("runtime_boundary"))):
        raise SourcePrimitiveCoverageError("unresolved facts need complete direct context review")
    binding = validate_report(site.review_root, entry["report"], entry.get("report_binding"))
    if entry.get("review_fingerprint") != review_fingerprint(site.fingerprint, binding):
        raise SourcePrimitiveCoverageError("changed review report/source fingerprint")


def validate_whole_source_primitive_coverage(root, registry=None, *, node_command=("node",)):
    root = Path(root).resolve()
    if registry is None:
        registry = load_registry(root / "docs/source-audit/registry.json")
    envelope = isinstance(registry, dict) and "format_version" in registry
    production = (root / "backend/apps").is_dir() and (root / "frontend").is_dir()
    if production and (not envelope or registry.get("ledger_format_version")
                       != LEDGER_FORMAT_VERSION):
        raise SourcePrimitiveCoverageError("production registry requires normalized reviewed scope envelope")
    derived = registry.get("derived", []) if envelope else []
    census = collect_source_primitives(root, node_command=node_command, derived=derived)
    reconcile_registry(census, registry, production=production)
    return census["sites"]


def reconcile_registry(census, registry, *, production=False):
    """Allow the CLI to discover exactly once, then reconcile that same census."""
    envelope = isinstance(registry, dict) and "format_version" in registry
    normalized = envelope and "ledger_format_version" in registry
    if production and not normalized:
        raise SourcePrimitiveCoverageError("production registry requires normalized reviewed scope envelope")
    if envelope:
        for key, value in (("format_version", FORMAT_VERSION), ("parser_version", PARSER_VERSION),
                           ("fingerprint_version", FINGERPRINT_VERSION)):
            if registry.get(key) != value:
                raise SourcePrimitiveCoverageError("registry format/parser/fingerprint version mismatch")
        if registry.get("status") != "REVIEWED":
            raise SourcePrimitiveCoverageError("scope/corpus is UNREVIEWED")
        if not _nonempty(registry.get("reviewer")) or not _nonempty(registry.get("report")):
            raise SourcePrimitiveCoverageError("scope review requires reviewer and report")
        for key in ("scope", "derived"):
            if registry.get(key) != census[key]:
                raise SourcePrimitiveCoverageError(f"changed or missing scope/dependency index: {key}")
        for key in ("call_index", "symbol_index"):
            if normalized:
                validate_index_binding(registry.get(key), census[key])
            elif registry.get(key) != census[key]:
                raise SourcePrimitiveCoverageError(f"changed or missing scope/dependency index: {key}")
        entries = (expand_entries(registry, census["sites"]) if normalized
                   else registry.get("entries"))
    else:
        entries = registry
    _reconcile_entries(census, entries, production=production)
    if envelope:
        validate_report(census.get("review_root"), registry["report"],
                        registry.get("report_binding"))
        if registry.get("review_fingerprint") != _envelope_fingerprint(registry):
            raise SourcePrimitiveCoverageError("changed scope review report/evidence fingerprint")


def _review_records(entries):
    if isinstance(entries, dict):
        records = []
        for key, value in entries.items():
            entry = _mapping(value)
            if not isinstance(entry, dict) or key != entry.get("source_symbol"):
                raise SourcePrimitiveCoverageError("orphan registry key/source symbol")
            records.append(entry)
    elif isinstance(entries, list):
        records = [_mapping(value) for value in entries]
    else:
        raise SourcePrimitiveCoverageError("registry entries must be list or symbol mapping")
    return records


def _reconcile_entries(census, entries, *, production):
    by_symbol = {}
    for entry in _review_records(entries):
        if not isinstance(entry, dict) or not _nonempty(entry.get("source_symbol")):
            raise SourcePrimitiveCoverageError("invalid source review record")
        symbol = entry["source_symbol"]
        if symbol in by_symbol:
            raise SourcePrimitiveCoverageError(f"double review: {symbol}")
        by_symbol[symbol] = entry
    actual = {site.source_symbol: site for site in census["sites"]}
    stale = sorted(set(by_symbol) - set(actual))
    missing = sorted(set(actual) - set(by_symbol))
    if stale:
        raise SourcePrimitiveCoverageError(f"stale/orphan source reviews: {len(stale)} ({stale[0]})")
    if missing:
        raise SourcePrimitiveCoverageError(f"new/unreviewed source sites: {len(missing)} ({missing[0]})")
    for symbol, site in actual.items():
        _validate_entry(site, by_symbol[symbol], production=production)
    return by_symbol


def _envelope_fingerprint(envelope):
    return digest({key: value for key, value in envelope.items() if key != "review_fingerprint"})


def _normalized_envelope(census, reviews, *, status, reviewer, report):
    envelope = {
        "format_version": FORMAT_VERSION, "parser_version": PARSER_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION, "status": status,
        "reviewer": reviewer, "report": report,
        **{key: deepcopy(census[key]) for key in ("scope", "derived")},
        **{key: index_binding(census[key]) for key in ("call_index", "symbol_index")},
        **normalize_entries(census["sites"], reviews),
    }
    envelope["report_binding"] = (report_binding(census.get("review_root"), report)
                                  if status == "REVIEWED" else None)
    envelope["review_fingerprint"] = (_envelope_fingerprint(envelope)
                                      if status == "REVIEWED" else None)
    return envelope


def unreviewed_registry(census):
    """Export normalized observations ONLY; never infer or copy any approval."""
    reviews = [dict(source_symbol=site.source_symbol, fingerprint=site.fingerprint,
                    status="UNREVIEWED", purpose=None, owner=None, disposition=None,
                    reviewer=None, evidence=None, report=None, review_mode=None,
                    report_binding=None, review_fingerprint=None,
                    format_version=FORMAT_VERSION, parser_version=PARSER_VERSION,
                    fingerprint_version=FINGERPRINT_VERSION) for site in census["sites"]]
    draft = _normalized_envelope(census, reviews, status="UNREVIEWED", reviewer=None,
                                 report=None)
    for record in draft["derived"]:
        record.update(status="UNREVIEWED", reviewer=None, report=None,
                      report_binding=None, review_fingerprint=None)
    return draft


def owner_context_sites(census):
    """Partition CURRENT in-memory sites by (path, lexical owner) for reviewers.

    Values are tuples of the original PrimitiveSite objects, including complete
    contexts/vectors. The census still carries full call_index and symbol_index;
    these observations confer no approval and do not rediscover the checkout.
    """
    owners = {}
    for site in census["sites"]:
        owners.setdefault((site.path, site.owner), []).append(site)
    return {key: tuple(sites) for key, sites in owners.items()}


def assemble_reviewed_registry(census, entries, *, reviewer, report, production=True):
    """Assemble ONLY caller-supplied explicit reviews against this exact census.

    No status, purpose, evidence or per-site reviewer is filled in. Missing,
    duplicate, stale or invalid reviews refuse before an envelope is returned.
    The caller must separately supply the scope review's reviewer and report.
    """
    if not _nonempty(reviewer) or not _nonempty(report):
        raise SourcePrimitiveCoverageError("scope review requires reviewer and report")
    by_symbol = _reconcile_entries(census, entries, production=production)
    ledger = _normalized_envelope(
        census, [by_symbol[site.source_symbol] for site in census["sites"]],
        status="REVIEWED", reviewer=reviewer, report=report,
    )
    reconcile_registry(census, ledger, production=production)
    return ledger
