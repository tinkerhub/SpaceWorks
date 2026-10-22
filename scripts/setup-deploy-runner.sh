#!/usr/bin/env bash
# Sourced by setup.sh; setup cannot mint a GitHub runner registration token.

ask_deploy_runner() {
  AUTOUPDATE=N
  [[ "$FIRST_RUN" == 1 ]] || return 0
  # Opt-in: it needs a systemd host and a runner token from the GitHub repository this
  # server deploys from, which most self-hosters (installing someone else's repo) lack.
  printf 'Automatic updates register this server as a GitHub Actions runner for YOUR fork.
'
  read -r -p "Enable automatic production updates from main? [y/N]: " AUTOUPDATE
  AUTOUPDATE="${AUTOUPDATE:-N}"
  # ^[Yy] not ^[Yy]$: typing "yes" must still count as "on".
}

# Later updates run without the operator's shell, so remember the Compose layer.
record_compose_layer() {
  local layer="${SPACEWORKS_COMPOSE_LAYER:-}"
  [[ -n "$layer" || "${SPACEWORKS_COMPOSE_BUILD_LAYER:-0}" != 1 ]] || layer=build
  [[ -n "$layer" ]] || return 0
  case "$layer" in
    none|build|tls|build-tls|saas|build-saas) printf '%s\n' "$layer" > "$ROOT/.spaceworks-layer" ;;
    *) die "Invalid Compose layer." ;;
  esac
}

# The app is already running here, so a runner problem warns instead of failing setup.
finish_deploy_runner_setup() {
  [[ "$AUTOUPDATE" =~ ^[Yy] ]] || return 0
  printf '\nSetting up automatic deploys: a GitHub Actions runner on this server.\n'
  if ! bash "$ROOT/scripts/install-deploy-runner.sh"; then
    printf 'WARNING: Automatic deploys are not set up yet. Fix the error above, then run: %s\n' \
      "bash scripts/install-deploy-runner.sh" >&2
  fi
}
