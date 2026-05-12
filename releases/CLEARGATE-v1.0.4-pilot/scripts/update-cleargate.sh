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
load_env_file
CLEARGATE_LLM_MODEL="${CLEARGATE_LLM_MODEL:-${OLLAMA_MODEL:-gemma4:26b}}"
if [[ "$CLEARGATE_LLM_MODEL" == "cleargate-llm" || "$CLEARGATE_LLM_MODEL" == Qwen/* || "$CLEARGATE_LLM_MODEL" == qwen* ]]; then
  warn "Old Qwen/vLLM model value detected ($CLEARGATE_LLM_MODEL). Switching to Gemma4."
  CLEARGATE_LLM_MODEL="gemma4:26b"
fi
CLEARGATE_LLM_HOST="${CLEARGATE_LLM_HOST:-}"
EFFECTIVE_LLM_HOST="${CLEARGATE_LLM_HOST:-http://ollama:11434}"
set_env_value OLLAMA_IMAGE "${OLLAMA_IMAGE:-ollama/ollama:latest}"
set_env_value CLEARGATE_LLM_MODEL "$CLEARGATE_LLM_MODEL"
set_env_value CLEARGATE_LLM_HOST "$CLEARGATE_LLM_HOST"
set_env_value OLLAMA_HOST "$EFFECTIVE_LLM_HOST"
set_env_value OLLAMA_MODEL "$CLEARGATE_LLM_MODEL"
compose build backend frontend
compose up -d
wait_for_container_health cleargate-ollama 900
if [[ -z "$CLEARGATE_LLM_HOST" || "$CLEARGATE_LLM_HOST" == "http://ollama:11434" ]]; then
  if docker exec cleargate-ollama ollama list | awk '{print $1}' | grep -Fxq "$CLEARGATE_LLM_MODEL"; then
    ok "Ollama model already present: $CLEARGATE_LLM_MODEL"
  else
    step "Pull Gemma4 model into local Ollama: $CLEARGATE_LLM_MODEL"
    docker exec cleargate-ollama ollama pull "$CLEARGATE_LLM_MODEL"
  fi
fi
bash "$SCRIPT_DIR/smoke-test.sh" || warn "Smoke test reported warnings. Check status/logs."
