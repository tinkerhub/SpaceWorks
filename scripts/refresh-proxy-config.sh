#!/usr/bin/env bash
# Sourced by scripts/update.sh. Brings an installed deploy/Caddyfile* up to the release
# being deployed, without ever overwriting an operator's own edits.
#
# The TLS/SaaS overlays bind-mount these files into Caddy, and no image carries them, so
# before this an updated host kept its install-day proxy rules forever (a fresh install of
# the same release got the new ones). A file is replaced only when it is byte-identical to
# a version some release shipped -- i.e. nobody edited it. An edited file is kept and the
# release's version is written beside it as <file>.release, with a notice, for a manual merge.

PROXY_CONFIG_FILES=(deploy/Caddyfile deploy/Caddyfile.saas)
# sha256 of every deploy/Caddyfile and deploy/Caddyfile.saas any release has shipped.
# Append the new digest whenever either file changes (backend/tests/test_proxy_config_refresh.py
# fails until you do), or every unedited install would be treated as customised.
SHIPPED_PROXY_CONFIG_SHA256=(
  fcc680a758348fc60aa1cf5ed6ad4576c978562aa21b5d391f05320d2751df1f
  84d6878b8b9c1a22225d9e0136ec2c6f2711e5dd9b3e8238eeacd4f6e4542c83
  fa1a8d87883085a8ab1fa8d19cb1b15ccbdc500f24b6ee3bdc78854f9e30ceda
  879a1bb092735c8f8e497d60abe95ce2354752076d12b92ef3ff7754de3a6886
  18a18e7a52583ed5d4f595ef0bce17191f6607ccc41c5758423db1ba5fad128f
  0d70d16657ea896e831dfe3b6565f313a41804edaa35d1ee8ad9983bda0aece9
  179d4a477550c3a62d4cf17f01e2e5bb03086cd0890619d161639f5f8c1cc7ea
  4b5483eb4f5729c2092acffeaad6f23da288db7fc50449779ddf0c2beef7ece5
  4fafd4d021a4f281dea2f5a65c83e0b4cbbaf92be1b61dcb7f84efe78815061f
)

proxy_config_sha256() {
  { sha256sum "$1" 2>/dev/null || shasum -a 256 "$1"; } | cut -c1-64
}

proxy_config_was_shipped() {
  local digest known
  digest="$(proxy_config_sha256 "$1")" || return 1
  for known in "${SHIPPED_PROXY_CONFIG_SHA256[@]}"; do
    [[ "$digest" == "$known" ]] && return 0
  done
  return 1
}

# Download this release's proxy files into a new directory and print its path. Used when
# update.sh runs from the installed tree (runner or manual update), which has no staged copy.
fetch_release_proxy_config() {
  local repository="$1" tag="$2" directory relative
  directory="$(mktemp -d)" || return 1
  for relative in "${PROXY_CONFIG_FILES[@]}"; do
    mkdir -p "$directory/$(dirname "$relative")"
    curl --fail --silent --show-error --location --connect-timeout 10 --max-time 30 \
      "https://raw.githubusercontent.com/$repository/$tag/$relative" -o "$directory/$relative" \
      || { rm -rf -- "$directory"; return 1; }
  done
  printf '%s\n' "$directory"
}

# refresh_proxy_config SOURCE_ROOT: sets PROXY_CONFIG_CHANGED=1 when a live file changed.
refresh_proxy_config() {
  local source_root="$1" relative current new backup temporary
  PROXY_CONFIG_CHANGED=0
  backup="$ROOT/backups/proxy-config-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  for relative in "${PROXY_CONFIG_FILES[@]}"; do
    new="$source_root/$relative"
    current="$ROOT/$relative"
    [[ -f "$new" ]] || continue
    if [[ -f "$current" ]] && cmp -s -- "$new" "$current"; then
      rm -f -- "$current.release"
      continue
    fi
    if [[ -f "$current" ]] && ! proxy_config_was_shipped "$current"; then
      cp -- "$new" "$current.release"
      warn "$relative has local edits, so it was NOT replaced. This release's version is $relative.release;"
      warn "merge it into $relative, then run: scripts/spaceworks-compose.sh bundled up -d --force-recreate --no-deps caddy"
      continue
    fi
    mkdir -p "$(dirname "$current")"
    if [[ -f "$current" ]]; then
      mkdir -p "$backup/$(dirname "$relative")"
      chmod 700 "$ROOT/backups" "$backup"
      cp -p -- "$current" "$backup/$relative"
    fi
    temporary="$(mktemp "$(dirname "$current")/.proxy-config.XXXXXX")"
    cp -- "$new" "$temporary"
    chmod 644 "$temporary"
    mv -f -- "$temporary" "$current"
    rm -f -- "$current.release"
    PROXY_CONFIG_CHANGED=1
    say "Updated $relative to this release's version (previous copy in backups/)."
  done
}

# apply_release_proxy_config TAG: refresh from the staged release when the installer runs
# this updater, otherwise from the tag on GitHub; restart a running Caddy to load it. A
# proxy problem warns rather than failing an update whose application is already healthy.
apply_release_proxy_config() {
  local tag="$1" source_root fetched=0
  source_root="$(cd "$UPDATE_SCRIPT_DIR/.." && pwd)"
  if [[ "$source_root" == "$ROOT" ]]; then
    source_root="$(fetch_release_proxy_config "$REPOSITORY" "$tag")" || {
      warn "Could not download $tag's proxy configuration; deploy/Caddyfile was left unchanged."
      return 0
    }
    fetched=1
  fi
  refresh_proxy_config "$source_root" || warn "Refreshing the proxy configuration failed part-way; check deploy/."
  [[ "$fetched" == 0 ]] || rm -rf -- "$source_root"
  if [[ "$PROXY_CONFIG_CHANGED" == 1 && -n "$("${COMPOSE[@]}" ps -q caddy 2>/dev/null)" ]]; then
    "${COMPOSE[@]}" up -d --force-recreate --no-deps caddy >/dev/null \
      || warn "Could not restart Caddy; run: scripts/spaceworks-compose.sh bundled up -d --force-recreate --no-deps caddy"
  fi
  return 0
}
