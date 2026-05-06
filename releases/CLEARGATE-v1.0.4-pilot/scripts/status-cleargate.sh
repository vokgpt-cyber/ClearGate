#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib-cleargate.sh"

print_release_banner
load_env_file

step "Git"
if [[ -d "$REPO_ROOT/.git" ]]; then
  git -C "$REPO_ROOT" log --oneline --decorate -3
else
  warn "No .git directory found"
fi

step "Docker compose"
compose ps || true

step "GPU"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu --format=csv
else
  warn "nvidia-smi not found"
fi

step "Health endpoints"
if curl -fsS http://127.0.0.1:8000/health >/tmp/cleargate-health-backend.json 2>/dev/null; then
  ok "Backend direct: http://127.0.0.1:8000/health"
  cat /tmp/cleargate-health-backend.json
  echo
else
  warn "Backend direct health is not reachable"
fi

if curl -fsS http://127.0.0.1/health >/dev/null 2>&1; then
  ok "Nginx HTTP health: http://127.0.0.1/health"
else
  warn "Nginx HTTP health is not reachable"
fi

if [[ -n "${CLEARGATE_DOMAIN:-}" ]]; then
  if curl -kfsS "https://${CLEARGATE_DOMAIN}/health" >/dev/null 2>&1; then
    ok "Public HTTPS health: https://${CLEARGATE_DOMAIN}/health"
  else
    warn "Public HTTPS health is not reachable. Check DNS/TLS/firewall."
  fi
fi

step "Admin"
if [[ -f "$INSTALL_DIR/initial-admin-password.txt" ]]; then
  ok "Initial admin password file exists: $INSTALL_DIR/initial-admin-password.txt"
else
  warn "Initial admin password file not found"
fi
