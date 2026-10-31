#!/usr/bin/env bash
# A pinned installer stages new host tooling separately from private installation state.
# Copy only the runtime bundle after the database backup; preserve every replaced file.
install_staged_host_bundle() {
  local source_root="$1" destination backup relative temporary checked_paths mode
  [[ "$source_root" != "$ROOT" ]] || return 0
  # deploy/Caddyfile* are operator-editable; refresh-proxy-config.sh replaces them only when unedited.
  local files=(
    setup.sh install.sh setup.ps1
    docker-compose.prod.yml docker-compose.cloud.yml docker-compose.yml
    docker/compose.build.yml docker/compose.tls.yml docker/compose.saas.yml
    frontend/nginx.conf
    deploy/init-object-buckets.sh
    scripts/bundled-database-url.py scripts/configure-compose-wrapper.py
    scripts/provision-runtime-image.py
    scripts/check-restore-host-bundle.py
    scripts/host-capability.py scripts/import-backup.sh
    scripts/init-host-orchestration.sh scripts/install-deploy-runner.sh scripts/install-host-bundle.sh
    scripts/refresh-proxy-config.sh
    scripts/setup-deploy-runner.sh
    scripts/env-file.sh scripts/host-image.sh scripts/module-selection.sh scripts/request-access-selection.sh
    scripts/restore.sh scripts/retire-update-polling.sh scripts/retire-update-tombstone.sh
    scripts/setup-host-orchestration.sh scripts/spaceworks-compose.sh
    scripts/update-lock.sh scripts/update.ps1 scripts/update.sh scripts/validate-compose-wrapper.py
  )
  # Refuse incomplete archives before replacing any file.
  for relative in "${files[@]}"; do
    [[ -f "$source_root/$relative" && ! -L "$source_root/$relative" ]] \
      || die "The pinned archive lacks a regular $relative."
  done
  checked_paths="$(python3 -I -B "$source_root/scripts/check-restore-host-bundle.py" \
    "$source_root" "${files[@]}")" || die "The pinned restore host bundle is incomplete or differs."
  while IFS= read -r relative; do files+=("$relative"); done <<< "$checked_paths"
  backup="$ROOT/backups/host-config-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  HOST_CONFIG_BACKUP_DIR="$backup"
  mkdir -p "$ROOT/backups"
  chmod 700 "$ROOT/backups"
  for relative in "${files[@]}"; do
    destination="$ROOT/$relative"
    # Set modes on new code directories only; never convert an existing live layout.
    (umask 022; mkdir -p -m 755 "$(dirname "$destination")")
    mkdir -p "$(dirname "$backup/$relative")"
    [[ ! -f "$destination" ]] || cp -p "$destination" "$backup/$relative"
    temporary="$(mktemp "$(dirname "$destination")/.deploy-bundle.XXXXXX")"
    case "$relative" in *.sh) mode=755 ;; *) mode=644 ;; esac
    if [[ "$EUID" != 0 && -f "$destination" ]]; then
      cp -p "$destination" "$temporary"
      chmod "$mode" "$temporary"
      cat "$source_root/$relative" > "$temporary"
    else
      cp "$source_root/$relative" "$temporary"
      chmod "$mode" "$temporary"
      [[ "$EUID" != 0 ]] || chown 0:0 "$temporary"
    fi
    mv -f -- "$temporary" "$destination"
  done
  for relative in scripts/install-auto-update.sh scripts/install-auto-update.ps1; do
    if [[ -f "$ROOT/$relative" ]]; then
      mkdir -p "$(dirname "$backup/$relative")"
      mv -- "$ROOT/$relative" "$backup/$relative"
    fi
  done
  say "Installed pinned host runtime files; previous files are in $backup."
}
