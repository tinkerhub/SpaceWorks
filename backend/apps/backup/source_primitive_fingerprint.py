"""Versioned, deterministic metadata for the release-source review ledger.

No Django imports: the release checker runs against a checkout, never a database.
The conservative corpus binding is deliberate: a changed caller with no primitive
must invalidate reviews too. This is a human review aid, not a Python verifier.
"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any


FORMAT_VERSION = "source-review-v2"
PARSER_VERSION = "python-ast+typescript+shell-facts-v2"
FINGERPRINT_VERSION = "location-owner-corpus-callgraph-report-v2"


class SourcePrimitiveCoverageError(ValueError):
    """The checkout does not exactly match its explicit reviewed ledger."""


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class PrimitiveSite:
    source_symbol: str
    path: str
    owner: str
    category: str
    line: int
    column: int
    shape: str
    fingerprint: str
    context: dict
    dependencies: tuple[str, ...]
    site_vector: tuple[str, ...]
    unresolved: tuple[str, ...]
    # Local provenance for report reads, never serialized or fingerprinted. The
    # same checkout must yield identical observations at another absolute path.
    review_root: str = field(default="", compare=False, repr=False)

    def to_dict(self):
        value = asdict(self)
        value.pop("review_root")
        return value


@dataclass(frozen=True)
class ReviewEvidence:
    explanation: str
    body_digest: str
    dependency_digest: str
    dependencies: tuple[str, ...]
    site_vector: tuple[str, ...]
    context_digest: str
    unresolved_facts: tuple[str, ...]
    runtime_boundary: str


@dataclass(frozen=True)
class ReviewedEntry:
    source_symbol: str
    fingerprint: str
    purpose: str
    owner: str
    disposition: str
    reviewer: str
    evidence: ReviewEvidence
    status: str = "REVIEWED"
    review_mode: str = "reviewed-direct"
    report: str | None = None
    format_version: str = FORMAT_VERSION
    parser_version: str = PARSER_VERSION
    fingerprint_version: str = FINGERPRINT_VERSION
    report_binding: dict | None = None
    review_fingerprint: str = ""

    def to_dict(self):
        return asdict(self)


def reviewed_direct_entry(site, *, purpose, owner, disposition, reviewer,
                          evidence=None, dependencies=None, report=None):
    """Record an EXPLICIT caller's context review; discovery never calls this.

    Direct review accepts responsibility for the whole bound context, including
    opaque facts. It does not infer approval from an app, method, or flow-map name.
    Every review requires an actual report. Production report paths are relative
    to the discovered checkout; only disposable fixtures allow temp siblings.
    """
    for label, value in (("purpose", purpose), ("owner", owner),
                         ("disposition", disposition), ("reviewer", reviewer)):
        if not isinstance(value, str) or not value.strip():
            raise SourcePrimitiveCoverageError(f"missing explicit {label}")
    if dependencies is not None and tuple(dependencies) != site.dependencies:
        raise SourcePrimitiveCoverageError("review dependencies do not match discovery")
    explanation = purpose if evidence is None else evidence
    runtime_boundary = "direct static context review"
    unresolved_facts = ()
    if isinstance(explanation, dict):
        unresolved_facts = tuple(explanation.get("unresolved_facts", ()))
        runtime_boundary = explanation.get("runtime_boundary", "")
        explanation = explanation.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        raise SourcePrimitiveCoverageError("review evidence requires an explanation")
    if site.unresolved and (unresolved_facts != site.unresolved or not report
                            or not isinstance(runtime_boundary, str)
                            or not runtime_boundary.strip()):
        raise SourcePrimitiveCoverageError(
            "opaque direct review requires exact facts, runtime boundary and report"
        )
    from .source_primitive_reports import report_binding, review_fingerprint

    report_snapshot = report_binding(site.review_root, report)
    binding = ReviewEvidence(
        explanation, site.context["body_digest"], site.context["dependency_digest"],
        site.dependencies, site.site_vector, digest(site.context),
        unresolved_facts, runtime_boundary,
    )
    return ReviewedEntry(site.source_symbol, site.fingerprint, purpose, owner,
                         disposition, reviewer, binding,
                         report=report, report_binding=report_snapshot,
                         review_fingerprint=review_fingerprint(site.fingerprint, report_snapshot))
