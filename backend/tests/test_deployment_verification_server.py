"""Exercise the shipped verifier against an installed-host command boundary."""

import pytest

from tests.deployment_verification_fakes import (
    CONTAINER, InstalledHost, OTHER_CONTAINER, OTHER_SHA, ROOT, SENTINEL, SHA,
)


pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")


@pytest.fixture
def host(tmp_path):
    return InstalledHost(tmp_path)


def assert_failure(result, summary, reason):
    assert result.returncode != 0
    assert reason in summary
    assert "Verified" not in summary
    assert SENTINEL not in result.stdout + result.stderr + summary


def test_marker_image_and_private_readiness_are_bound_to_the_same_container(host):
    result, summary, _ = host.run()
    assert result.returncode == 0, result.stderr
    assert "Production server: Verified" in summary
    assert SENTINEL not in result.stdout + result.stderr + summary
    calls = host.calls()
    assert len([call for call in calls if call[0] == "spaceworks-compose.sh"]) == 2
    inspections = [call for call in calls if call[:2] == ["docker", "inspect"]]
    executions = [call for call in calls if call[:2] == ["docker", "exec"]]
    assert len(inspections) == 2 and len(executions) == 1
    assert all(call[-1] == CONTAINER for call in inspections)
    assert executions[0][2:5] == [CONTAINER, "python", "-c"]
    # Every external Compose/Docker observation must go through the hard timeout.
    bounded = [call[3:] for call in calls if call[0] == "timeout"]
    operations = [call for call in calls if call[0] in {"docker", "spaceworks-compose.sh"}]
    assert len(bounded) == len(operations) == 5
    for wrapped, operation in zip(bounded, operations):
        assert wrapped[1:] == operation[1:]
        assert wrapped[0].endswith(operation[0])


def test_already_current_but_unhealthy_is_not_verified_and_retries_are_finite(host):
    result, summary, _ = host.run(ready=[1])
    assert_failure(result, summary, "private readiness did not return HTTP 200")
    assert len([call for call in host.calls() if call[:2] == ["docker", "exec"]]) == 12
    assert len([call for call in host.calls() if call[0] == "sleep"]) == 11


def test_readiness_can_recover_within_the_budget(host):
    result, summary, _ = host.run(ready=[1, 1, 0])
    assert result.returncode == 0
    assert "Verified" in summary
    assert len([call for call in host.calls() if call[:2] == ["docker", "exec"]]) == 3
    assert len([call for call in host.calls() if call[0] == "sleep"]) == 2


@pytest.mark.parametrize("expected", ["", SHA.upper(), SHA[:-1], SHA + "\n", SENTINEL])
def test_invalid_expected_revision_fails_before_any_host_command(host, expected):
    result, summary, _ = host.run(expected=expected)
    assert_failure(result, summary, "invalid expected revision")
    assert host.calls() == []


@pytest.mark.parametrize("marker", [
    None, "", "1.2.3", "1.2.3-main.42." + OTHER_SHA[:12],
    "1.2.3-main.42." + SHA[:12].upper(),
    f"1.2.3-main.42.{SHA[:12]}\n{SENTINEL}",
])
def test_missing_invalid_or_wrong_release_markers_fail_before_docker(host, marker):
    if marker is None:
        host.marker.unlink()
    else:
        host.marker.write_text(marker)
    result, summary, _ = host.run()
    assert_failure(result, summary, "version marker" if marker is None else
                   ("release revision mismatch" if OTHER_SHA[:12] in marker else "invalid installed version marker"))
    assert host.calls() == []


@pytest.mark.parametrize("container", ["", "short", CONTAINER.upper(), f"{CONTAINER}\n{OTHER_CONTAINER}", SENTINEL])
def test_missing_invalid_or_ambiguous_container_never_reaches_docker(host, container):
    result, summary, _ = host.run(container=[container])
    assert_failure(result, summary, "invalid or ambiguous backend container")
    assert not any(call[0] == "docker" for call in host.calls())


@pytest.mark.parametrize("revision", ["", "<no value>", SHA.upper(), SHA[:-1], OTHER_SHA, f"{SHA}\n{SHA}", SENTINEL])
def test_missing_invalid_or_wrong_oci_revision_never_probes_readiness(host, revision):
    result, summary, _ = host.run(revision=[revision])
    assert_failure(result, summary, "backend image revision mismatch")
    assert not any(call[:2] == ["docker", "exec"] for call in host.calls())


@pytest.mark.parametrize(("config", "reason"), [
    ({"compose_fail": True}, "cannot resolve installed backend container"),
    ({"inspect_fail": True}, "cannot inspect backend revision"),
    ({"timeout_operation": "compose"}, "cannot resolve installed backend container"),
    ({"timeout_operation": "inspect"}, "cannot inspect backend revision"),
    ({"timeout_operation": "exec"}, "private readiness did not return HTTP 200"),
])
def test_tool_errors_and_timeouts_fail_sanitized_and_bounded(host, config, reason):
    result, summary, _ = host.run(**config)
    assert_failure(result, summary, reason)
    if config.get("timeout_operation") == "exec":
        attempts = [call for call in host.calls() if call[0] == "timeout" and "exec" in call]
        assert len(attempts) == 12


@pytest.mark.parametrize(("config", "reason"), [
    ({"container": [CONTAINER, OTHER_CONTAINER]}, "backend container changed"),
    ({"revision": [SHA, OTHER_SHA]}, "backend revision changed"),
    ({"revision": [SHA, ""]}, "backend revision changed"),
    ({"mutate_marker": f"1.2.4-main.43.{SHA[:12]}"}, "installed version changed"),
    ({"remove_marker": True}, "installed version marker disappeared"),
])
def test_observations_are_rechecked_after_readiness_before_claiming_success(host, config, reason):
    result, summary, _ = host.run(**config)
    assert_failure(result, summary, reason)
    assert any(call[:2] == ["docker", "exec"] for call in host.calls())
