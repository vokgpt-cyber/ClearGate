#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib-cleargate.sh"

TARGET_REF="${1:-$RELEASE_BRANCH}"
print_release_banner

step "Backup before update"
bash "$SCRIPT_DIR/backup-cleargate.sh"

step "Git update to $TARGET_REF"
git -C "$REPO_ROOT" fetch --all --tags
git -C "$REPO_ROOT" checkout "$TARGET_REF"
if git -C "$REPO_ROOT" symbolic-ref -q HEAD >/dev/null; then
  git -C "$REPO_ROOT" pull --ff-only
else
  warn "Detached HEAD on $TARGET_REF; skipping pull"
fi

step "Rebuild and restart"
compose build backend frontend
compose up -d
bash "$SCRIPT_DIR/smoke-test.sh" || warn "Smoke test reported warnings. Check status/logs."
