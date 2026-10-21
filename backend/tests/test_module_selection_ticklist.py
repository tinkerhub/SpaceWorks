"""The setup/update module tick list (scripts/module-selection.sh) without Docker.

It must name every requirement it pulls in and the borrow-request consequence of the
membership switch BEFORE anything is applied, never offer a module the deployment does
not ship, and report a failed apply as a failure.
"""

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

LISTING = """Modules for lab:
  * public_inventory   Public browse catalogue and item detail. (core)
  - reports            Analytics, report registry and CSV/XLSX exports.
  {membership_mark} membership         Join requests, referrals, verification and profiles.
  - events             Event scheduling and registrations. [requires membership]
  + payments           Online payment for machine jobs, bookings, events and dues.
  x procurement        To-buy list and procurement tracking. (not shipped by this deployment)

  * core (always on)   + installed   - available   x not shipped by this deployment
"""


@pytest.fixture
def ticklist(tmp_path):
    stub = tmp_path / "compose-stub.sh"
    stub.write_text(
        "#!/bin/bash\n"
        'if [[ " $* " == *" list_modules "* ]]; then cat "$LISTING_FILE"; exit 0; fi\n'
        'printf "CALL %s\\n" "$*" >> "$LOG"\n'
        'for key in $FAIL_KEYS; do [[ " $* " == *" $key "* ]] && { echo "refused $key"; exit 1; }; done\n'
        "exit 0\n",
        encoding="utf-8",
    )
    log = tmp_path / "log.txt"

    def run(script, *, membership_installed=False, input_text="", **environment):
        listing = tmp_path / "listing.txt"
        listing.write_text(
            LISTING.format(membership_mark="+" if membership_installed else "-"), encoding="utf-8"
        )
        result = subprocess.run(
            [shutil.which("bash") or "bash", "-c",
             'say() { printf "SAY %s\\n" "$*" >> "$LOG"; printf "%s\\n" "$*"; }; '
             'warn() { printf "WARN %s\\n" "$*" >> "$LOG"; printf "%s\\n" "$*"; }; '
             'source "$1"; source "$2"; exec 0<<< "$TICK_INPUT"; '
             'COMPOSE=(bash "$COMPOSE_STUB" bundled); ' + script,
             "ticklist-test", (ROOT / "scripts/module-selection.sh").as_posix(),
             (ROOT / "scripts/request-access-selection.sh").as_posix()],
            cwd=tmp_path,
            env={**os.environ, "BASH_ENV": "", "COMPOSE_STUB": stub.as_posix(),
                 "LISTING_FILE": listing.as_posix(), "LOG": log.as_posix(),
                 "TICK_INPUT": input_text, "FAIL_KEYS": "", "MODULE_MODE": "interactive",
                 "MODULE_INTERACTIVE": "1", "MODULE_FORCE_ON": "", "MODULE_FORCE_OFF": "",
                 "STRIPE_SECRET_KEY": "", **environment},
            capture_output=True, text=True, timeout=20,
        )
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return result, lines

    return run


def _first(lines, prefix):
    return next(index for index, line in enumerate(lines) if line.startswith(prefix))


def test_pulled_in_requirement_and_membership_consequence_print_before_apply(ticklist):
    # Rows: 1 reports, 2 membership, 3 events, 4 payments. Tick events only.
    result, lines = ticklist("module_change_one lab", input_text="3\n\n")

    assert result.returncode == 0, result.stdout + result.stderr
    pulled = _first(lines, "SAY events requires membership, so membership will be enabled too.")
    consequence = _first(lines, "WARN membership ON: only active members of lab")
    first_call = _first(lines, "CALL ")
    assert pulled < first_call and consequence < first_call
    calls = [line for line in lines if line.startswith("CALL ")]
    assert any("install_module events --makerspace lab" in call for call in calls)
    assert any("install_module membership --makerspace lab" in call for call in calls)


def test_turning_membership_off_states_the_borrow_consequence_first(ticklist):
    result, lines = ticklist(
        "module_change_one lab", membership_installed=True, input_text="\nlab\n",
        MODULE_FORCE_OFF="membership",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    consequence = _first(lines, "WARN membership OFF: anyone with a signed-in account")
    assert consequence < _first(lines, "CALL ")
    assert any("uninstall_module membership" in line for line in lines)


def test_modules_the_deployment_does_not_ship_are_never_offered(ticklist):
    interactive, _ = ticklist("module_change_one lab", input_text="\n")
    everything, lines = ticklist("module_change_one lab", MODULE_MODE="all", MODULE_INTERACTIVE="0")

    assert interactive.returncode == everything.returncode == 0
    assert "procurement" not in interactive.stdout
    assert "reports" in interactive.stdout
    assert not any("procurement" in line for line in lines if line.startswith("CALL "))


def test_a_failed_apply_is_reported_as_a_failure(ticklist):
    result, lines = ticklist(
        "module_change_one lab", MODULE_MODE="all", MODULE_INTERACTIVE="0", FAIL_KEYS="reports",
    )

    assert result.returncode == 1
    assert any(line.startswith("WARN Could not install reports for lab") for line in lines)


@pytest.mark.parametrize("stripe_key", ["sk_test_123", ""], ids=["stripe-given", "no-stripe"])
def test_stripe_keys_offer_the_payments_module(ticklist, stripe_key):
    result, _ = ticklist(
        'change_modules() { printf "FORCE_ON:%s\\n" "$MODULE_FORCE_ON"; }; choose_modules',
        REQUEST_ACCESS="accounts", STRIPE_SECRET_KEY=stripe_key,
    )

    assert result.returncode == 0, result.stderr
    force_on = next(line for line in result.stdout.splitlines() if line.startswith("FORCE_ON:"))
    assert ("payments" in force_on.split(":", 1)[1].split(",")) is bool(stripe_key)


def test_setup_and_installer_exit_non_zero_when_module_selection_fails():
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    failure = setup.split("if ! choose_modules; then", 1)[1].split("fi", 1)[0]
    assert "MODULES_FAILED=1" in failure
    tail = setup.split("finish_deploy_runner_setup\n", 1)[1]
    assert 'if [[ "${MODULES_FAILED:-0}" == 1 ]]; then' in tail and "exit 3" in tail
    # The installer still writes the version marker for exit 3, then fails.
    marker = installer.index('> "$INSTALL_DIR/.spaceworks-version"')
    assert installer.index('|| exit "$setup_status"') < marker
    assert installer.index('[[ "$setup_status" == 0 ]] || die') > marker
