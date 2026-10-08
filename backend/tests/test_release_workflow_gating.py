"""A release must publish the exact main push that passed CI, including its audit."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)
CI_GROUP = (
    "${{ github.workflow }}-${{ (github.event_name == 'push' && github.ref_name == 'main') "
    "&& 'main-push' || format('branch-{0}', github.head_ref || github.ref_name) }}"
)
RESOLVED_SHA = "${{ github.event.workflow_run.head_sha || github.sha }}"


def _workflow(name):
    # YAML 1.1 SafeLoader turns `on` into True; BaseLoader preserves Actions keys.
    return yaml.load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"),
                     Loader=yaml.BaseLoader)


def _group(event, ref_name, head_ref=""):
    """Evaluate only the two branches of the exact expression pinned by the caller."""
    suffix = "main-push" if event == "push" and ref_name == "main" else f"branch-{head_ref or ref_name}"
    return f"CI-{suffix}"


def test_ci_pushes_include_security_audit_and_sufficient_backend_time():
    """The successful CI conclusion must cover dependencies and allow the full suite to finish."""
    ci = _workflow("ci.yml")
    assert ci["on"]["push"]["branches"] == ["main"]
    assert {"main", "dev"} <= set(ci["on"]["pull_request"]["branches"])
    assert int(ci["jobs"]["backend"]["timeout-minutes"]) >= 75
    audit = ci["jobs"]["security-audit"]
    assert audit["uses"] == "./.github/workflows/security-audit.yml"
    assert audit["if"] == "github.event_name != 'pull_request'"
    assert "workflow_call" in _workflow("security-audit.yml")["on"]


@pytest.mark.parametrize("head_ref", ["main", "main-push", "dev"])
def test_pull_requests_cannot_cancel_main_release_ci(head_ref):
    """Even a fork branch named main-push must never share the release-gating push group."""
    expression = _workflow("ci.yml")["concurrency"]["group"]
    assert "main-push" in expression
    assert "format('branch-{0}'" in expression
    assert expression == CI_GROUP
    assert _group("push", "main") == "CI-main-push"
    assert _group("pull_request", "123/merge", head_ref) != _group("push", "main")
    assert "dev" not in _workflow("ci.yml")["on"]["push"]["branches"]


def test_release_waits_for_successful_main_push_ci():
    """Direct pushes and PR conclusions must not bypass the successful main CI gate."""
    release = _workflow("release.yml")
    triggers = release["on"]
    assert triggers["workflow_run"] == {
        "workflows": ["CI"], "types": ["completed"], "branches": ["main"],
    }
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers
    assert release["permissions"]["actions"] == "read"
    assert release["jobs"]["prepare"]["if"] == (
        "github.event_name == 'workflow_dispatch' || "
        "(github.event.workflow_run.conclusion == 'success' && "
        "github.event.workflow_run.event == 'push' && "
        "github.event.workflow_run.head_branch == 'main')"
    )


def _dispatch_step():
    return next(step for step in _workflow("release.yml")["jobs"]["prepare"]["steps"]
                if step.get("name") == "Require successful main CI for manual releases")


def test_manual_release_queries_successful_push_ci_for_exact_sha():
    """Dispatch must prove CI passed this commit, rather than trusting another green main run."""
    step = _dispatch_step()
    assert step["if"] == "github.event_name == 'workflow_dispatch'"
    assert step["env"]["RELEASE_REF"] == "${{ github.ref }}"
    assert step["env"]["SHA"] == "${{ steps.sha.outputs.sha }}"
    assert '[[ "$RELEASE_REF" != "refs/heads/main" ]]' in step["run"]
    assert "head_sha=$SHA&event=push&branch=main&status=success&per_page=1" in step["run"]
    assert "successful_runs < 1" in step["run"]


@pytest.mark.parametrize(
    ("ref", "count", "succeeds", "queried"),
    [("refs/heads/dev", "1", False, False),
     ("refs/heads/main", "0", False, True),
     ("refs/heads/main", "invalid", False, True),
     ("refs/heads/main", "1", True, True)],
)
def test_dispatch_gate_fails_closed_with_stubbed_github(tmp_path, ref, count, succeeds, queried):
    """Exercise only the isolated dispatch step; no real GitHub API or publishing runs."""
    stub = tmp_path / "gh"
    stub.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$GH_CALLS"\n'
        'printf "%s\\n" "$SUCCESS_COUNT"\n', encoding="utf-8",
    )
    stub.chmod(0o755)
    calls = tmp_path / "gh-calls.txt"
    result = subprocess.run(
        [shutil.which("bash") or "bash", "-c", _dispatch_step()["run"], "dispatch-test"],
        env={**os.environ, "BASH_ENV": "", "RELEASE_REF": ref, "SHA": "a" * 40,
             "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
             "GH_REPO": "test/repo", "GH_CALLS": calls.as_posix(), "SUCCESS_COUNT": count},
        capture_output=True, text=True, timeout=10,
    )
    assert (result.returncode == 0) == succeeds, result.stderr
    assert calls.exists() == queried
    if queried:
        assert calls.read_text().strip() == (
            "api repos/test/repo/actions/workflows/ci.yml/runs?head_sha=" + "a" * 40
            + "&event=push&branch=main&status=success&per_page=1 --jq .total_count"
        )


def test_all_release_consumers_use_the_resolved_commit():
    """workflow_run's ambient SHA may differ from the tested push; every checkout must pin it."""
    release = _workflow("release.yml")
    steps = [step for job in release["jobs"].values() for step in job.get("steps", [])]
    sha_step = next(step for step in steps if step.get("id") == "sha")
    assert sha_step["env"]["RESOLVED_SHA"] == RESOLVED_SHA
    assert release["run-name"] == "Release main@" + RESOLVED_SHA
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    text = re.sub(r"^run-name:.*\n", "", text, flags=re.MULTILINE)
    text = text.replace("RESOLVED_SHA: " + RESOLVED_SHA, "RESOLVED_SHA: tested-commit", 1)
    assert "github.sha" not in text
    assert "GITHUB_SHA" not in text
    checkouts = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
    assert checkouts, "The checkout scan must cover at least one step."
    for checkout in checkouts:
        assert checkout["with"]["ref"] in {
            "${{ steps.sha.outputs.sha }}", "${{ needs.prepare.outputs.sha }}",
        }
