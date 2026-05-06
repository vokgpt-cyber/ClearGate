#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib-cleargate.sh"
print_release_banner
compose down
ok "CLEARGATE stopped. Persistent Docker volumes were not removed."
