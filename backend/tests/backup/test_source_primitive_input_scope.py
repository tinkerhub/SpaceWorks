"""Exact public templates and active SVG content require whole-input review."""

import hashlib
from pathlib import Path
import subprocess

import pytest

from apps.backup.source_primitive_discovery import collect_source_primitives
from apps.backup.source_primitive_fingerprint import SourcePrimitiveCoverageError
from apps.backup.source_primitive_registry import assemble_reviewed_registry, reconcile_registry
from apps.backup.source_primitive_scope import collect_scope
from .source_primitive_helpers import explicit_review, review_options, write_sources


# Deliberately independent of the implementation's allowlist: additions must be reviewed.
PUBLIC_TEMPLATES = (
    ".env.example", ".env.production.example", "backend/.env.example", "frontend/.env.example",
)


@pytest.mark.parametrize("changed_path", PUBLIC_TEMPLATES)
def test_each_exact_public_env_template_hashes_and_byte_change_invalidates_review(tmp_path, changed_path):
    files = {path: f"PUBLIC_FIXTURE_LABEL=template-{index}\n"
             for index, path in enumerate(PUBLIC_TEMPLATES)}
    write_sources(tmp_path, files)
    census = collect_source_primitives(tmp_path)
    assert {row["path"] for row in census["scope"]} == set(PUBLIC_TEMPLATES)
    for row in census["scope"]:
        assert row["classification"] == "production-input"
        assert row["language"] == "opaque"
        assert row["digest"] == hashlib.sha256(files[row["path"]].encode()).hexdigest()
    assert {site.path for site in census["sites"]} == set(PUBLIC_TEMPLATES)
    options = review_options(tmp_path)
    reviews = [explicit_review(site, facts=site.unresolved, **options) for site in census["sites"]]
    ledger = assemble_reviewed_registry(census, reviews, reviewer=options["reviewer"], report=options["report"])
    reconcile_registry(census, ledger)
    write_sources(tmp_path, {changed_path: files[changed_path] + "PUBLIC_FIXTURE_FLAG=changed\n"})
    changed = collect_source_primitives(tmp_path)
    with pytest.raises(SourcePrimitiveCoverageError, match="scope/dependency index: scope"):
        reconcile_registry(changed, ledger)
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        reconcile_registry(changed, reviews)


def test_script_bearing_svg_is_opaque_whole_context_without_execution(tmp_path, monkeypatch):
    def no_process(*args, **kwargs):
        pytest.fail("Opaque SVG inspection must not start a parser or executable")

    monkeypatch.setattr(subprocess, "run", no_process)
    path = "public/icon.svg"
    source = ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">'
              '<script>throw new Error("MUST_NOT_EXECUTE")</script></svg>\n')
    write_sources(tmp_path, {path: source})
    rows, sources = collect_scope(tmp_path)
    expected = hashlib.sha256(source.encode()).hexdigest()
    assert rows == [dict(path=path, classification="production-input", language="opaque", digest=expected)]
    assert sources == {path: ("opaque", source)}
    census = collect_source_primitives(tmp_path)
    site, = census["sites"]
    assert site.path == path and site.owner == "<unit>"
    assert site.category == "unresolved_dynamic"
    assert site.context["body_digest"] == expected
    assert site.unresolved == ("whole-source-input-or-unsupported-grammar",)
    options = review_options(tmp_path)
    review = explicit_review(site, facts=site.unresolved, **options)
    ledger = assemble_reviewed_registry(census, [review], reviewer=options["reviewer"], report=options["report"])
    reconcile_registry(census, ledger)
    write_sources(tmp_path, {path: source.replace("MUST_NOT_EXECUTE", "CHANGED_SCRIPT")})
    changed = collect_source_primitives(tmp_path)
    with pytest.raises(SourcePrimitiveCoverageError, match="scope/dependency index: scope"):
        reconcile_registry(changed, ledger)
    with pytest.raises(SourcePrimitiveCoverageError, match="changed fingerprint"):
        reconcile_registry(changed, [review])


def test_existing_static_images_still_have_no_source_hash_or_review_site(tmp_path, monkeypatch):
    files = {"public/icon.png": "opaque static image", "public/photo.jpg": "static photo"}
    write_sources(tmp_path, files)

    def no_read(path):
        pytest.fail("Static image policy must not start reading image bytes")

    monkeypatch.setattr(Path, "read_bytes", no_read)
    rows, sources = collect_scope(tmp_path)
    assert rows == [dict(path=path, classification="static-asset", language=None) for path in sorted(files)]
    assert sources == {}
    assert collect_source_primitives(tmp_path)["sites"] == []
