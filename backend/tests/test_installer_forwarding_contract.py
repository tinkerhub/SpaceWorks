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
    # The only trusted sourced data is OS metadata; repo helpers are not safe here.
    sourced = re.findall(r"^\s*(?:source|\.)\s+([^\n]+)$", source, flags=re.MULTILINE)
    assert sourced == ["/etc/os-release"]


def test_installer_release_preflight_and_quoted_forwarding_are_fresh_only():
    """Existing installs use their own updater; fresh installs must preserve literal overrides."""
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    start = source.index('if [[ "$ACTION" == fresh ]]; then\n  release_json=')
    end = source.index('say "All preflight checks passed;', start)
    preflight = source[start:end]
    assert source.count("release_json=") == 1
    assert source.count('"$RELEASE_API"') == 1
    assert preflight.rstrip().endswith("fi")
    forwarding = preflight.split("for name in ", 1)[1].split("\n  done", 1)[0]
    names = forwarding.split("; do", 1)[0].split()
    assert set(names) == {
        "MAKERSPACE_IMAGE_TAG", "SPACEWORKS_REPOSITORY", "MAKERSPACE_BACKEND_IMAGE",
        "MAKERSPACE_FRONTEND_IMAGE", "SPACEWORKS_UPDATE_SCHEDULE",
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
    required = source.split('[[ -f "$STAGE_DIR/setup.sh"', 1)[1].split(
        '|| die "The pinned release archive is missing required installer files."', 1
    )[0]
    assert '-f "$STAGE_DIR/scripts/request-access-selection.sh"' in required


@pytest.mark.parametrize("name", [
    "install.sh", "setup.sh", "scripts/request-access-selection.sh",
    "scripts/env-file.sh", "scripts/host-image.sh",
])
def test_install_entrypoints_and_helpers_stay_modular(name):
    """Keep host setup small enough that validation and privileged transitions remain reviewable."""
    assert len((ROOT / name).read_text(encoding="utf-8").splitlines()) <= 300
