#!/usr/bin/env bash
set -euo pipefail

RELEASE_VERSION="1.0.4"
RELEASE_TAG="v1.0.4"
RELEASE_BRANCH="release/pilot-v1.0.4"
RELEASE_BASELINE_COMMIT="38077abbb0d8b1536479094880971914d0a730af"
REPO_URL="https://github.com/vokgpt-cyber/ClearGate.git"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${CLEARGATE_REPO_ROOT:-$(cd "$RELEASE_DIR/../.." && pwd)}"
INSTALL_DIR="${CLEARGATE_INSTALL_DIR:-/opt/cleargate}"
BACKUP_ROOT="${CLEARGATE_BACKUP_ROOT:-/opt/cleargate/backups}"
CERT_DIR="${CLEARGATE_CERT_DIR:-/opt/cleargate/certs}"
LOG_DIR="${CLEARGATE_LOG_DIR:-/opt/cleargate/logs}"

if [[ -t 1 ]]; then
  RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; RESET=$'\e[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; RESET=''
fi

step() { echo "${BLUE}==>${RESET} $*"; }
ok() { echo "  ${GREEN}[OK]${RESET} $*"; }
warn() { echo "  ${YELLOW}[WARN]${RESET} $*"; }
fail() { echo "  ${RED}[FAIL]${RESET} $*" >&2; exit 1; }

ensure_repo_root() {
  [[ -f "$REPO_ROOT/docker-compose.yml" ]] || fail "docker-compose.yml not found. Run from a cloned CLEARGATE repo."
  [[ -f "$REPO_ROOT/docker-compose.gpu.yml" ]] || fail "docker-compose.gpu.yml not found. GPU compose profile is missing."
  [[ -d "$REPO_ROOT/.git" ]] || warn "Repository .git directory not found; git-based update checks will be limited."
}

compose() {
  ensure_repo_root
  (
    cd "$REPO_ROOT"
    COMPOSE_PROJECT_NAME=cleargate docker compose \
      -f docker-compose.yml \
      -f docker-compose.gpu.yml \
      -f "$RELEASE_DIR/docker-compose.release.yml" \
      --profile gpu \
      "$@"
  )
}

git_short() {
  if [[ -d "$REPO_ROOT/.git" ]]; then
    git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true
  fi
}

git_full() {
  if [[ -d "$REPO_ROOT/.git" ]]; then
    git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true
  fi
}

require_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    exec sudo -E bash "$0" "$@"
  fi
}

load_env_file() {
  local env_file="$REPO_ROOT/.env"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
  fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  local env_file="${3:-$REPO_ROOT/.env}"
  local escaped
  escaped="$(printf '%s' "$value" | sed 's/[&|]/\\&/g')"
  if grep -q "^${key}=" "$env_file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${escaped}|" "$env_file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$env_file"
  fi
}

wait_for_container_health() {
  local container="$1"
  local max_seconds="${2:-300}"
  local elapsed=0
  while (( elapsed < max_seconds )); do
    local state
    state="$(docker inspect "$container" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || echo missing)"
    if [[ "$state" == "healthy" || "$state" == "running" ]]; then
      ok "$container is $state"
      return 0
    fi
    sleep 10
    elapsed=$((elapsed + 10))
    if (( elapsed % 60 == 0 )); then
      warn "Still waiting for $container (${elapsed}s elapsed, state=$state)"
    fi
  done
  fail "$container did not become healthy within ${max_seconds}s"
}

print_release_banner() {
  cat <<EOF
==============================================================================
  CLEARGATE pilot package ${RELEASE_VERSION}
  App baseline: ${RELEASE_TAG} / ${RELEASE_BASELINE_COMMIT}
  Repo root:    ${REPO_ROOT}
==============================================================================
EOF
}
