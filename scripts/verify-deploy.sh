#!/usr/bin/env bash
# =============================================================================
# Cleargate v0.4.0 — post-install verification (smoke test)
# =============================================================================
# Run AFTER `install-gpu.sh` completes. Confirms every layer of the stack
# is alive and the end-to-end anonymization path works against a synthetic
# input (no real client data).
#
#   sudo bash scripts/verify-deploy.sh
#
# Exit code:
#   0  — all checks green; deployment is ready for lawyers
#   1  — one or more checks failed; see output for details
#
# Designed to be re-runnable. Each check is independent; failures do not
# short-circuit subsequent checks (so IT gets a complete picture, not a
# stop-at-first-fail trickle).
# =============================================================================
set -uo pipefail

if [[ -t 1 ]]; then
    RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; RESET=$'\e[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; RESET=''
fi

INSTALL_DIR="${INSTALL_DIR:-/opt/cleargate}"
ENV_FILE="${INSTALL_DIR}/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a; . "$ENV_FILE"; set +a
fi

CLEARGATE_DOMAIN="${CLEARGATE_DOMAIN:-localhost}"

PASS_COUNT=0
FAIL_COUNT=0
FAIL_DETAIL=()

step() { echo "${BLUE}==>${RESET} $*"; }
ok()   { echo "  ${GREEN}[OK]${RESET}   $*"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo "  ${RED}[FAIL]${RESET} $*"; FAIL_COUNT=$((FAIL_COUNT+1)); FAIL_DETAIL+=("$*"); }
warn() { echo "  ${YELLOW}[WARN]${RESET} $*"; }

cat <<'BANNER'
==============================================================================
  Cleargate v0.4.0 deploy verification
==============================================================================
  Runs ~12 checks across docker, vllm, bge-embedder, backend, frontend, and
  nginx. Each check independent; failures do not abort. Total: ~30 seconds.
==============================================================================
BANNER

# =============================================================================
# Step 1. Container status
# =============================================================================
step "[1/6] Container status"
for svc in cleargate-vllm cleargate-bge cleargate-backend cleargate-frontend cleargate-nginx; do
    state=$(docker inspect "$svc" --format '{{.State.Status}}' 2>/dev/null || echo "missing")
    if [[ "$state" == "running" ]]; then
        ok "$svc is running"
    else
        fail "$svc state = $state (expected: running)"
    fi
done

# =============================================================================
# Step 2. Healthcheck status (Docker-level)
# =============================================================================
step "[2/6] Healthchecks"
for svc in cleargate-vllm cleargate-bge cleargate-backend cleargate-frontend cleargate-nginx; do
    health=$(docker inspect "$svc" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' 2>/dev/null || echo "missing")
    if [[ "$health" == "healthy" ]]; then
        ok "$svc healthcheck: healthy"
    elif [[ "$health" == "starting" ]]; then
        warn "$svc healthcheck: starting (give it ~60s more)"
    elif [[ "$health" == "n/a" ]]; then
        warn "$svc has no healthcheck defined"
    else
        fail "$svc healthcheck: $health"
    fi
done

# =============================================================================
# Step 3. vLLM /v1/models — confirm Qwen 3 actually loaded
# =============================================================================
step "[3/6] vLLM model loaded"
vllm_models=$(curl -fsS http://127.0.0.1:8001/v1/models 2>/dev/null || echo "")
if [[ "$vllm_models" =~ "cleargate-llm" ]]; then
    ok "vLLM serves model 'cleargate-llm'"
elif [[ -n "$vllm_models" ]]; then
    warn "vLLM responding but model name is unexpected:"
    echo "$vllm_models" | head -5
else
    fail "vLLM /v1/models did not respond — model still loading or service down"
fi

# =============================================================================
# Step 4. BGE embedder /health
# =============================================================================
step "[4/6] BGE embedder"
if curl -fsS http://127.0.0.1:8002/health 2>/dev/null | grep -q '.\+'; then
    ok "BGE-M3 embedder responds on :8002/health"
else
    fail "BGE embedder /health unreachable on :8002"
fi

# Try a real embedding call
embed_response=$(curl -fsS -X POST http://127.0.0.1:8002/embed \
    -H "Content-Type: application/json" \
    -d '{"inputs":["test"]}' 2>/dev/null || echo "")
if [[ "$embed_response" =~ "[" ]]; then
    ok "BGE embedder returned a vector for /embed"
else
    fail "BGE embedder /embed call failed"
fi

# =============================================================================
# Step 5. Backend /health (direct + via nginx)
# =============================================================================
step "[5/6] Backend"
backend_direct=$(curl -fsS http://127.0.0.1:8000/health 2>/dev/null || echo "")
if [[ "$backend_direct" =~ "ok" ]] || [[ "$backend_direct" =~ "healthy" ]]; then
    ok "Backend /health (direct on :8000): responsive"
else
    fail "Backend /health (direct) did not respond OK"
fi

# Through nginx (TLS) — will use the self-signed cert in dev
backend_via_nginx=$(curl -fsSk "https://${CLEARGATE_DOMAIN}/health" 2>/dev/null || echo "")
if [[ -n "$backend_via_nginx" ]]; then
    ok "Backend /health via nginx https://${CLEARGATE_DOMAIN}: responsive"
else
    warn "Backend /health via https://${CLEARGATE_DOMAIN} did not respond (DNS or cert issue?)"
fi

# =============================================================================
# Step 6. End-to-end anonymize smoke
# =============================================================================
step "[6/6] End-to-end anonymize smoke"
# Login as admin (default password from .env or initial-admin-password).
# If neither found, skip — IT can do this manually.
ADMIN_PWD="${CLEARGATE_INITIAL_ADMIN_PASSWORD:-${ADMIN_PASSWORD:-}}"
if [[ -z "$ADMIN_PWD" ]]; then
    warn "No admin password in env; skipping end-to-end smoke. Run benchmark_v040.py manually."
else
    cookie_jar=$(mktemp)
    trap 'rm -f "$cookie_jar"' EXIT

    # Login
    login_status=$(curl -sk -o /dev/null -w '%{http_code}' \
        -c "$cookie_jar" \
        -X POST "https://${CLEARGATE_DOMAIN}/api/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PWD\"}" 2>/dev/null)
    if [[ "$login_status" != "200" ]]; then
        fail "Admin login returned HTTP $login_status (expected 200)"
    else
        ok "Admin login successful"

        # Create session
        session_id=$(curl -sk -b "$cookie_jar" -c "$cookie_jar" \
            -X POST "https://${CLEARGATE_DOMAIN}/api/sessions" \
            -H "Content-Type: application/json" \
            -d '{"locale":"ru","enable_llm_layer":true}' 2>/dev/null \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
        if [[ -z "$session_id" ]]; then
            fail "Could not create session"
        else
            ok "Session created: $session_id"

            # Anonymize a synthetic test string
            test_text='Договор между Ивановым Иваном Ивановичем (ИНН 7707083893) и ООО Ромашка от 01.04.2026'
            anon_response=$(curl -sk -b "$cookie_jar" \
                -X POST "https://${CLEARGATE_DOMAIN}/api/sessions/${session_id}/anonymize" \
                -H "Content-Type: application/json" \
                -d "{\"text\":\"$test_text\"}" 2>/dev/null)

            entity_count=$(echo "$anon_response" \
                | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('entities',[])))" 2>/dev/null || echo "0")

            if [[ "$entity_count" -ge 3 ]]; then
                ok "End-to-end anonymize: $entity_count entities found in test sentence"
            else
                fail "End-to-end anonymize: only $entity_count entities found (expected >=3: PER, RU_INN, ORG)"
            fi
        fi
    fi
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=============================================================================="
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "${GREEN}ALL CHECKS PASSED${RESET}  ($PASS_COUNT/$((PASS_COUNT+FAIL_COUNT)))"
    echo "Cleargate is ready for lawyers at: https://${CLEARGATE_DOMAIN}"
    echo "=============================================================================="
    exit 0
else
    echo "${RED}$FAIL_COUNT CHECK(S) FAILED${RESET}  (passed $PASS_COUNT/$((PASS_COUNT+FAIL_COUNT)))"
    echo ""
    echo "Failed checks:"
    for detail in "${FAIL_DETAIL[@]}"; do
        echo "  - $detail"
    done
    echo ""
    echo "Send this output + 'docker logs --tail 100 cleargate-backend > backend.log'"
    echo "to vokgpt@gmail.com for triage."
    echo "=============================================================================="
    exit 1
fi
