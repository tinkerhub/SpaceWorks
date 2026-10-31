"""Host-only guards for TLS topology, backup-first updates and migration-free rollback."""

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


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


LATEST_VERSION = "1.2.3-main.42.abcdef123456"
PREVIOUS_VERSION = "1.2.3-main.41.123456abcdef"


def _run_update(tmp_path, current, args=(), failure="", layer="", pinned=""):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("update.sh", "update-lock.sh", "module-selection.sh", "env-file.sh", "host-image.sh",
                 "retire-update-polling.sh", "retire-update-tombstone.sh", "install-host-bundle.sh",
                 "refresh-proxy-config.sh"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    (tmp_path / ".env").write_text("TOMBSTONED_APPS=updates,payments\n", encoding="utf-8")
    # The backup reads the active database from the host pointer, not a running backend.
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "database-pointer.env").write_text(
        "DATABASE_URL=postgres://app:secret@db:5432/active_restored_db\n", encoding="utf-8",
    )
    _write_executable(
        scripts / "init-host-orchestration.sh",
        '#!/bin/sh\nprintf "%s|init-host\\n" "$MAKERSPACE_IMAGE_TAG" >> "$FAKE_COMPOSE_CALLS"\n',
    )
    _write_executable(
        scripts / "setup-host-orchestration.sh",
        'install_producer_capability() { printf "%s|producer-proof\\n" "$HOST_CONFIG_IMAGE" >> "$FAKE_COMPOSE_CALLS"; }\n'
        # This fixture does not exercise image identity; the independent host tests do.
        'refresh_old_image_identity_and_only_trusted_records() { return 0; }\n',
    )
    if current is not None:
        (tmp_path / ".spaceworks-version").write_text(current + "\n", encoding="utf-8")
    _write_executable(
        scripts / "spaceworks-compose.sh",
        '#!/bin/sh\nprintf "%s\\0" "$@" >> "$FAKE_COMPOSE_RAW_CALLS"\n'
        'printf "\\n" >> "$FAKE_COMPOSE_RAW_CALLS"\n'
        # Keep legacy exact logs while retaining untouched argv in a separate file.
        # Only project the adjacent startup pair; all other commands/flags stay intact.
        'if [ "${1:-}" = bundled ] && [ "${2:-}" = up ] && [ "${3:-}" = -d ] '
        '&& [ "${4:-}" = --pull ] && [ "${5:-}" = never ]; then\n'
        '  shift 5; set -- bundled up -d "$@"\n'
        'fi\n'
        'printf "%s|%s\\n" "$MAKERSPACE_IMAGE_TAG" "$*" >> "$FAKE_COMPOSE_CALLS"\n'
        'case "$FAKE_FAILURE:$*" in\n'
        '  backup:*pg_dump*) exit 1 ;;\n'
        '  deploy:"bundled up -d") [ "$MAKERSPACE_IMAGE_TAG" != "$FAKE_LATEST_VERSION" ] ;;\n'
        'esac\n',
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "docker", '#!/bin/sh\nprintf "docker|%s\\n" "$*" >> "$FAKE_COMPOSE_CALLS"\n')
    _write_executable(
        bin_dir / "curl",
        '#!/bin/sh\nprintf \'{"tag_name":"v%s"}\\n\' "$FAKE_LATEST_VERSION"\n',
    )
    calls_file = tmp_path / "compose-calls.txt"
    shell_root = subprocess.check_output(
        [shutil.which("bash") or "bash", "-c", "pwd"], cwd=tmp_path, text=True,
    ).strip()
    completed = subprocess.run(
        [shutil.which("bash") or "bash", (scripts / "update.sh").as_posix(), "--no-module-changes", *args],
        cwd=tmp_path,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "SPACEWORKS_OPS_HOST_DIR": f"{shell_root}/ops",
            "SPACEWORKS_COMPOSE_LAYER": layer,
            "FAKE_COMPOSE_CALLS": f"{shell_root}/compose-calls.txt",
            "FAKE_COMPOSE_RAW_CALLS": f"{shell_root}/compose-raw-argv.bin",
            "FAKE_LATEST_VERSION": LATEST_VERSION,
            "FAKE_FAILURE": failure,
            "SPACEWORKS_PINNED_RELEASE": pinned,
        },
        capture_output=True, text=True, timeout=30,
    )
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    assert all("update_control" not in call for call in calls)
    assert not (tmp_path / ".spaceworks-update.lock").exists()
    return completed, calls


@pytest.mark.parametrize(
    ("current", "args", "applies"),
    [
        (PREVIOUS_VERSION, (), True),
        (LATEST_VERSION, (), False),
        (LATEST_VERSION, ("--force",), True),
        (None, (), True),
    ],
    ids=["different-version", "already-installed", "force-reinstall", "untracked-install"],
)
def test_host_version_and_force_decide_whether_to_apply(tmp_path, current, args, applies):
    completed, calls = _run_update(tmp_path, current, args)

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / ".spaceworks-version").read_text().strip() == LATEST_VERSION
    if applies:
        assert any("pg_dump" in call and "SPACEWORKS_BACKUP_DATABASE=active_restored_db" in call for call in calls)
        assert any("exec -T db test -s /backups/pre-update-" in call for call in calls)
        # Both release images are pulled directly before host state changes; no Compose
        # pull runs after the producer proof is swapped.
        assert not any("bundled pull" in call for call in calls)
        assert f"{LATEST_VERSION}|bundled up -d" in calls
        assert any("health/readiness/" in call for call in calls)
        assert calls.index(f"{LATEST_VERSION}|init-host") < calls.index(f"{LATEST_VERSION}|bundled up -d")
        assert "updates" not in (tmp_path / ".env").read_text()
        assert "payments" in (tmp_path / ".env").read_text()
        assert f"Update complete: {LATEST_VERSION}." in completed.stdout
    else:
        assert f"{LATEST_VERSION} is already installed." in completed.stdout
        assert calls == []
        assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("failure", ["backup", "deploy"])
def test_failure_logs_without_update_control_and_keeps_previous_version(tmp_path, failure):
    completed, calls = _run_update(tmp_path, PREVIOUS_VERSION, failure=failure)

    assert completed.returncode != 0
    assert (tmp_path / ".spaceworks-version").read_text().strip() == PREVIOUS_VERSION
    if failure == "deploy":
        assert f"{PREVIOUS_VERSION}|bundled up -d --no-deps backend worker beat frontend" in calls
        # The previous producer proof is saved before init swaps it and moved back on rollback;
        # it is never regenerated by the previous image's installer.
        save = next(i for i, call in enumerate(calls) if "cp -p /p/producer-capability.json" in call)
        assert save < calls.index(f"{LATEST_VERSION}|init-host")
        assert any("mv -f /p/.producer-capability.previous" in call for call in calls[save:])
        assert not any("producer-proof" in call for call in calls)
        assert f"Rollback complete: {PREVIOUS_VERSION} is healthy." in completed.stdout
        assert "The database backup was retained." in completed.stdout
    else:
        assert "Host update failed. Check the terminal output or Actions job log." in completed.stdout
        assert not any("bundled pull" in call or call.endswith("bundled up -d") for call in calls)


def test_upgrade_retains_tls_layer_for_later_runner_updates(tmp_path):
    completed, _ = _run_update(tmp_path, PREVIOUS_VERSION, layer="tls")
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / ".spaceworks-layer").read_text().strip() == "tls"


def test_an_installer_pinned_release_wins_over_a_newer_latest(tmp_path):
    # The installer staged this release's host files; a release published meanwhile must not
    # pair those files with newer images.
    pinned = "1.2.3-main.40.0000000000aa"
    completed, calls = _run_update(tmp_path, PREVIOUS_VERSION, pinned=f"v{pinned}")

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / ".spaceworks-version").read_text().strip() == pinned
    assert f"{pinned}|bundled up -d" in calls
    assert not any(LATEST_VERSION in call for call in calls)
