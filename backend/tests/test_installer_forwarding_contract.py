"""Static installer guards avoid running its privileged and interactive preflight."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)


def test_installer_validates_fork_repository_without_sourcing_repo_files():
    """The curl entrypoint must validate owner/repo before downloading any executable content."""
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assignment = 'REPOSITORY="${SPACEWORKS_REPOSITORY:-SpaceWorks-HQ/SpaceWorks}"'
    validation = '[[ "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die'
    assert assignment in source
    assert validation in source
    assert source.index(assignment) < source.index(validation) < source.index("RELEASE_API=")
    # Existing installs may use their already installed parsers; no downloaded code is sourced.
    sourced = re.findall(r"^\s*(?:source|\.)\s+([^\n]+)$", source, flags=re.MULTILINE)
    assert sourced == ["/etc/os-release"]
    # The installed (not downloaded) parsers resolve the repository, under the chosen privileges.
    assert ("source \"$1/scripts/env-file.sh\"; source \"$1/scripts/host-image.sh\"; "
            "resolve_spaceworks_repository \"$1\"' _ \"$INSTALL_DIR\"") in source
    assert source.index("RUN_INSTALLED_AS_ROOT=1") < source.index("resolve_spaceworks_repository")


def test_installer_release_preflight_and_quoted_forwarding():
    """Updates stage the release; setup must preserve literal image overrides."""
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    start = source.index('if [[ "$ACTION" != modules && "$ACTION" != runner ]]; then\n  release_json=')
    end = source.index('say "All preflight checks passed;', start)
    preflight = source[start:end]
    assert source.count("release_json=") == 1
    assert source.count('"$RELEASE_API"') == 1
    assert preflight.rstrip().endswith("fi")
    forwarding = preflight.split("for name in ", 1)[1].split("\n  done", 1)[0]
    names = forwarding.split("; do", 1)[0].split()
    assert set(names) == {
        "MAKERSPACE_IMAGE_TAG", "SPACEWORKS_REPOSITORY", "MAKERSPACE_BACKEND_IMAGE",
        "MAKERSPACE_FRONTEND_IMAGE",
    }
    newline_guard = '[[ "$value" != *$\'\\r\'* && "$value" != *$\'\\n\'* ]] || die'
    quote = "printf -v assignment '%s=%q ' \"$name\" \"$value\""
    assert newline_guard in forwarding
    assert quote in forwarding
    assert forwarding.index(newline_guard) < forwarding.index(quote)
    assert 'setup_command+="$assignment"' in forwarding
    assert 'run_installed "$setup_command"' in source


def test_existing_install_drops_the_shell_repository_override():
    """update.sh gives a shell override precedence over .env, so it must not leak into it."""
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    existing = source.split('if [[ -f "$INSTALL_DIR/.spaceworks-version" ]]; then', 1)[1]
    existing = existing.split("\n", 2)[1]
    assert "unset SPACEWORKS_REPOSITORY" in existing


def test_installer_requires_the_request_access_helper_in_the_release():
    """Setup sources this helper, so a partial release must fail before installing the archive."""
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    required = source.split("for required in ", 1)[1].split("; do", 1)[0]
    required = required.replace("\\\n", "").split()
    assert "setup.sh" in required
    assert "scripts/request-access-selection.sh" in required
    assert "scripts/install-deploy-runner.sh" in required
    assert "scripts/setup-deploy-runner.sh" in required


def test_installer_reads_the_private_stage_dir_only_as_root():
    """Under sudo the stage is a root-owned 0700 mktemp dir; unprivileged reads cannot
    traverse it, so every check fails until the post-mv chown.
    """
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    start = source.index('STAGE_DIR="$("${RUN_ROOT[@]}" mktemp -d')
    end = source.index('\nSTAGE_DIR=""', start)
    block = source[start:end]
    assert 'chmod 755 "$STAGE_DIR"' in block
    for line in block.splitlines():
        if "$STAGE_DIR" in line and ("test -f" in line or "chmod" in line or "mv --" in line):
            assert '"${RUN_ROOT[@]}"' in line, line
    assert '"${RUN_ROOT[@]}" test -f "$STAGE_DIR/$required"' in block


@pytest.mark.parametrize("name", [
    "install.sh", "setup.sh", "scripts/request-access-selection.sh",
    "scripts/env-file.sh", "scripts/host-image.sh",
    "scripts/install-deploy-runner.sh", "scripts/setup-deploy-runner.sh",
])
def test_install_entrypoints_and_helpers_stay_modular(name):
    """Keep host setup small enough that validation and privileged transitions remain reviewable."""
    assert len((ROOT / name).read_text(encoding="utf-8").splitlines()) <= 300


def test_existing_install_runs_new_release_updater_before_adopting_host_files():
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert '"$STAGE_DIR/scripts/update.sh"' in source
    assert "SPACEWORKS_UPDATE_INSTALL_DIR=%q" in source
    assert source.index('tar -xzf') < source.index('printf -v update_command')
    update = (ROOT / "scripts/update.sh").read_text(encoding="utf-8")
    assert update.index("pg_dump") < update.index('install_staged_host_bundle "')
    assert update.index('install_staged_host_bundle "') < update.index('bash "$ROOT/scripts/init-host-orchestration.sh"')
