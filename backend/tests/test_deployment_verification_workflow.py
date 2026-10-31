"""Released revisions and honest status reporting from the actual Actions shell."""

import pytest

from tests.deployment_verification_fakes import (
    OTHER_SHA, ROOT, SENTINEL, SHA, shell_run, shell_step, workflow,
)


pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")


def prepare(path, **overrides):
    return shell_run(path, shell_step("prepare"), {
        "EVENT_NAME": "workflow_run", "RELEASE_TITLE": f"Release main@{SHA}",
        "MANUAL_SHA": OTHER_SHA, "MANUAL_REF": "refs/heads/main",
        "HEAD_SHA": OTHER_SHA, "DEFAULT_BRANCH_SHA": OTHER_SHA, **overrides,
    })


def test_release_title_wins_over_release_workflow_head_and_current_main(tmp_path):
    result, summary, output = prepare(tmp_path)
    assert result.returncode == 0, result.stderr
    assert output == f"sha={SHA}\n"
    assert not summary


def test_manual_main_resolves_the_exact_manual_commit(tmp_path):
    result, _, output = prepare(tmp_path, EVENT_NAME="workflow_dispatch", RELEASE_TITLE="unused")
    assert result.returncode == 0
    assert output == f"sha={OTHER_SHA}\n"


@pytest.mark.parametrize("title", [
    "", f"Release dev@{SHA}", f"Release main@{SHA.upper()}", f"Release main@{SHA[:-1]}",
    f"Release main@{SHA}\n", f"Release main@{SHA}\nsha={OTHER_SHA}",
    f" Release main@{SHA}", f"Release main@{SHA} ",
    f"Release main@$(touch {SENTINEL})", f"Release main@{SHA}; echo {SENTINEL}",
])
def test_untrusted_release_titles_fail_without_output_or_shell_evaluation(tmp_path, title):
    result, summary, output = prepare(tmp_path, RELEASE_TITLE=title)
    assert result.returncode != 0
    assert output == ""
    assert "invalid release title or manual revision" in summary
    assert SENTINEL not in result.stdout + result.stderr + summary
    assert not (tmp_path / SENTINEL).exists()


@pytest.mark.parametrize("values", [
    {"EVENT_NAME": "pull_request"}, {"EVENT_NAME": "unknown"},
    {"EVENT_NAME": "workflow_dispatch", "MANUAL_REF": "refs/heads/dev"},
    *({"EVENT_NAME": "workflow_dispatch", "MANUAL_SHA": sha}
      for sha in ("", SHA.upper(), SHA[:-1], SHA + "\n", SENTINEL)),
])
def test_unknown_events_and_invalid_manual_revisions_fail_closed(tmp_path, values):
    result, summary, output = prepare(tmp_path, **values)
    assert result.returncode != 0 and not output
    assert SENTINEL not in result.stdout + result.stderr + summary


def test_frontend_is_independent_and_checks_out_only_the_prepared_revision():
    jobs = workflow()["jobs"]
    for name in ("prepare", "report"):
        assert jobs[name]["permissions"] == {}
        assert all("uses" not in step for step in jobs[name]["steps"])
    frontend = jobs["frontend"]
    assert frontend["needs"] == "prepare"
    assert frontend["runs-on"] == "ubuntu-latest"
    assert frontend["permissions"] == {"contents": "read"}
    assert "vars.PRODUCTION_FRONTEND_URL != ''" in frontend["if"]
    assert "SPACEWORKS_DEPLOY_RUNNER" not in frontend["if"]
    checkout, checker = frontend["steps"]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"] == {"ref": "${{ needs.prepare.outputs.sha }}", "persist-credentials": False}
    assert checker["env"]["EXPECTED_SHA"] == "${{ needs.prepare.outputs.sha }}"
    assert checker["run"] == ('python3 scripts/check-frontend-deployment.py '
                              '--expected-revision "$EXPECTED_SHA" --url "$PRODUCTION_FRONTEND_URL"')
    assert jobs["prepare"]["outputs"] == {"sha": "${{ steps.revision.outputs.sha }}"}
    assert jobs["report"]["if"] == "always()"
    assert set(jobs["report"]["needs"]) == {"prepare", "deploy", "frontend"}


@pytest.mark.parametrize(("prepare_result", "server", "frontend", "configured", "overall", "code"), [
    ("success", "success", "success", ("true", "true"), "Verified", 0),
    ("success", "failure", "success", ("true", "true"), "Failed", 1),
    ("success", "success", "failure", ("true", "true"), "Failed", 1),
    ("success", "cancelled", "success", ("true", "true"), "Failed", 1),
    ("success", "success", "cancelled", ("true", "true"), "Failed", 1),
    ("failure", "skipped", "skipped", ("true", "true"), "Failed", 1),
    ("skipped", "skipped", "skipped", ("true", "true"), "Not verified", 0),
    ("success", "skipped", "skipped", ("false", "false"), "Not verified", 0),
    ("success", "skipped", "success", ("false", "true"), "Not verified", 0),
    ("success", "success", "skipped", ("true", "false"), "Not verified", 0),
    ("success", "skipped", "success", ("true", "true"), "Not verified", 0),
    ("success", "unknown", "success", ("true", "true"), "Failed", 1),
])
def test_report_never_claims_a_skipped_or_failed_component_was_deployed(
    tmp_path, prepare_result, server, frontend, configured, overall, code,
):
    result, summary, _ = shell_run(tmp_path, shell_step("report"), {
        "PREPARE_RESULT": prepare_result, "SERVER_RESULT": server, "FRONTEND_RESULT": frontend,
        "SERVER_CONFIGURED": configured[0], "FRONTEND_CONFIGURED": configured[1],
        "RUN_URL": "https://github.com/example/project/actions/runs/123",
    })
    assert result.returncode == code, result.stderr
    assert summary.splitlines()[0] == f"Deployment: {overall}"
    for name, status, enabled in (("Production server", server, configured[0]),
                                  ("Netlify frontend", frontend, configured[1])):
        if status == "skipped":
            label = "Skipped / not verified" if enabled == "true" else "Not configured / not verified"
            assert f"{name}: {label}" in summary
        elif status == "cancelled":
            assert f"{name}: Failed (cancelled)" in summary
        elif status == "failure":
            assert f"{name}: Failed" in summary
    if overall != "Verified":
        assert "Deployment: Verified" not in summary
