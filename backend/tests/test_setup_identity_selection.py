"""Exercise installer identity prompts without starting setup, Docker or services."""

import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
HELPERS = ("scripts/env-file.sh", "scripts/request-access-selection.sh")

# Private answers travel only through stdin/environment. The shell emits booleans,
# lengths and read target/options, never credentials or captured helper output.
PROBE = r'''
set -euo pipefail
source "$1"
source "$2"
trap 'rm -f "$OUTPUT"' EXIT
: > "$READ_TRACE"; : > "$RAND_CALLS"
warn() { printf '%s\n' "$*" >&2; }
say() { printf '%s\n' "$*"; }
rand_key() {
  [[ $# == 1 && "$1" == 16 ]] || return 94
  printf '16\n' >> "$RAND_CALLS"
  printf '%s' "$EXPECTED_PASSWORD"
}
read() {
  local option silent=0
  for option in "$@"; do
    [[ "$option" != -*s* ]] || silent=1
  done
  printf '%s:%s\n' "${@: -1}" "$silent" >> "$READ_TRACE"
  builtin read "$@"
}
flag() {
  local label="$1"; shift
  if "$@"; then printf '%s=1\n' "$label"; else printf '%s=0\n' "$label"; fi
}
contains() { [[ "$output" == *"$1"* ]]; }
private_output() { [[ "$output" != *"$EXPECTED_PASSWORD"* ]]; }
{
  if [[ "$ACTION" == existing ]]; then
    source "$INITIAL_BRANCH"
  else
    if [[ "$ACTION" == chain ]]; then ask_request_access; fi
    ask_setup_identity
  fi
} > "$OUTPUT" 2>&1
output="$(<"$OUTPUT")"
builtin read -r sentinel
flag sentinel test "$sentinel" = SENTINEL
if builtin read -r extra; then printf 'exhausted=0\n'; else printf 'exhausted=1\n'; fi
flag username test "$ADMINUSER" = "$EXPECTED_USER"
flag email test "$ADMINEMAIL" = "$EXPECTED_EMAIL"
flag password test "$ADMINPASS" = "$EXPECTED_PASSWORD"
flag google test "$GOOGLE_WEB_CLIENT_ID" = "$EXPECTED_GOOGLE"
flag generated test "$GEN_PASS" = "$EXPECTED_GEN"
flag random test "$(<"$RAND_CALLS")" = "$EXPECTED_RAND"
flag private private_output
flag guidance contains 'Optional: Google sign-in'
flag origin contains 'http://workshop.example'
flag instructions contains 'https://console.cloud.google.com/apis/credentials'
flag suffix contains '.apps.googleusercontent.com'
flag skip contains 'Leave blank to skip'
flag warning contains 'That does not look like a Google client ID; skipping Google sign-in.'
printf 'length=%s\nfirst_run=%s\n' "${#ADMINPASS}" "${FIRST_RUN:-unset}"
if [[ "$ACTION" == chain ]]; then
  flag mode test "$REQUEST_ACCESS" = checked_in
  flag profile test "$MSPROFILE" = checkin
  flag roster test "$CHECKIN_URL_INPUT" = 'https://roster.example/api'
  flag space test "$CHECKIN_SPACE_ID_INPUT" = 42
  flag purpose test "$CHECKIN_PURPOSE_INPUT" = 'Working on a project'
fi
'''


@pytest.fixture
def identity_shell(tmp_path):
    def run(*, mode="checked_in", username="operator", email="", google="", generated=False,
            action="identity", initial=None):
        __tracebackhide__ = True  # Keep private stdin/env out of pytest's optional local-variable dump.
        expected_google = "" if mode == "checked_in" else "client.apps.googleusercontent.com"
        if not google.strip() or google == "invalid-client":
            expected_google = ""
        environment = {
            "PATH": os.environ.get("PATH", os.defpath), "BASH_ENV": "/dev/null", "LC_ALL": "C",
            "ACTION": action, "MSPROFILE": "recommended", "ADMINUSER": "untouched-user",
            "ADMINEMAIL": "stale@example.com", "GOOGLE_WEB_CLIENT_ID": "stale-google",
            "GEN_PASS": "9", "EXPECTED_GEN": "1" if generated else "0",
            "EXPECTED_RAND": "16" if generated else "", "EXPECTED_USER": username or "admin",
            "EXPECTED_EMAIL": "" if mode == "checked_in" else email or "admin@example.com",
            "EXPECTED_GOOGLE": expected_google, "EXPECTED_PASSWORD": secrets.token_hex(8),
            "OUTPUT": str(tmp_path / "private-output"), "READ_TRACE": str(tmp_path / "reads"),
            "RAND_CALLS": str(tmp_path / "random-calls"),
        }
        if mode is not None:
            environment["REQUEST_ACCESS"] = mode
        if mode != "checked_in":
            environment["WEBHOST"] = "workshop.example"
        answers = [username]
        if mode != "checked_in":
            answers.append(email)
        # Include shell metacharacters in typed passwords to catch script interpolation.
        if not generated:
            environment["EXPECTED_PASSWORD"] += '$(`false`); literal \\ password'
        answers.append("" if generated else environment["EXPECTED_PASSWORD"])
        if mode != "checked_in":
            answers.append(google)
        if action == "chain":
            answers = ["4", "https://roster.example/api", "42", "  \t ", *answers]
        if action == "existing":
            environment.update(
                INITIAL_BRANCH=str(initial), ADMINPASS=environment["EXPECTED_PASSWORD"],
                EXPECTED_USER="untouched-user", EXPECTED_EMAIL="stale@example.com",
                EXPECTED_GOOGLE="stale-google", EXPECTED_GEN="9", EXPECTED_RAND="",
            )
            answers = []
        result = subprocess.run(
            [shutil.which("bash") or "bash", "-c", PROBE, "identity-test",
             *(str(ROOT / path) for path in HELPERS)],
            input="\n".join([*answers, "SENTINEL", ""]), env=environment, cwd=tmp_path,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
        assert result.returncode == 0, "isolated bash probe failed; private output suppressed"
        facts = dict(line.split("=", 1) for line in result.stdout.splitlines())
        for name in ("sentinel", "exhausted", "username", "email", "password", "google",
                     "generated", "random", "private"):
            assert facts[name] == "1", name
        assert facts["length"] == str(len(environment["EXPECTED_PASSWORD"]))
        return facts, (tmp_path / "reads").read_text().splitlines()

    return run


@pytest.mark.parametrize("username", ["", "front-desk"])
@pytest.mark.parametrize("generated", [False, True], ids=["typed", "generated-16"])
def test_checked_in_only_reads_username_and_silent_password(identity_shell, username, generated):
    """Stale email/OAuth values clear; WEBHOST stays unset and the next answer survives."""
    facts, reads = identity_shell(username=username, generated=generated)
    assert reads == ["ADMINUSER:0", "ADMINPASS:1"]
    assert all(facts[key] == "0" for key in
               ("guidance", "origin", "instructions", "suffix", "skip", "warning"))
    if generated:
        assert facts["length"] == "16"


def test_actual_choice_four_chains_roster_selection_into_identity(identity_shell):
    facts, reads = identity_shell(action="chain")
    assert reads == ["REQUEST_ACCESS_CHOICE:0", "url:0", "space_id:0", "purpose:0",
                     "ADMINUSER:0", "ADMINPASS:1"]
    assert all(facts[key] == "1" for key in ("mode", "profile", "roster", "space", "purpose"))
    assert all(facts[key] == "0" for key in
               ("guidance", "origin", "instructions", "suffix", "skip", "warning"))


@pytest.mark.parametrize("mode", ["accounts", "members", "anyone", None],
                         ids=["accounts", "members", "anyone", "unset-fallback"])
@pytest.mark.parametrize("custom", [False, True], ids=["defaults", "custom"])
@pytest.mark.parametrize("generated", [False, True], ids=["typed", "generated-16"])
@pytest.mark.parametrize("google", ["", " \tclient .apps.googleusercontent.com \t", "invalid-client"],
                         ids=["skip-google", "normalize-google", "reject-google"])
def test_other_modes_keep_original_four_prompt_contract(identity_shell, mode, custom, generated, google):
    facts, reads = identity_shell(
        mode=mode, username="custom-admin" if custom else "",
        email="staff@example.org" if custom else "", google=google, generated=generated,
    )
    assert reads == ["ADMINUSER:0", "ADMINEMAIL:0", "ADMINPASS:1", "GOOGLE_WEB_CLIENT_ID:0"]
    assert all(facts[key] == "1" for key in
               ("guidance", "origin", "instructions", "suffix", "skip"))
    assert facts["warning"] == ("1" if google == "invalid-client" else "0")


def _initial_setup_block():
    source = (ROOT / "setup.sh").read_text()
    start = source.index("FIRST_RUN=0\nif [ -f .env ]; then\n")
    end = source.index("\n# Older .env files", start)
    block = source[start:end]
    assert block.endswith("\nfi")
    return source, start, end, block


def test_identity_call_is_only_in_first_run_immediately_after_access_selection():
    source, start, end, block = _initial_setup_block()
    existing, first_run = block.split("\nelse\n", 1)
    calls = re.findall(r"^\s*ask_setup_identity\s*$", source, re.MULTILINE)
    assert len(calls) == 1
    assert "ask_setup_identity" not in source[:start] + existing + source[end:]
    assert "  ask_request_access\n  ask_setup_identity\n" in first_run
    assert first_run.index("FIRST_RUN=1") < first_run.index("ask_request_access")


def test_existing_env_executes_actual_initial_branch_without_new_identity_state(identity_shell, tmp_path):
    _, _, _, block = _initial_setup_block()
    initial = tmp_path / "initial-branch.sh"
    initial.write_text(block + "\n")
    dotenv = tmp_path / ".env"
    original = b"EXISTING=keep\nCHECKIN_API_URL=https://saved.example/roster\n"
    dotenv.write_bytes(original)
    facts, reads = identity_shell(action="existing", initial=initial)
    assert facts["first_run"] == "0"
    assert reads == []
    assert dotenv.read_bytes() == original


def test_setup_preserves_empty_email_google_guard_and_final_password_delivery():
    source = (ROOT / "setup.sh").read_text()
    assert '--username "$ADMINUSER" --email "$ADMINEMAIL" --password "$ADMINPASS"' in source
    google = source.index('  if [ -n "$GOOGLE_WEB_CLIENT_ID" ]; then\n')
    configure = source.index("python manage.py configure_social_auth", google)
    assert google < configure < source.index("\n  fi", configure)
    assert '--google-web-client-id "$GOOGLE_WEB_CLIENT_ID"' in source[google:configure + 180]
    delivery = '[ "$GEN_PASS" = 1 ] && warn "  Generated admin password: ${ADMINPASS}   (save this now)"'
    assert source.count(delivery) == 1
    assert source.index('echo   "  Staff console') < source.index(delivery)
    assert source.index(delivery) < source.index('echo   "Next: log into')
    helper = (ROOT / HELPERS[1]).read_text()
    identity = helper.split("ask_setup_identity() {\n", 1)[1].split("\nask_checkin_settings()", 1)[0]
    assert "Generated admin password" not in identity
    assert not re.search(r"\b(?:2fa|totp|otp|two_factor|manage\.py|COMPOSE)\b", identity, re.I)


def test_installer_requires_and_sources_the_actual_identity_helper():
    source = (ROOT / "install.sh").read_text()
    declarations = re.findall(r"^required_files=\(([^)]*)\)\n", source, re.MULTILINE)
    assert len(declarations) == 1
    assert re.fullmatch(r"[A-Za-z0-9_./\s-]+", declarations[0])
    assert {"setup.sh", HELPERS[1]} <= set(declarations[0].split())
    setup = (ROOT / "setup.sh").read_text()
    assert setup.count(f'source "$ROOT/{HELPERS[1]}"') == 1
    assert setup.index(f'source "$ROOT/{HELPERS[1]}"') < setup.index("ask_setup_identity\n")
    # Pinned restore-source metadata is reviewed/refreshed separately, never here.
    for path in ("setup.sh", *HELPERS):
        assert len((ROOT / path).read_text().splitlines()) <= 300


@pytest.mark.parametrize("path", ("setup.sh", *HELPERS))
def test_actual_shared_shell_sources_parse(path):
    result = subprocess.run(
        [shutil.which("bash") or "bash", "-n", str(ROOT / path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
    )
    assert result.returncode == 0, "shared shell source failed bash -n"
