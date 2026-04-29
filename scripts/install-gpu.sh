#!/usr/bin/env bash
# =============================================================================
# Cleargate v0.4.0 — installer for Ubuntu GPU server
# =============================================================================
# Run as a user with sudo. Idempotent: re-running picks up where it left off.
#
#   curl -fsSL https://intra.epam/cleargate/install-gpu.sh | bash
#   # or
#   sudo bash install-gpu.sh
#
# What it does:
#   1. Checks Ubuntu version, NVIDIA driver, GPU memory
#   2. Installs Docker Engine + nvidia-container-toolkit if missing
#   3. Verifies GPU passthrough into Docker (nvidia-smi inside container)
#   4. Creates /opt/cleargate layout with persistent dirs
#   5. Generates .env from template, prompts for required values
#   6. Sets up TLS based on chosen mode (letsencrypt / corp_ca / selfsigned)
#   7. Pulls model weights pre-emptively (Qwen 3 32B AWQ + BGE-M3, ~25 GB)
#   8. Brings up the stack (`docker compose ... up -d`)
#   9. Runs smoke test
#  10. Sets up systemd unit so the stack auto-starts on boot
#
# Failure handling: every step logs to /var/log/cleargate-install-*.log;
# on any non-zero exit the script tells you which file and line to look at.
# =============================================================================
set -euo pipefail

# --- Colors (only if stdout is a TTY) ---
if [[ -t 1 ]]; then
    RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; BLUE=$'\e[34m'; RESET=$'\e[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; RESET=''
fi

LOG_FILE="/var/log/cleargate-install-$(date +%Y%m%d-%H%M%S).log"
INSTALL_DIR="/opt/cleargate"
COMPOSE_PROJECT="cleargate"

step()  { echo "${BLUE}==>${RESET} $*" | tee -a "$LOG_FILE"; }
ok()    { echo "  ${GREEN}[OK]${RESET} $*" | tee -a "$LOG_FILE"; }
warn()  { echo "  ${YELLOW}[WARN]${RESET} $*" | tee -a "$LOG_FILE"; }
fail()  { echo "  ${RED}[FAIL]${RESET} $*" | tee -a "$LOG_FILE"; exit 1; }
ask()   { read -r -p "${YELLOW}?${RESET} $1: " "$2"; }

trap 'fail "Install aborted at line $LINENO. See $LOG_FILE for full output."' ERR

# Re-exec with sudo if not root.
if [[ $EUID -ne 0 ]]; then
    exec sudo -E bash "$0" "$@"
fi

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

cat <<'BANNER'
==============================================================================
  Cleargate v0.4.0 GPU installer
==============================================================================
This script will:
  - check the OS, NVIDIA driver, GPU memory
  - install Docker + nvidia-container-toolkit if missing
  - lay out /opt/cleargate
  - prompt for the few config values it cannot auto-detect
  - download Qwen 3 32B AWQ and BGE-M3 model weights (~25 GB)
  - bring the stack up and run a smoke test
  - install a systemd unit for auto-start on boot

The whole thing takes 15-30 minutes depending on your bandwidth.
You can rerun this script at any time; it is idempotent.
==============================================================================
BANNER

# =============================================================================
# Step 1. OS + GPU + driver checks
# =============================================================================
step "[1/10] System checks"

if ! grep -q '^ID=ubuntu' /etc/os-release; then
    fail "This installer targets Ubuntu. Detected: $(. /etc/os-release && echo "$PRETTY_NAME")"
fi
. /etc/os-release
case "$VERSION_ID" in
    22.04|24.04) ok "Ubuntu $VERSION_ID detected" ;;
    *) warn "Ubuntu $VERSION_ID is not in the tested set (22.04, 24.04). Continuing anyway." ;;
esac

if ! command -v nvidia-smi &>/dev/null; then
    fail "NVIDIA driver not found. Install via 'sudo ubuntu-drivers install --gpgpu' first."
fi

DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)
ok "NVIDIA driver: $DRIVER_VER"

GPU_MEM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1 | tr -d ' ')
GPU_MEM_GB=$(( GPU_MEM_MB / 1024 ))
if (( GPU_MEM_GB < 24 )); then
    fail "GPU has only ${GPU_MEM_GB} GB VRAM; need >= 24 GB for Qwen 3 32B AWQ."
fi
ok "GPU memory: ${GPU_MEM_GB} GB"

if (( GPU_MEM_GB < 40 )); then
    warn "Less than 40 GB VRAM — embedder will fight for memory; may need to switch to Qwen 3 14B."
fi

# =============================================================================
# Step 2. Docker
# =============================================================================
step "[2/10] Docker Engine"

if ! command -v docker &>/dev/null; then
    ok "Installing Docker Engine via the convenience script..."
    curl -fsSL https://get.docker.com | sh
fi
ok "Docker version: $(docker --version)"

if ! docker compose version &>/dev/null; then
    fail "Docker Compose v2 plugin missing. apt install docker-compose-plugin"
fi
ok "Docker Compose: $(docker compose version --short)"

# =============================================================================
# Step 3. nvidia-container-toolkit
# =============================================================================
step "[3/10] nvidia-container-toolkit"

if ! dpkg -l | grep -q nvidia-container-toolkit; then
    ok "Installing nvidia-container-toolkit..."
    distribution=$(. /etc/os-release; echo "$ID$VERSION_ID")
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list" \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -qq
    apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
fi
ok "nvidia-container-toolkit installed"

# =============================================================================
# Step 4. GPU-in-container smoke
# =============================================================================
step "[4/10] GPU passthrough smoke test"

if ! docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
    fail "GPU not visible inside Docker. Re-check nvidia-container-toolkit and 'docker info' for the nvidia runtime."
fi
ok "GPU visible inside Docker"

# =============================================================================
# Step 5. /opt/cleargate layout
# =============================================================================
step "[5/10] Filesystem layout at $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"/{certs,backups,logs}
chown -R "$SUDO_USER":"$SUDO_USER" "$INSTALL_DIR" 2>/dev/null || true
ok "Created $INSTALL_DIR/{certs,backups,logs}"

# Copy compose files and configs from the script's directory if not
# already in place. Allows running this script from any location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

for f in docker-compose.yml docker-compose.gpu.yml nginx.gpu.conf; do
    if [[ -f "$REPO_ROOT/$f" ]]; then
        cp -u "$REPO_ROOT/$f" "$INSTALL_DIR/$f"
    fi
done
ok "Compose files staged"

# =============================================================================
# Step 6. .env file
# =============================================================================
step "[6/10] Configuration ($INSTALL_DIR/.env)"

ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cat > "$ENV_FILE" <<EOF
# Cleargate v0.4.0 configuration. Edit and re-run install-gpu.sh.

# --- Required: public-facing identity ---
CLEARGATE_DOMAIN=
CLEARGATE_TLS_MODE=selfsigned   # letsencrypt | corp_ca | selfsigned

# --- LLM ---
VLLM_MODEL=Qwen/Qwen3-32B-AWQ
VLLM_MAX_MODEL_LEN=16384
VLLM_GPU_UTIL=0.85
EMBEDDER_MODEL=BAAI/bge-m3

# --- Optional: HuggingFace token (skips rate limits, faster downloads) ---
HF_TOKEN=

# --- Optional: LDAP / Active Directory ---
# Empty = local password auth only. Filled = LDAP-first, local fallback.
LDAP_URL=
LDAP_BIND_DN=
LDAP_BIND_PASSWORD=
LDAP_BASE_DN=
LDAP_ADMIN_GROUP_DN=
LDAP_USER_GROUP_DN=

# --- Auto-generated; do not edit manually ---
CLEARGATE_SESSION_COOKIE_SECRET=
EOF
    chmod 600 "$ENV_FILE"
    warn "$ENV_FILE created with empty values. Open it, fill in CLEARGATE_DOMAIN at minimum, then re-run."
    exit 0
fi

set -a; . "$ENV_FILE"; set +a

if [[ -z "${CLEARGATE_DOMAIN:-}" ]]; then
    fail "CLEARGATE_DOMAIN is empty in $ENV_FILE — set it and re-run."
fi
ok "Domain: $CLEARGATE_DOMAIN, TLS mode: ${CLEARGATE_TLS_MODE:-selfsigned}"

# Generate session cookie secret if missing.
if [[ -z "${CLEARGATE_SESSION_COOKIE_SECRET:-}" ]]; then
    SECRET=$(openssl rand -hex 32)
    sed -i "s|^CLEARGATE_SESSION_COOKIE_SECRET=.*|CLEARGATE_SESSION_COOKIE_SECRET=$SECRET|" "$ENV_FILE"
    ok "Generated session cookie secret"
fi

# =============================================================================
# Step 7. TLS certificates
# =============================================================================
step "[7/10] TLS certificate setup ($CLEARGATE_TLS_MODE)"

mkdir -p "$INSTALL_DIR/certs"
ACTIVE_CRT="$INSTALL_DIR/certs/active.crt"
ACTIVE_KEY="$INSTALL_DIR/certs/active.key"

case "$CLEARGATE_TLS_MODE" in
    letsencrypt)
        if ! command -v certbot &>/dev/null; then
            apt-get install -y certbot
        fi
        if [[ ! -d "/etc/letsencrypt/live/$CLEARGATE_DOMAIN" ]]; then
            ok "Requesting certificate from Let's Encrypt..."
            certbot certonly --standalone -d "$CLEARGATE_DOMAIN" --non-interactive --agree-tos -m "admin@$CLEARGATE_DOMAIN"
        fi
        ln -sf "/etc/letsencrypt/live/$CLEARGATE_DOMAIN/fullchain.pem" "$ACTIVE_CRT"
        ln -sf "/etc/letsencrypt/live/$CLEARGATE_DOMAIN/privkey.pem" "$ACTIVE_KEY"
        ok "Let's Encrypt cert in place"
        ;;
    corp_ca)
        # IT/security drops their own cert + key into /opt/cleargate/certs/
        # before running this. We just symlink to the right names.
        if [[ ! -f "$INSTALL_DIR/certs/$CLEARGATE_DOMAIN.crt" ]]; then
            fail "Expected $INSTALL_DIR/certs/$CLEARGATE_DOMAIN.crt (corp_ca mode). Drop it in and re-run."
        fi
        ln -sf "$INSTALL_DIR/certs/$CLEARGATE_DOMAIN.crt" "$ACTIVE_CRT"
        ln -sf "$INSTALL_DIR/certs/$CLEARGATE_DOMAIN.key" "$ACTIVE_KEY"
        ok "Corporate CA cert wired"
        ;;
    selfsigned)
        if [[ ! -f "$ACTIVE_CRT" ]]; then
            ok "Generating self-signed cert for $CLEARGATE_DOMAIN..."
            openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
                -keyout "$INSTALL_DIR/certs/selfsigned.key" \
                -out "$INSTALL_DIR/certs/selfsigned.crt" \
                -subj "/CN=$CLEARGATE_DOMAIN" \
                -addext "subjectAltName=DNS:$CLEARGATE_DOMAIN"
            ln -sf "$INSTALL_DIR/certs/selfsigned.crt" "$ACTIVE_CRT"
            ln -sf "$INSTALL_DIR/certs/selfsigned.key" "$ACTIVE_KEY"
            warn "Self-signed cert: browsers will scream. Use only for development."
        fi
        ok "Self-signed cert in place"
        ;;
    *)
        fail "Unknown CLEARGATE_TLS_MODE=$CLEARGATE_TLS_MODE (expected: letsencrypt | corp_ca | selfsigned)"
        ;;
esac

# =============================================================================
# Step 8. Model pre-pull (parallel, save first-start latency)
# =============================================================================
step "[8/10] Pre-pulling model images and weights"

ok "Pulling vllm/vllm-openai container image..."
docker pull vllm/vllm-openai:v0.7.3

ok "Pulling text-embeddings-inference container image..."
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5

# We can't easily pre-pull HF model weights without running the container,
# so we just warn the user that first start will take a while.
warn "Model weights ($VLLM_MODEL + $EMBEDDER_MODEL, ~25 GB) will download on first start"
warn "  → first 'docker compose up' will take 15-30 min depending on bandwidth"

# =============================================================================
# Step 9. Bring up stack + smoke
# =============================================================================
step "[9/10] Starting the stack"

cd "$INSTALL_DIR"
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up -d

ok "Waiting for vLLM to become healthy (this is the slow one — model download + load)..."
WAIT_MAX=1800   # 30 min
WAIT_ELAPSED=0
while (( WAIT_ELAPSED < WAIT_MAX )); do
    if docker inspect cleargate-vllm --format '{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; then
        break
    fi
    sleep 10
    WAIT_ELAPSED=$(( WAIT_ELAPSED + 10 ))
    if (( WAIT_ELAPSED % 60 == 0 )); then
        ok "  ... still waiting (${WAIT_ELAPSED}s elapsed; check 'docker logs cleargate-vllm' if curious)"
    fi
done
if (( WAIT_ELAPSED >= WAIT_MAX )); then
    fail "vLLM did not become healthy within ${WAIT_MAX}s. Check 'docker logs cleargate-vllm'."
fi
ok "vLLM healthy"

# Smoke test: hit the OpenAI-compat endpoint with a tiny prompt.
ok "Smoke-testing vLLM via OpenAI API..."
SMOKE=$(curl -s -X POST http://127.0.0.1:8001/v1/completions \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"cleargate-llm\",\"prompt\":\"Привет, \",\"max_tokens\":8,\"temperature\":0}" \
    | jq -r '.choices[0].text // "FAILED"')
if [[ "$SMOKE" == "FAILED" ]] || [[ -z "$SMOKE" ]]; then
    fail "vLLM smoke test failed. See 'docker logs cleargate-vllm'."
fi
ok "vLLM responds: '${SMOKE:0:40}...'"

ok "Smoke-testing backend health endpoint..."
sleep 5
HTTP=$(curl -sk -o /dev/null -w '%{http_code}' "https://$CLEARGATE_DOMAIN/health" || echo 000)
if [[ "$HTTP" != "200" ]]; then
    warn "Backend health returned HTTP $HTTP — check 'docker logs cleargate-backend' and 'docker logs cleargate-nginx'"
else
    ok "Backend healthy via nginx"
fi

# =============================================================================
# Step 10. systemd unit (auto-start on boot)
# =============================================================================
step "[10/10] systemd auto-start"

UNIT_FILE=/etc/systemd/system/cleargate.service
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Cleargate anonymization service
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up -d
ExecStop=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable cleargate.service
ok "cleargate.service installed and enabled (will auto-start on boot)"

cat <<EOF

==============================================================================
  ${GREEN}Install complete.${RESET}
==============================================================================
  Cleargate is running at:  https://$CLEARGATE_DOMAIN
  Logs:                     docker compose -f $INSTALL_DIR/docker-compose.yml -f $INSTALL_DIR/docker-compose.gpu.yml logs -f
  Stop:                     systemctl stop cleargate.service
  Start:                    systemctl start cleargate.service
  Install log:              $LOG_FILE

  Next: log in as the seeded admin user (run 'docker exec cleargate-backend
  cleargate-admin create-user --username <name> --password <pass> --admin'),
  or wait for LDAP to take over once IT fills in LDAP_* in $ENV_FILE.
==============================================================================
EOF
