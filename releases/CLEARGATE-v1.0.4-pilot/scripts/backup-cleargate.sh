#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib-cleargate.sh"

ensure_repo_root
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"
chmod 700 "$DEST"

print_release_banner
step "Creating backup at $DEST"

if [[ -d "$REPO_ROOT/.git" ]]; then
  git -C "$REPO_ROOT" bundle create "$DEST/cleargate-source-$STAMP.bundle" HEAD
  git -C "$REPO_ROOT" rev-parse HEAD > "$DEST/git-head.txt"
  ok "Source bundle created"
fi

if [[ -f "$REPO_ROOT/.env" ]]; then
  cp "$REPO_ROOT/.env" "$DEST/env.backup"
  chmod 600 "$DEST/env.backup"
  ok ".env copied"
fi

if docker volume inspect cleargate-data >/dev/null 2>&1; then
  docker run --rm \
    -v cleargate-data:/data:ro \
    -v "$DEST:/backup" \
    alpine:3.20 \
    sh -c "cd /data && tar -czf /backup/cleargate-data-$STAMP.tar.gz ."
  ok "cleargate-data volume archived"
else
  warn "Docker volume cleargate-data not found"
fi

if [[ -d "$LOG_DIR" ]]; then
  tar -czf "$DEST/cleargate-logs-$STAMP.tar.gz" -C "$LOG_DIR" . || warn "Could not archive logs"
fi

cat > "$DEST/manifest.txt" <<EOF
created_at=$(date -Iseconds)
release_version=$RELEASE_VERSION
release_tag=$RELEASE_TAG
baseline_commit=$RELEASE_BASELINE_COMMIT
repo_root=$REPO_ROOT
git_head=$(git_full)
note=Contains application data. Store only on encrypted/trusted media.
EOF

ok "Backup complete: $DEST"
