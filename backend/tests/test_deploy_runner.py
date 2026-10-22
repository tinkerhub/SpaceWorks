"""Production runner boundaries and installer behavior, without network or privileges."""

import subprocess

import pytest
import yaml

from tests.deploy_runner_fakes import BASH, REMOVE_TOKEN, ROOT, TOKEN, RunnerHost


pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")


def test_only_the_release_deploy_workflow_can_target_the_production_runner():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    # YAML 1.1 interprets the unquoted Actions key `on` as True.
    document = yaml.safe_load(workflow)
    triggers = document.get("on", document.get(True))
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"] == {
        "workflows": ["Continuous Release"], "types": ["completed"], "branches": ["main"],
    }
    assert document["permissions"] == {}
    assert document["concurrency"] == {"group": "production-deploy", "cancel-in-progress": False}
    assert set(document["jobs"]) == {"deploy"}
    job = document["jobs"]["deploy"]
    assert job["runs-on"] == ["self-hosted", "spaceworks-prod"]
    assert job["timeout-minutes"] == 90
    condition = job["if"]
    assert " ".join(condition.removeprefix("${{").removesuffix("}}").split()) == (
        "vars.SPACEWORKS_DEPLOY_RUNNER == 'true' && ((github.event_name == 'workflow_dispatch' "
        "&& github.ref == 'refs/heads/main') || github.event.workflow_run.conclusion == 'success')"
    )
    for required in ("vars.SPACEWORKS_DEPLOY_RUNNER == 'true'", "github.event_name == 'workflow_dispatch'",
                     "github.ref == 'refs/heads/main'", "github.event.workflow_run.conclusion == 'success'"):
        assert required in condition
    assert len(job["steps"]) == 1
    step = job["steps"][0]
    assert "uses" not in step
    assert step["run"].strip() == 'bash "$SPACEWORKS_INSTALL_DIR/scripts/update.sh" --no-module-changes'
    environment = {**document.get("env", {}), **job.get("env", {}), **step.get("env", {})}
    assert str(environment["SPACEWORKS_DEPLOY_WAIT"]) == "1"
    assert "SPACEWORKS_INSTALL_DIR" not in environment
    assert "uses:" not in workflow
    for path in (ROOT / ".github/workflows").iterdir():
        if path.name != "deploy.yml" and path.suffix in {".yml", ".yaml"}:
            source = path.read_text()
            assert "self-hosted" not in source, path
            assert "spaceworks-prod" not in source, path


@pytest.fixture
def host(tmp_path):
    return RunnerHost(tmp_path)


@pytest.mark.parametrize("values", [
    {"RUNNER_TOKEN": ""}, {"FAKE_ARCH": "riscv64"}, {"FAKE_OS": "Darwin"},
    {"FAKE_UID": "0"}, {"FAKE_SYSTEMD": "0"},
])
def test_installation_refuses_invalid_preconditions_before_download(host, values):
    result = host.run(**values)
    assert result.returncode != 0
    assert not any(line.startswith(("curl|", "tar|", "config|", "svc|")) for line in host.recorded())


@pytest.mark.parametrize(("arch", "digest"), [
    ("x86_64", "af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32"),
    ("aarch64", "628b4a7258487b80c1d3c221095a7ded349f5ae0175fd3dfab708d07428f041b"),
])
def test_verified_install_uses_private_token_and_current_install_owner(host, arch, digest):
    result = host.run(FAKE_ARCH=arch)
    assert result.returncode == 0, result.stderr
    calls = host.recorded()
    asset_arch = "x64" if arch == "x86_64" else "arm64"
    assert any(f"actions-runner-linux-{asset_arch}-2.338.0.tar.gz" in line for line in calls)
    assert any(line.startswith("sha256sum|") and digest in line and ("--check" in line or "-c" in line) for line in calls)
    assert calls.index(next(line for line in calls if line.startswith("sha256sum|"))) < calls.index(
        next(line for line in calls if line.startswith("tar|")))
    config = next(line for line in calls if line.startswith("config|"))
    for argument in ("--unattended", "--url https://github.com/example/Fork", "--labels spaceworks-prod",
                     "--name spaceworks-production", "--replace"):
        assert argument in config
    assert "--token" not in config
    assert "svc|install install-owner" in calls and "svc|start" in calls
    assert (host.runner / ".env").read_text().splitlines() == [f"SPACEWORKS_INSTALL_DIR={host.root}"]
    assert (host.path / "retained-cron").read_text().strip() == "3 4 * * * keep-other-job"
    assert "SPACEWORKS_DEPLOY_RUNNER" in result.stdout
    assert "review" in result.stdout.lower() and "approv" in result.stdout.lower()


def test_checksum_mismatch_prevents_extract_and_configuration(host):
    result = host.run(FAKE_CHECKSUM_FAIL="1")
    assert result.returncode != 0
    assert not any(line.startswith(("tar|", "config|", "svc|")) for line in host.recorded())


@pytest.mark.parametrize("installed_service", [True, False])
def test_same_repository_rerun_keeps_configuration_and_refreshes_install_path(host, installed_service):
    host.configured(service=installed_service)
    result = host.run(RUNNER_TOKEN="")
    assert result.returncode == 0, result.stderr
    calls = host.recorded()
    assert not any(line.startswith(("curl|", "tar|", "config|")) for line in calls)
    dotenv = (host.runner / ".env").read_text().splitlines()
    assert "KEEP=value" in dotenv
    assert [line for line in dotenv if line.startswith("SPACEWORKS_INSTALL_DIR=")] == [
        f"SPACEWORKS_INSTALL_DIR={host.root}"]
    assert "svc|start" in calls
    assert ("svc|install install-owner" in calls) is not installed_service
    if installed_service:
        assert calls.index("svc|stop") < calls.index("svc|start")


def test_runner_configured_for_another_repository_is_never_overwritten(host):
    host.configured(repository="other/Repository")
    result = host.run()
    assert result.returncode != 0
    assert not any(line.startswith(("curl|", "tar|", "config|", "svc|")) for line in host.recorded())


def test_nonempty_unconfigured_install_is_never_extracted_over(host):
    host.runner.mkdir()
    (host.runner / "keep").write_text("keep me")
    result = host.run()
    assert result.returncode != 0
    assert (host.runner / "keep").read_text() == "keep me"
    assert not any(line.startswith(("tar|", "config|", "svc|")) for line in host.recorded())


@pytest.mark.parametrize("accept_risk", ["", "1"])
def test_known_unsafe_fork_policy_requires_explicit_risk_override(host, accept_risk):
    result = host.run(FAKE_POLICY="first_time_contributors", SPACEWORKS_RUNNER_ACCEPT_RISK=accept_risk)
    assert (result.returncode == 0) is bool(accept_risk), result.stderr
    assert any("repos/example/Fork/actions/permissions/fork-pr-contributor-approval --jq .approval_policy"
               in line for line in host.recorded())
    assert ("svc|start" in host.recorded()) is bool(accept_risk)


def test_policy_lookup_failure_is_best_effort_with_warning(host):
    result = host.run(FAKE_GH_FAIL="1")
    assert result.returncode == 0, result.stderr
    assert "polic" in (result.stdout + result.stderr).lower()


def test_remove_requires_its_own_private_token_and_stops_the_service(host):
    host.configured()
    result = host.run("--remove", EXPECTED_TOKEN=REMOVE_TOKEN)
    assert result.returncode == 0, result.stderr
    calls = host.recorded()
    assert calls.index("svc|stop") < calls.index("svc|uninstall") < calls.index("config|remove --unattended")
    assert not any(line.startswith(("curl|", "tar|")) for line in calls)
    assert "svc|start" not in calls


def test_remove_refuses_registration_token_as_substitute_for_removal_token(host):
    host.configured()
    result = host.run("--remove", RUNNER_REMOVE_TOKEN="")
    assert result.returncode != 0
    assert not any(line.startswith(("config|", "svc|")) for line in host.recorded())


def test_setup_installs_the_runner_after_the_stack_is_up():
    source = (ROOT / "setup.sh").read_text()
    helper = (ROOT / "scripts/setup-deploy-runner.sh").read_text()
    assert source.index("\nask_deploy_runner\n") < source.index('"${COMPOSE[@]}" up')
    assert source.index("\nfinish_deploy_runner_setup\n") > source.index('"${COMPOSE[@]}" up')
    assert source.index("\nretire_update_tombstone\n") < source.index('"${COMPOSE[@]}" up')
    assert source.index("\nretire_update_polling\n") < source.index('"${COMPOSE[@]}" up')
    assert 'bash "$ROOT/scripts/install-deploy-runner.sh"' in helper
    assert "env_file_append" not in helper  # no secret: the runner prompts for its own token


@pytest.mark.parametrize(("answer", "installer_exit", "runs"), [
    ("Y", 0, True), ("yes", 0, True), ("", 0, False), ("N", 0, False), ("Y", 1, True),
])
def test_setup_runner_opt_in_runs_the_installer_and_never_fails_setup(tmp_path, answer, installer_exit, runs):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/install-deploy-runner.sh").write_text(
        f"touch '{tmp_path.as_posix()}/installer-ran'\nexit {installer_exit}\n", encoding="utf-8")
    script = f'''set -e
ROOT='{tmp_path.as_posix()}'
FIRST_RUN=1
source '{ROOT.as_posix()}/scripts/setup-deploy-runner.sh'
ask_deploy_runner
finish_deploy_runner_setup
'''
    result = subprocess.run([BASH, "-c", script], cwd=tmp_path, input=(answer + "\n").encode(),
                            capture_output=True, timeout=30)
    # The app is already up when this runs, so a runner problem must not fail setup.
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "installer-ran").exists() is runs
    assert (b"Automatic deploys are not set up yet" in result.stderr) is (installer_exit != 0)


def test_failed_registration_explains_why_without_revealing_the_token(host):
    # The fake config.sh echoes the token to stderr and fails on an unexpected token.
    result = host.run(EXPECTED_TOKEN="not-the-token-we-sent")
    assert result.returncode != 0
    assert "[redacted]" in result.stderr
    assert TOKEN not in result.stdout + result.stderr
    assert "Runner registration failed" in result.stderr


def test_a_failed_first_registration_can_be_retried_with_a_fresh_token(host):
    failed = host.run(EXPECTED_TOKEN="not-the-token-we-sent")
    assert failed.returncode != 0
    # The half-installed directory is gone, so the retry is not refused as "not empty".
    assert not host.runner.exists() or not any(host.runner.iterdir())
    retried = host.run()
    assert retried.returncode == 0, retried.stderr
    assert (host.runner / ".runner").exists()


def test_a_removed_runner_can_be_installed_again(host):
    host.configured()
    removed = host.run("--remove", EXPECTED_TOKEN=REMOVE_TOKEN)
    assert removed.returncode == 0, removed.stderr
    # The installer-owned directory is deleted, so the next install is not refused as "not empty".
    assert not host.runner.exists()
    reinstalled = host.run()
    assert reinstalled.returncode == 0, reinstalled.stderr
    assert (host.runner / ".runner").exists()


def test_installer_menu_requires_an_update_before_runner_setup_on_old_installs():
    source = (ROOT / "install.sh").read_text()
    runner_branch = source.split("runner) ", 1)[1].split(";; esac", 1)[0]
    guard = '[[ -f "$INSTALL_DIR/scripts/install-deploy-runner.sh" ]] || die'
    assert runner_branch.index(guard) < runner_branch.index("run_installed")
