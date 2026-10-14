#!/usr/bin/env bash
# Sourced by setup.sh: the GitHub release webhook that replaced the in-app updater.

# Asked before Compose records are taken: the receiver reads its secret from .env, so the
# secret must exist before the configuration digest and the containers are created.
ask_deploy_webhook() {
  local secret
  AUTOUPDATE=N
  [[ "$FIRST_RUN" == 1 ]] || return 0
  read -r -p "Enable automatic production updates from main? [Y/n]: " AUTOUPDATE
  AUTOUPDATE="${AUTOUPDATE:-Y}"
  # ^[Yy] not ^[Yy]$: typing "yes" at a [Y/n] prompt must not fall through to "off".
  [[ "$AUTOUPDATE" =~ ^[Yy] ]] || return 0
  secret="${SPACEWORKS_DEPLOY_WEBHOOK_SECRET:-}"
  if [[ -z "$secret" ]]; then
    if command -v openssl >/dev/null 2>&1; then secret="$(openssl rand -hex 32)"
    else secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"; fi
  fi
  env_file_append_if_absent .env SPACEWORKS_DEPLOY_WEBHOOK_SECRET "$secret" \
    || die "Could not persist SPACEWORKS_DEPLOY_WEBHOOK_SECRET in .env."
}

# Later deliveries run update.sh without the operator's shell, so remember the layer.
record_compose_layer() {
  local layer="${SPACEWORKS_COMPOSE_LAYER:-}"
  [[ -n "$layer" || "${SPACEWORKS_COMPOSE_BUILD_LAYER:-0}" != 1 ]] || layer=build
  [[ -n "$layer" ]] || return 0
  case "$layer" in
    none|build|tls|build-tls|saas|build-saas) printf '%s\n' "$layer" > "$ROOT/.spaceworks-layer" ;;
    *) die "Invalid Compose layer." ;;
  esac
}

finish_deploy_webhook_setup() {
  local host
  [[ "$AUTOUPDATE" =~ ^[Yy] ]] || return 0
  bash "$ROOT/scripts/install-deploy-webhook.sh" \
    || die "Host trigger installation failed; run bash scripts/install-deploy-webhook.sh before registering GitHub."
  host="$(env_file_get .env PUBLIC_DOMAIN)"
  [[ -n "$host" ]] || host="${WEBHOST:-$(env_file_get .env ALLOWED_HOSTS)}"
  host="${host%%,*}"
  printf '\nGitHub repository %s: Settings -> Webhooks -> Add webhook\n' "$(resolve_spaceworks_repository "$ROOT")"
  printf '  Payload URL: https://%s/hooks/deploy\n' "${host:-localhost}"
  printf '  Content type: application/json\n  Secret: SPACEWORKS_DEPLOY_WEBHOOK_SECRET from .env\n  Event: Releases only\n'
  printf 'GitHub must be able to reach this URL over HTTPS.\n'
}
