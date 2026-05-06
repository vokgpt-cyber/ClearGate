#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib-cleargate.sh"
SERVICE="${1:-}"
if [[ -n "$SERVICE" ]]; then
  compose logs -f --tail 200 "$SERVICE"
else
  compose logs -f --tail 200
fi
