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

api_auth_me_requires_cookie() {
  local code
  code="$(curl -k -sS -o /dev/null -w '%{http_code}' https://127.0.0.1/api/auth/me || true)"
  [[ "$code" == "401" ]]
}

frontend_uses_same_origin_api() {
  docker exec cleargate-frontend sh -c \
    "! grep -R -E 'localhost:(18000|8000)' /app/out/_next/static >/dev/null 2>&1"
}

container_port_bound_to_loopback() {
  local container="$1"
  local port="$2"
  local bindings
  bindings="$(docker port "$container" "${port}/tcp" 2>/dev/null || true)"
  [[ -n "$bindings" ]] && ! grep -vqE '^(127\.0\.0\.1|\[::1\]):' <<<"$bindings"
}

check "Ollama container running" container_running cleargate-ollama
check "BGE container running" container_running cleargate-bge
check "Backend container running" container_running cleargate-backend
check "Frontend container running" container_running cleargate-frontend
check "Nginx container running" container_running cleargate-nginx

check "Ollama healthy" container_healthy cleargate-ollama
check "BGE healthy" container_healthy cleargate-bge
check "Backend healthy" container_healthy cleargate-backend
check "Frontend healthy" container_healthy cleargate-frontend
check "Nginx healthy" container_healthy cleargate-nginx

check "Backend /health direct" curl -fsS http://127.0.0.1:8000/health
check "Nginx /health" curl -fsS http://127.0.0.1/health
check "Nginx /api/auth/me returns 401 without cookie" api_auth_me_requires_cookie
check "Frontend bundle uses same-origin API" frontend_uses_same_origin_api
check "Backend port bound to loopback only" container_port_bound_to_loopback cleargate-backend 8000
check "Frontend port bound to loopback only" container_port_bound_to_loopback cleargate-frontend 3000
check "Ollama model list" docker exec cleargate-ollama ollama list
check "Ollama /v1/models" curl -fsS http://127.0.0.1:11434/v1/models
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
