"""Explicit review decisions and evidence, independent of discovery."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from apps.backup.source_primitive_fingerprint import (
    SourcePrimitiveCoverageError, reviewed_direct_entry,
)
from apps.backup.source_primitive_ledger import expand_entries
from apps.backup.source_primitive_registry import (
    assemble_reviewed_registry, owner_context_sites, reconcile_registry,
    unreviewed_registry,
)
from apps.backup.source_primitive_discovery import collect_source_primitives
from .source_primitive_helpers import (
    explicit_review, review_dict, review_options, sql_fixture, write_sources,
)


def test_discovery_and_draft_never_create_approvals(tmp_path):
    census, entry, ledger, _ = sql_fixture(tmp_path)
    before = deepcopy(census)
    draft = unreviewed_registry(census)
    assert census == before
    assert draft["status"] == "UNREVIEWED"
    assert draft["reviewer"] is draft["report"] is None
    records = expand_entries(draft, census["sites"])
    assert len(records) == 1
    assert records[0]["status"] == "UNREVIEWED"
    for key in ("purpose", "owner", "disposition", "reviewer", "evidence", "report"):
        assert records[0][key] is None
    assert not hasattr(census["sites"][0], "reviewer")
    with pytest.raises(SourcePrimitiveCoverageError, match="UNREVIEWED"):
        reconcile_registry(census, draft)
    assert ledger["status"] == entry.status == "REVIEWED"


def test_explicit_typed_review_snapshot_and_normalized_roundtrip(tmp_path):
    census, entry, ledger, options = sql_fixture(tmp_path)
    site, = census["sites"]
    record = review_dict(entry)
    assert record["source_symbol"] == "owner.py::write::raw_sql:1"
    assert record["purpose"] == options["purpose"]
    assert record["owner"] == options["domain"]
    assert record["disposition"] == options["disposition"]
    assert record["reviewer"] == options["reviewer"]
    assert record["report"] == options["report"]
    assert record["evidence"]["body_digest"] == site.context["body_digest"]
    assert record["evidence"]["dependencies"] == list(site.dependencies)
    assert record["evidence"]["site_vector"] == list(site.site_vector)
    assert expand_entries(ledger, census["sites"]) == [record]
    assert owner_context_sites(census) == {("owner.py", "write"): (site,)}
    reconcile_registry(census, ledger, production=True)


@pytest.mark.parametrize("field", ["purpose", "owner", "disposition", "reviewer", "report"])
@pytest.mark.parametrize("invalid", [None, "", "  ", False, 17])
def test_assembly_requires_every_explicit_review_field(tmp_path, field, invalid):
    census, entry, _, options = sql_fixture(tmp_path)
    record = asdict(entry)
    record[field] = invalid
    with pytest.raises(SourcePrimitiveCoverageError, match=f"invalid review {field}"):
        assemble_reviewed_registry(census, [record], reviewer=options["reviewer"],
                                   report=options["report"])


@pytest.mark.parametrize("field", ["reviewer", "report"])
def test_scope_approval_cannot_be_filled_in_by_assembly(tmp_path, field):
    census, entry, _, options = sql_fixture(tmp_path)
    scope = dict(reviewer=options["reviewer"], report=options["report"])
    scope[field] = None
    with pytest.raises(SourcePrimitiveCoverageError, match="scope review requires"):
        assemble_reviewed_registry(census, [entry], **scope)


@pytest.mark.parametrize("mutation,diagnostic", [
    ("missing", "new/unreviewed"), ("duplicate", "double review"),
    ("stale", "stale/orphan"), ("orphan-key", "orphan registry key"),
    ("draft", "unreviewed source"), ("false-reviewed", "unreviewed source"),
    ("parser", "version mismatch"), ("mode", "unsupported inherited-boundary"),
    ("vector", "incomplete dependency"), ("dependencies", "incomplete dependency"),
    ("context", "changed evidence"), ("body", "changed evidence"),
    ("fingerprint", "changed fingerprint"), ("explanation", "missing explicit evidence"),
    ("attestation-only", "actual review report"),
])
def test_invalid_duplicate_stale_or_incomplete_reviews_refuse(tmp_path, mutation, diagnostic):
    census, entry, _, options = sql_fixture(tmp_path)
    record = asdict(entry)
    records = [record]
    if mutation == "missing":
        records = []
    elif mutation == "duplicate":
        records.append(deepcopy(record))
    elif mutation == "stale":
        record["source_symbol"] = "gone.py::write::raw_sql:1"
    elif mutation == "orphan-key":
        records = {"wrong-key": record}
    elif mutation in {"draft", "false-reviewed"}:
        record["status"] = "UNREVIEWED" if mutation == "draft" else True
    elif mutation == "parser":
        record["parser_version"] = "future-parser"
    elif mutation == "mode":
        record["review_mode"] = "folder-is-safe"
    elif mutation in {"vector", "dependencies"}:
        record["evidence"]["site_vector" if mutation == "vector" else "dependencies"] = []
    elif mutation in {"context", "body"}:
        record["evidence"][mutation + "_digest"] = "0" * 64
    elif mutation == "fingerprint":
        record["fingerprint"] = "0" * 64
    elif mutation == "explanation":
        record["evidence"]["explanation"] = ""
    else:
        record["report"] = "explicit-caller-attestation"
    with pytest.raises(SourcePrimitiveCoverageError, match=diagnostic):
        assemble_reviewed_registry(census, records, reviewer=options["reviewer"],
                                   report=options["report"])


def test_report_is_required_even_for_a_resolved_direct_review(tmp_path):
    census, _, _, options = sql_fixture(tmp_path)
    # A real report was supplied in the valid baseline; omission must not mint one.
    with pytest.raises(SourcePrimitiveCoverageError, match="report"):
        reviewed_direct_entry(
            census["sites"][0], purpose=options["purpose"], owner=options["domain"],
            disposition=options["disposition"], reviewer=options["reviewer"],
            evidence=options["explanation"],
        )


def test_nonexistent_report_is_not_an_actual_review(tmp_path):
    census, entry, _, options = sql_fixture(tmp_path)
    record = asdict(entry)
    record["report"] = str(tmp_path.parent / "no-such-review-report.txt")
    with pytest.raises(SourcePrimitiveCoverageError, match="report"):
        assemble_reviewed_registry(census, [record], reviewer=options["reviewer"],
                                   report=options["report"])


def test_folder_name_confers_no_review_or_disposition(tmp_path):
    write_sources(tmp_path, {"reviewed/safe/public_readonly.py":
                            "from adapter import cursor\ncursor.execute('DELETE FROM x')\n"})
    census = collect_source_primitives(tmp_path)
    assert any(s.category == "raw_sql" for s in census["sites"])
    with pytest.raises(SourcePrimitiveCoverageError, match="UNREVIEWED"):
        reconcile_registry(census, unreviewed_registry(census))


@pytest.mark.parametrize("omitted", ["facts", "boundary", "report"])
def test_opaque_review_requires_exact_acknowledgements(tmp_path, omitted):
    write_sources(tmp_path, {"custom.ps1": "Invoke-CustomMutation\n"})
    census = collect_source_primitives(tmp_path)
    site, = census["sites"]
    assert site.category == "unresolved_dynamic" and site.unresolved
    options = review_options(tmp_path)
    good = explicit_review(site, facts=site.unresolved, **options)
    ledger = assemble_reviewed_registry(census, [good], reviewer=options["reviewer"],
                                       report=options["report"])
    reconcile_registry(census, ledger, production=True)
    bad = dict(options, facts=site.unresolved)
    if omitted == "facts":
        bad["facts"] = ("invented-fact",)
    elif omitted == "boundary":
        bad["runtime_boundary"] = ""
    else:
        bad["report"] = None
    with pytest.raises(SourcePrimitiveCoverageError, match="opaque direct review"):
        explicit_review(site, **bad)


def test_exact_opaque_context_review_refuses_changed_whole_file(tmp_path):
    write_sources(tmp_path, {"custom.ps1": "Invoke-CustomMutation\n"})
    census = collect_source_primitives(tmp_path)
    site, = census["sites"]
    options = review_options(tmp_path)
    review = explicit_review(site, facts=site.unresolved, **options)
    reconcile_registry(census, [review])
    write_sources(tmp_path, {"custom.ps1": "Invoke-CustomMutation -DifferentScope\n"})
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        reconcile_registry(collect_source_primitives(tmp_path), [review], production=False)


@pytest.mark.parametrize("mutation", ["deleted", "changed-bytes"])
def test_opaque_review_report_is_actual_bound_evidence(tmp_path, mutation):
    from pathlib import Path

    write_sources(tmp_path, {"custom.ps1": "Invoke-CustomMutation\n"})
    census = collect_source_primitives(tmp_path)
    site, = census["sites"]
    options = review_options(tmp_path)
    entry = explicit_review(site, facts=site.unresolved, **options)
    ledger = assemble_reviewed_registry(census, [entry], reviewer=options["reviewer"],
                                       report=options["report"])
    reconcile_registry(census, ledger, production=True)
    report = Path(options["report"])
    if mutation == "deleted":
        report.unlink()
    else:
        report.write_text("Review withdrawn: this context is not approved.\n", encoding="utf-8")
    with pytest.raises(SourcePrimitiveCoverageError, match="^actual review report missing, unsafe or changed$"):
        reconcile_registry(census, ledger, production=True)


def test_drafting_reviewed_derived_census_clears_all_approval_fields_without_mutating_input(tmp_path):
    from .source_primitive_helpers import assert_node20
    from .test_source_primitive_derived import derived_fixture

    assert_node20()
    _, _, reviewed = derived_fixture(tmp_path)
    census = collect_source_primitives(tmp_path, derived=[reviewed])
    before = deepcopy(census)
    draft = unreviewed_registry(census)
    assert census == before
    record, = draft["derived"]
    assert record is not census["derived"][0]
    assert record["inputs"] is not census["derived"][0]["inputs"]
    for value in (draft, record):
        assert value["status"] == "UNREVIEWED"
        assert all(value[key] is None for key in (
            "reviewer", "report", "report_binding", "review_fingerprint",
        ))
    assert {key: value for key, value in record.items() if key not in {
        "status", "reviewer", "report", "report_binding", "review_fingerprint",
    }} == {key: value for key, value in reviewed.items() if key not in {
        "status", "reviewer", "report", "report_binding", "review_fingerprint",
    }}
    with pytest.raises(SourcePrimitiveCoverageError, match="scope/corpus is UNREVIEWED"):
        reconcile_registry(census, draft)
