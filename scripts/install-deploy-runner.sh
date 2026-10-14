#!/usr/bin/env bash
# Run as the install owner; registration/removal tokens stay out of argv and files.
set +x
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/env-file.sh"
source "$ROOT/scripts/host-image.sh"
source "$ROOT/scripts/retire-update-polling.sh"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
# Ask for a one-time token on the terminal (hidden) when it was not passed in the environment.
prompt_token() {
  local variable="$1" kind="$2" endpoint="$3" value=""
  [[ -z "${!variable:-}" ]] || return 0
  { [[ -r /dev/tty ]] && : < /dev/tty; } 2>/dev/null || die "Set $variable to a fresh $kind token."
  printf 'Get a %s token (valid 1 hour), then paste it below. Either:\n' "$kind" > /dev/tty
  if [[ "$kind" == removal ]]; then
    printf '  GitHub: %s -> Settings -> Actions -> Runners -> this runner -> Remove (copy the --token value)\n' "$url" > /dev/tty
  else
    printf '  GitHub: %s -> Settings -> Actions -> Runners -> New self-hosted runner (copy the --token value)\n' "$url" > /dev/tty
  fi
  printf '  or on any machine with gh: gh api -X POST repos/%s/actions/runners/%s --jq .token\n' "$REPOSITORY" "$endpoint" > /dev/tty
  read -rs -p "Runner $kind token (hidden): " value < /dev/tty; printf '\n' > /dev/tty
  [[ -n "$value" ]] || die "No $kind token entered."
  printf -v "$variable" '%s' "$value"
}
case "${1:-}" in
  ""|--remove) ;;
  *) die 'Usage: bash scripts/install-deploy-runner.sh [--remove]' ;;
esac
[[ "$(id -u)" != 0 ]] || die 'Run as the install owner, not root.'
[[ "$(uname -s)" == Linux ]] || die 'The deployment runner requires Linux.'
case "$(uname -m)" in
  x86_64) arch=x64; digest=af4b794c1bc41d73d40535e3fe092a39f9679cd8d965954c2aca25a05ca41d32 ;;
  aarch64|arm64) arch=arm64; digest=628b4a7258487b80c1d3c221095a7ded349f5ae0175fd3dfab708d07428f041b ;;
  *) die 'The deployment runner supports Linux x64 or arm64 only.' ;;
esac
command -v systemctl >/dev/null 2>&1 && test -d /run/systemd/system \
  || die 'The deployment runner requires running systemd.'
command -v sudo >/dev/null 2>&1 || die 'sudo is required to manage the runner service.'
REPOSITORY="$(resolve_spaceworks_repository "$ROOT")"
owner="$(id -un)"
runner_dir="$HOME/spaceworks-actions-runner"
url="https://github.com/$REPOSITORY"

if [[ "${1:-}" == --remove ]]; then
  prompt_token RUNNER_REMOVE_TOKEN removal remove-token
  token="$RUNNER_REMOVE_TOKEN"
  unset RUNNER_REMOVE_TOKEN RUNNER_TOKEN
  [[ -f "$runner_dir/.runner" ]] || die 'No configured deployment runner to remove.'
  cd "$runner_dir"
  if [[ -f .service ]]; then sudo ./svc.sh stop; sudo ./svc.sh uninstall; fi
  ACTIONS_RUNNER_INPUT_TOKEN="$token" ./config.sh remove --unattended >/dev/null 2>&1 \
    || die 'Runner removal failed; obtain a fresh removal token and retry.'
  unset token
  # The directory is installer-owned; deleting it lets a later install start clean.
  cd "$HOME"
  rm -rf -- "$runner_dir"
  echo 'Deployment runner removed. Set the repository variable SPACEWORKS_DEPLOY_RUNNER=false.'
  exit 0
fi

echo 'Public repository warning: review workflow changes before approving any fork PR workflow.'
echo 'Set Actions approval to Require approval for all outside collaborators.'
if command -v gh >/dev/null 2>&1; then
  if policy="$(gh api "repos/$REPOSITORY/actions/permissions/fork-pr-contributor-approval" --jq .approval_policy 2>/dev/null)"; then
    [[ "$policy" == all_external_contributors || "${SPACEWORKS_RUNNER_ACCEPT_RISK:-0}" == 1 ]] \
      || die 'Fork PR approval policy must be all_external_contributors; SPACEWORKS_RUNNER_ACCEPT_RISK=1 overrides this risk check.'
  else
    echo 'WARNING: Could not verify fork PR approval policy; check it in GitHub before approving workflows.' >&2
  fi
else
  echo 'WARNING: gh is unavailable; verify the fork PR approval policy in GitHub.' >&2
fi

configured=0
if [[ -f "$runner_dir/.runner" ]]; then
  existing_url="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["gitHubUrl"])' "$runner_dir/.runner")" \
    || die 'Cannot read the existing runner repository.'
  [[ "${existing_url,,}" == "${url,,}" ]] || die 'The existing runner belongs to another repository.'
  configured=1
else
  prompt_token RUNNER_TOKEN registration registration-token
  token="$RUNNER_TOKEN"
  unset RUNNER_TOKEN RUNNER_REMOVE_TOKEN
  [[ ! -d "$runner_dir" || -z "$(ls -A "$runner_dir")" ]] \
    || die 'Runner directory is not empty; refusing to extract over an existing install.'
  temporary="$(mktemp -d)"
  trap 'rm -rf -- "$temporary"' EXIT
  archive="actions-runner-linux-$arch-2.338.0.tar.gz"
  curl --fail --location --silent --show-error \
    "https://github.com/actions/runner/releases/download/v2.338.0/$archive" -o "$temporary/$archive"
  printf '%s  %s\n' "$digest" "$temporary/$archive" | sha256sum --check --status \
    || die 'Runner checksum mismatch; nothing was extracted.'
  mkdir -p "$runner_dir"
  # This run owns the (empty) directory now: if registration never completes (no .runner),
  # remove it so a retry with a fresh token is not refused as "not empty".
  trap 'rm -rf -- "$temporary"; [[ -f "$runner_dir/.runner" ]] || rm -rf -- "$runner_dir"' EXIT
  tar -xzf "$temporary/$archive" -C "$runner_dir"
  cd "$runner_dir"
  # GitHub's own helper installs the runner's OS libraries (e.g. ICU) a minimal host may lack.
  sudo ./bin/installdependencies.sh >/dev/null || die 'Could not install the runner OS dependencies.'
  # Show why registration failed (bad token vs missing library), with the token redacted.
  if ! errors="$(ACTIONS_RUNNER_INPUT_TOKEN="$token" ./config.sh --unattended --url "$url" \
    --name "spaceworks-$(hostname)" --labels spaceworks-prod --replace 2>&1 >/dev/null)"; then
    printf '%s\n' "${errors//"$token"/[redacted]}" >&2
    die 'Runner registration failed; obtain a fresh token and retry.'
  fi
  unset token
fi
unset RUNNER_TOKEN RUNNER_REMOVE_TOKEN ACTIONS_RUNNER_INPUT_TOKEN
cd "$runner_dir"
# Preserve runner-managed environment entries while replacing only the install path.
env_value_is_safe "$ROOT" || die 'Install path cannot be represented safely in the runner environment.'
environment="$(mktemp "$runner_dir/.env.XXXXXX")"
if [[ -f .env ]]; then awk '!/^SPACEWORKS_INSTALL_DIR=/' .env > "$environment"; fi
printf 'SPACEWORKS_INSTALL_DIR=%s\n' "$ROOT" >> "$environment"
chmod 600 "$environment"
mv -f -- "$environment" .env
if [[ ! -f .service ]]; then sudo ./svc.sh install "$owner"; fi
if [[ "$configured" == 1 ]]; then sudo ./svc.sh stop; fi
retire_update_polling
sudo ./svc.sh start
printf 'Runner ready for %s as %s.\n' "$REPOSITORY" "$owner"
printf 'Enable deployments: gh variable set SPACEWORKS_DEPLOY_RUNNER --body true --repo %s\n' "$REPOSITORY"
echo 'Confirm Settings -> Actions -> Require approval for all outside collaborators.'
