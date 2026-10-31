#!/usr/bin/env bash
# Signed-full import stays under the same source guard, controller and host lock.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/scripts/restore.sh" --import "$@"
