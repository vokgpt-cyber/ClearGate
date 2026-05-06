#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib-cleargate.sh"

BACKUP_DIR="${1:-}"
[[ -n "$BACKUP_DIR" ]] || fail "Usage: RESTORE_I_UNDERSTAND=1 $0 /opt/cleargate/backups/<timestamp>"
[[ -d "$BACKUP_DIR" ]] || fail "Backup directory not found: $BACKUP_DIR"
[[ "${RESTORE_I_UNDERSTAND:-}" == "1" ]] || fail "Restore is destructive. Re-run with RESTORE_I_UNDERSTAND=1"

DATA_ARCHIVE="$(find "$BACKUP_DIR" -maxdepth 1 -name 'cleargate-data-*.tar.gz' | head -n1)"
[[ -n "$DATA_ARCHIVE" ]] || fail "No cleargate-data-*.tar.gz found in $BACKUP_DIR"

print_release_banner
warn "This will stop CLEARGATE and replace Docker volume cleargate-data."
step "Safety backup before restore"
bash "$SCRIPT_DIR/backup-cleargate.sh"

step "Stopping stack"
compose down

step "Replacing cleargate-data volume"
docker volume rm cleargate-data >/dev/null 2>&1 || true
docker volume create cleargate-data >/dev/null
docker run --rm \
  -v cleargate-data:/data \
  -v "$BACKUP_DIR:/backup:ro" \
  alpine:3.20 \
  sh -c "cd /data && tar -xzf /backup/$(basename "$DATA_ARCHIVE")"
ok "Data volume restored"

if [[ -f "$BACKUP_DIR/env.backup" ]]; then
  cp "$BACKUP_DIR/env.backup" "$REPO_ROOT/.env"
  chmod 600 "$REPO_ROOT/.env"
  ok ".env restored"
fi

step "Starting stack"
compose up -d
bash "$SCRIPT_DIR/status-cleargate.sh"
