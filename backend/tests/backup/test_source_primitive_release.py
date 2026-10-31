"""Actual release YAML dependency graph and standalone CLI; no provider calls."""

import json

import pytest
import yaml

from apps.backup.source_primitive_fingerprint import SourcePrimitiveCoverageError
from apps.backup.source_primitive_registry import load_registry
from .source_primitive_helpers import ROOT, cli, save_registry, sql_fixture, write_sources


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def needs(job):
    value = job.get("needs", [])
    return {value} if isinstance(value, str) else set(value)


def assert_required(job):
    assert "if" not in job, "Required release jobs cannot have a bypass condition"
    assert job.get("continue-on-error", False) is False
    for step in job["steps"]:
        assert "if" not in step
        assert step.get("continue-on-error", False) is False


def test_release_prepare_resolves_exact_sha_and_requires_successful_main_ci():
    release = workflow("release.yml")
    # PyYAML's YAML 1.1 loader treats the GitHub Actions "on" key as True.
    trigger = release[True]["workflow_run"]
    assert trigger == {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]}
    prepare = release["jobs"]["prepare"]
    assert needs(prepare) == set()
    assert prepare["if"] == (
        "github.event_name == 'workflow_dispatch' || "
        "(github.event.workflow_run.conclusion == 'success' && "
        "github.event.workflow_run.event == 'push' && github.event.workflow_run.head_branch == 'main')"
    )
    assert prepare["outputs"]["sha"] == "${{ steps.sha.outputs.sha }}"
    steps = prepare["steps"]
    resolve, = [s for s in steps if s.get("id") == "sha"]
    assert resolve["env"]["RESOLVED_SHA"] == "${{ github.event.workflow_run.head_sha || github.sha }}"
    assert 'if ! [[ "$RESOLVED_SHA" =~ ^[0-9a-f]{40}$ ]]; then' in resolve["run"]
    assert "exit 1" in resolve["run"]
    assert 'echo "sha=$RESOLVED_SHA" >> "$GITHUB_OUTPUT"' in resolve["run"]
    manual, = [s for s in steps if s.get("if") == "github.event_name == 'workflow_dispatch'"]
    assert manual["env"]["SHA"] == "${{ steps.sha.outputs.sha }}"
    assert manual["env"]["RELEASE_REF"] == "${{ github.ref }}"
    assert 'if [[ "$RELEASE_REF" != "refs/heads/main" ]]; then' in manual["run"]
    assert "actions/workflows/ci.yml/runs?head_sha=$SHA&event=push&branch=main&status=success" in manual["run"]
    assert '(( successful_runs < 1 ))' in manual["run"]
    assert "exit 1" in manual["run"]
    assert prepare.get("continue-on-error", False) is False
    for step in (resolve, manual):
        assert step.get("continue-on-error", False) is False
    assert "if" not in resolve
    checkout, = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["ref"] == "${{ steps.sha.outputs.sha }}"
    assert steps.index(resolve) < steps.index(manual) < steps.index(checkout)


def test_sole_publish_matrix_preserves_prepare_release_and_promotion_dependencies():
    jobs = workflow("release.yml")["jobs"]
    assert set(jobs) == {"prepare", "publish", "github-release", "promote-latest"}
    publish = jobs["publish"]
    assert_required(publish)
    assert needs(publish) == {"prepare"}
    assert publish["strategy"]["matrix"]["include"] == [
        {"context": "backend", "image": "spaceworks-backend"},
        {"context": "frontend", "image": "spaceworks-frontend"},
    ]
    checkout, = [s for s in publish["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["ref"] == "${{ needs.prepare.outputs.sha }}"
    pushing = []
    for name, job in jobs.items():
        for step in job.get("steps", []):
            if step.get("uses", "").startswith("docker/build-push-action@"):
                assert step["with"]["push"] is True
                assert step["with"]["context"] == "./${{ matrix.context }}"
                assert needs(job) == {"prepare"}
                assert_required(job)
                pushing.append(name)
    assert pushing == ["publish"]
    assert needs(jobs["github-release"]) == {"publish", "prepare"}
    assert_required(jobs["github-release"])
    release, = jobs["github-release"]["steps"]
    assert release["with"]["target_commitish"] == "${{ needs.prepare.outputs.sha }}"
    assert needs(jobs["promote-latest"]) == {"publish", "prepare", "github-release"}
    checkout, = [s for s in jobs["promote-latest"]["steps"]
                 if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["ref"] == "${{ needs.prepare.outputs.sha }}"


def test_ci_remains_dependency_audit_and_does_not_claim_application_tests_run():
    ci = workflow("ci.yml")
    assert ci["jobs"] == {"security-audit": {"uses": "./.github/workflows/security-audit.yml"}}
    audit = workflow("security-audit.yml")
    assert set(audit["jobs"]) == {"pip-audit"}
    commands = "\n".join(s.get("run", "") for s in audit["jobs"]["pip-audit"]["steps"])
    assert "pip-audit -r backend/requirements.txt" in commands
    assert all(command not in commands for command in ("pytest", "npm test", "tsc", "npm run build"))


def test_cli_accepts_an_unchanged_explicit_normalized_fixture(tmp_path):
    _, _, ledger, _ = sql_fixture(tmp_path)
    registry = save_registry(tmp_path.parent / (tmp_path.name + "-reviewed.json"), ledger)
    result = cli(tmp_path, "--registry", registry)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "REVIEWED release-source coverage: 1 sites"


@pytest.mark.parametrize("mutation", ["missing", "invalid-json", "unreviewed", "bad-version", "unknown-scope"])
def test_cli_bad_registry_and_unknown_scope_exit_nonzero(tmp_path, mutation):
    _, _, ledger, _ = sql_fixture(tmp_path)
    registry = tmp_path.parent / (tmp_path.name + "-registry.json")
    if mutation == "invalid-json":
        registry.write_text("{", encoding="utf-8")
    elif mutation == "unreviewed":
        save_registry(registry, dict(ledger, status="UNREVIEWED"))
    elif mutation == "bad-version":
        save_registry(registry, dict(ledger, parser_version="future-parser"))
    elif mutation != "missing":
        save_registry(registry, ledger)
        write_sources(tmp_path, {"runtime.new_language": "opaque executable\n"})
    result = cli(tmp_path, "--registry", registry)
    assert result.returncode != 0
    assert "source review refused:" in result.stderr
    assert "REVIEWED release-source coverage:" not in result.stdout
    if mutation == "unknown-scope":
        assert "scope/dependency index" in result.stderr
    if mutation == "unreviewed":
        assert "UNREVIEWED" in result.stderr


def test_cli_emits_only_fresh_unreviewed_drafts_and_refuses_overwrite(tmp_path):
    sql_fixture(tmp_path)
    output = tmp_path.parent / (tmp_path.name + "-draft.json")
    result = cli(tmp_path, "--emit-unreviewed", output)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "UNREVIEWED" and summary["sites"] == 1
    draft = load_registry(output)
    assert draft["status"] == "UNREVIEWED"
    assert draft["reviewer"] is draft["report"] is None
    assert all(e["review"]["status"] == "UNREVIEWED" and
               e["review"]["reviewer"] is e["review"]["report"] is e["review"]["evidence"] is None
               for e in draft["entries"])
    before = output.read_bytes()
    refused = cli(tmp_path, "--emit-unreviewed", output)
    assert refused.returncode != 0
    assert "source review refused:" in refused.stderr
    assert output.read_bytes() == before
    validation = cli(tmp_path, "--registry", output)
    assert validation.returncode != 0 and "UNREVIEWED" in validation.stderr


@pytest.mark.parametrize("json_text", ["{\"status\":1,\"status\":2}", "[] trailing", "null!"])
def test_registry_json_rejects_duplicate_keys_and_invalid_documents(tmp_path, json_text):
    path = tmp_path / "registry.json"
    path.write_text(json_text, encoding="utf-8")
    with pytest.raises(SourcePrimitiveCoverageError, match="duplicate|invalid"):
        load_registry(path)


def test_real_cli_refuses_unreviewed_production_registry_before_discovery():
    """Registry-admission integration: refusal occurs before source discovery.

    This does not execute the whole-corpus scanner or establish release readiness.
    """
    registry = load_registry(ROOT / "docs/source-audit/registry.json")
    assert registry["status"] == "UNREVIEWED"
    result = cli(ROOT)
    assert result.returncode == 1, result.stderr
    assert result.stderr.strip() == "source review refused: scope/corpus is UNREVIEWED"
    assert result.stdout == ""
