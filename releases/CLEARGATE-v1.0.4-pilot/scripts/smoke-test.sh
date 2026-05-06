#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib-cleargate.sh"

print_release_banner
load_env_file

PASS=0
FAILS=()

check() {
  local name="$1"
  shift
  if "$@"; then
    ok "$name"
    PASS=$((PASS + 1))
  else
    warn "$name"
    FAILS+=("$name")
  fi
}

container_running() {
  [[ "$(docker inspect "$1" --format '{{.State.Status}}' 2>/dev/null || echo missing)" == "running" ]]
}

container_healthy() {
  local health
  health="$(docker inspect "$1" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || echo missing)"
  [[ "$health" == "healthy" || "$health" == "running" ]]
}

check "vLLM container running" container_running cleargate-vllm
check "BGE container running" container_running cleargate-bge
check "Backend container running" container_running cleargate-backend
check "Frontend container running" container_running cleargate-frontend
check "Nginx container running" container_running cleargate-nginx

check "vLLM healthy" container_healthy cleargate-vllm
check "BGE healthy" container_healthy cleargate-bge
check "Backend healthy" container_healthy cleargate-backend
check "Frontend healthy" container_healthy cleargate-frontend
check "Nginx healthy" container_healthy cleargate-nginx

check "Backend /health direct" curl -fsS http://127.0.0.1:8000/health
check "Nginx /health" curl -fsS http://127.0.0.1/health
check "vLLM /v1/models" curl -fsS http://127.0.0.1:8001/v1/models
check "BGE /health" curl -fsS http://127.0.0.1:8002/health

if [[ ${#FAILS[@]} -eq 0 ]]; then
  echo
  ok "Smoke test passed: ${PASS} checks"
  exit 0
fi

echo
warn "Smoke test finished with ${#FAILS[@]} warning/failure item(s):"
for item in "${FAILS[@]}"; do
  echo "  - $item"
done
exit 1
