"""Check-in setup must fail closed and retain the full hardware handover lifecycle."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)
FORCE_ON = "reports,telegram,guest_handover,machines,machine_service,printing,maintenance"


@pytest.fixture
def checkin_shell(tmp_path):
    """Record management calls without Docker, and fail only the checked-in call on demand."""
    stub = tmp_path / "compose-stub.sh"
    stub.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$COMPOSE_CALLS"\n'
        'if [[ "$FAIL_CHECKIN" == 1 && " $* " == *" --mode checked_in "* ]]; then\n'
        '  exit 9\nfi\n', encoding="utf-8",
    )
    stub.chmod(0o755)

    def run(script, input_text="", **environment):
        # Inputs live in stdin/env, never in shell program text, including unsafe purposes.
        return subprocess.run(
            [shutil.which("bash") or "bash", "-c",
             'source "$1"; source "$2"; '
             'exec 0<<< "$CHECKIN_TEST_INPUT"; '
             'warn() { printf "%s\\n" "$*" >&2; }; '
             'COMPOSE=(bash "$COMPOSE_STUB" bundled); ' + script,
             "checkin-test", (ROOT / "scripts/env-file.sh").as_posix(),
             (ROOT / "scripts/request-access-selection.sh").as_posix()],
            cwd=tmp_path,
            env={**os.environ, "BASH_ENV": "", "MSPROFILE": "recommended",
                 "REQUEST_ACCESS": "accounts", "FAIL_CHECKIN": "0",
                 "COMPOSE_STUB": stub.as_posix(),
                 "COMPOSE_CALLS": (tmp_path / "compose-calls.txt").as_posix(),
                 "CHECKIN_TEST_INPUT": input_text,
                 **environment},
            capture_output=True, text=True, timeout=10,
        )

    return run


def _ask(checkin_shell, url="https://checkin.example.org/api/roster", space_id="42",
         purpose="Working on a project"):
    return checkin_shell(
        'ask_request_access; printf "RESULT:%s|%s|%s|%s|%s\\n" '
        '"$REQUEST_ACCESS" "$MSPROFILE" "$CHECKIN_URL_INPUT" '
        '"$CHECKIN_SPACE_ID_INPUT" "$CHECKIN_PURPOSE_INPUT"',
        input_text=f"4\n{url}\n{space_id}\n{purpose}\n",
    )


@pytest.mark.parametrize("space_id", ["1", "42", "2147483647"])
def test_choice_four_selects_checkin_profile(checkin_shell, space_id):
    """Valid roster settings must reach the checked_in mode and its install profile."""
    result = _ask(checkin_shell, space_id=space_id)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == (
        "RESULT:checked_in|checkin|https://checkin.example.org/api/roster|"
        f"{space_id}|Working on a project"
    )


@pytest.mark.parametrize(
    ("url", "space_id", "purpose"),
    [
        ("not-a-url", "42", "safe"),
        ("ftp://checkin.example.org/roster", "42", "safe"),
        ("https://checkin.example.org/a b", "42", "safe"),
        ("https://checkin.example.org/roster", "0", "safe"),
        ("https://checkin.example.org/roster", "2147483648", "safe"),
        ("https://checkin.example.org/roster", "42", "$unsafe"),
        ("https://checkin.example.org/roster", "42", "unsafe#comment"),
    ],
)
def test_invalid_checkin_inputs_keep_account_gate_and_profile(checkin_shell, url, space_id, purpose):
    """Bad settings must not leave anonymous requests enabled or switch the install profile."""
    result = _ask(checkin_shell, url, space_id, purpose)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "RESULT:accounts|recommended|||"
    assert "Falling back" in result.stderr


def test_whitespace_only_purpose_uses_the_default(checkin_shell):
    """An operator accepting the purpose prompt must get the upstream eligibility default."""
    result = _ask(checkin_shell, purpose=" \t ")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1].endswith("|42|Working on a project")
    assert "RESULT:checked_in|checkin|" in result.stdout


def test_persist_checkin_settings_writes_once_in_current_directory(checkin_shell, tmp_path):
    """Repeated setup must append literal roster settings without duplicating or replacing them."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("EXISTING=keep\n", encoding="utf-8")
    result = checkin_shell(
        'persist_checkin_settings; CHECKIN_URL_INPUT=https://replacement.example.org; '
        'CHECKIN_PURPOSE_INPUT=replacement; persist_checkin_settings',
        REQUEST_ACCESS="checked_in", CHECKIN_URL_INPUT="https://checkin.example.org/roster",
        CHECKIN_PURPOSE_INPUT="Working on a project",
    )
    assert result.returncode == 0, result.stderr
    assert dotenv.read_text() == (
        "EXISTING=keep\nCHECKIN_API_URL=https://checkin.example.org/roster\n"
        "CHECKIN_REQUIRED_PURPOSE=Working on a project\n"
    )


@pytest.mark.parametrize("existing", [False, True])
def test_accounts_mode_does_not_persist_checkin_settings(checkin_shell, tmp_path, existing):
    """The account-only path must not create or alter unrelated roster configuration."""
    dotenv = tmp_path / ".env"
    if existing:
        dotenv.write_bytes(b"EXISTING=keep")
    result = checkin_shell("persist_checkin_settings", REQUEST_ACCESS="accounts")
    assert result.returncode == 0, result.stderr
    if existing:
        assert dotenv.read_bytes() == b"EXISTING=keep"
    else:
        assert not dotenv.exists()


def test_checked_in_module_selection_uses_registered_lifecycle_modules(checkin_shell):
    """The wizard's module defaults must exist in the backend and exclude membership gating."""
    from apps.makerspaces.module_registry import MODULE_KEYS

    result = checkin_shell(
        'change_modules() { printf "%s\\n%s\\n" "$MODULE_FORCE_ON" "$MODULE_FORCE_OFF"; }; '
        'choose_modules', REQUEST_ACCESS="checked_in",
    )
    assert result.returncode == 0, result.stderr
    enabled, disabled = result.stdout.splitlines()
    assert enabled == FORCE_ON
    assert disabled == "membership"
    assert set(enabled.split(",")) <= set(MODULE_KEYS)


@pytest.mark.parametrize("fail", [False, True], ids=["success", "fallback-to-accounts"])
def test_apply_checked_in_passes_space_id_and_fails_closed(checkin_shell, tmp_path, fail):
    """A rejected roster policy must retry accounts through the same management role."""
    result = checkin_shell(
        'apply_request_access "$SLUG"', REQUEST_ACCESS="checked_in",
        CHECKIN_SPACE_ID_INPUT="42", SLUG="test-space", FAIL_CHECKIN="1" if fail else "0",
    )
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "compose-calls.txt").read_text().splitlines()
    prefix = ("bundled run --rm --no-deps -T backend --role management "
              "python manage.py set_request_access --makerspace test-space")
    expected = [prefix + " --mode checked_in --checkin-space-id 42"]
    if fail:
        expected.append(prefix + " --mode accounts")
        assert "Borrow requests will require an account" in result.stderr
    assert calls == expected
