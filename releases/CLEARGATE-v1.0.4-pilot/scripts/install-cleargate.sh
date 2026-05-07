#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-cleargate.sh
. "$SCRIPT_DIR/lib-cleargate.sh"

require_root "$@"
ensure_repo_root

LOG_FILE="/var/log/cleargate-install-v${RELEASE_VERSION}-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'fail "Install aborted at line $LINENO. See $LOG_FILE"' ERR

print_release_banner

step "1/10 System and GPU checks"
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || warn "Expected Ubuntu, detected ${PRETTY_NAME:-unknown}. Continuing."
  case "${VERSION_ID:-unknown}" in
    22.04|24.04) ok "Ubuntu ${VERSION_ID} detected" ;;
    *) warn "Ubuntu ${VERSION_ID:-unknown} is not in the tested set: 22.04, 24.04" ;;
  esac
fi

command -v nvidia-smi >/dev/null 2>&1 || fail "nvidia-smi not found. Install NVIDIA driver first."
DRIVER_VER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1 | tr -d ' ')"
GPU_MEM_MB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1 | tr -d ' ')"
GPU_MEM_GB=$((GPU_MEM_MB / 1024))
ok "NVIDIA driver: ${DRIVER_VER}"
ok "GPU memory: ${GPU_MEM_GB} GB"
if (( GPU_MEM_GB < 24 )); then
  fail "Need at least 24 GB VRAM for this GPU profile."
fi
if (( GPU_MEM_GB < 40 )); then
  warn "Less than 40 GB VRAM. Qwen3-32B-AWQ + BGE-M3 may need a smaller model."
fi

step "2/10 Docker Engine"
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker not found. Installing Docker Engine via get.docker.com."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi
ok "$(docker --version)"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 plugin is missing."
ok "Docker Compose: $(docker compose version --short)"

step "3/10 NVIDIA Container Toolkit"
if ! docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
  warn "GPU is not visible inside Docker. Installing nvidia-container-toolkit."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /etc/apt/keyrings/nvidia-container-toolkit.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia-container-toolkit.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update
  apt-get install -y nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
fi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null
ok "GPU is visible inside Docker"

step "4/10 Filesystem layout"
mkdir -p "$CERT_DIR" "$BACKUP_ROOT" "$LOG_DIR"
chmod 700 "$CERT_DIR" "$BACKUP_ROOT"
ok "Created/verified $CERT_DIR, $BACKUP_ROOT, $LOG_DIR"

step "5/10 Git/version lock"
CURRENT_COMMIT="$(git_full)"
if [[ -n "$CURRENT_COMMIT" ]]; then
  if git -C "$REPO_ROOT" merge-base --is-ancestor "$RELEASE_BASELINE_COMMIT" HEAD 2>/dev/null; then
    ok "Current checkout contains baseline $RELEASE_BASELINE_COMMIT ($(git_short))"
  else
    warn "Current checkout does not contain baseline $RELEASE_BASELINE_COMMIT. Check branch before pilot."
  fi
fi

step "6/10 Environment configuration"
ENV_FILE="$REPO_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$RELEASE_DIR/.env.pilot.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "Created $ENV_FILE from pilot template"
fi

load_env_file
if [[ -t 0 ]]; then
  read -r -p "CLEARGATE_DOMAIN [${CLEARGATE_DOMAIN:-cleargate.local}]: " INPUT_DOMAIN
  CLEARGATE_DOMAIN="${INPUT_DOMAIN:-${CLEARGATE_DOMAIN:-cleargate.local}}"
  read -r -p "TLS mode selfsigned/corp_ca/letsencrypt [${CLEARGATE_TLS_MODE:-selfsigned}]: " INPUT_TLS
  CLEARGATE_TLS_MODE="${INPUT_TLS:-${CLEARGATE_TLS_MODE:-selfsigned}}"
fi
CLEARGATE_DOMAIN="${CLEARGATE_DOMAIN:-cleargate.local}"
CLEARGATE_TLS_MODE="${CLEARGATE_TLS_MODE:-selfsigned}"
set_env_value CLEARGATE_DOMAIN "$CLEARGATE_DOMAIN"
set_env_value CLEARGATE_TLS_MODE "$CLEARGATE_TLS_MODE"
set_env_value OLLAMA_HOST "http://vllm:8000/v1"
set_env_value OLLAMA_MODEL "cleargate-llm"
set_env_value EMBEDDER_URL "http://bge-embedder:80"
set_env_value CLEARGATE_DISABLE_LLM_LAYER "false"
SPACY_MODEL="${SPACY_MODEL:-ru_core_news_lg}"
SPACY_MODEL_WHEEL_URL="${SPACY_MODEL_WHEEL_URL:-https://github.com/explosion/spacy-models/releases/download/ru_core_news_lg-3.8.0/ru_core_news_lg-3.8.0-py3-none-any.whl}"
set_env_value SPACY_MODEL "$SPACY_MODEL"
set_env_value SPACY_MODEL_WHEEL_URL "$SPACY_MODEL_WHEEL_URL"
ok "Domain: $CLEARGATE_DOMAIN"
ok "TLS mode: $CLEARGATE_TLS_MODE"
ok "Required spaCy model: $SPACY_MODEL"

step "7/10 TLS certificates"
ACTIVE_CRT="$CERT_DIR/active.crt"
ACTIVE_KEY="$CERT_DIR/active.key"
case "$CLEARGATE_TLS_MODE" in
  selfsigned)
    if [[ ! -f "$CERT_DIR/selfsigned.crt" || ! -f "$CERT_DIR/selfsigned.key" ]]; then
      openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$CERT_DIR/selfsigned.key" \
        -out "$CERT_DIR/selfsigned.crt" \
        -subj "/CN=$CLEARGATE_DOMAIN" \
        -addext "subjectAltName=DNS:$CLEARGATE_DOMAIN"
      chmod 600 "$CERT_DIR/selfsigned.key"
    fi
    ln -sf "$CERT_DIR/selfsigned.crt" "$ACTIVE_CRT"
    ln -sf "$CERT_DIR/selfsigned.key" "$ACTIVE_KEY"
    warn "Self-signed certificate is installed. Browser warning is expected."
    ;;
  corp_ca)
    [[ -f "$CERT_DIR/${CLEARGATE_DOMAIN}.crt" ]] || fail "Missing $CERT_DIR/${CLEARGATE_DOMAIN}.crt"
    [[ -f "$CERT_DIR/${CLEARGATE_DOMAIN}.key" ]] || fail "Missing $CERT_DIR/${CLEARGATE_DOMAIN}.key"
    ln -sf "$CERT_DIR/${CLEARGATE_DOMAIN}.crt" "$ACTIVE_CRT"
    ln -sf "$CERT_DIR/${CLEARGATE_DOMAIN}.key" "$ACTIVE_KEY"
    ok "Corporate certificate wired"
    ;;
  letsencrypt)
    command -v certbot >/dev/null 2>&1 || apt-get install -y certbot
    if [[ ! -d "/etc/letsencrypt/live/$CLEARGATE_DOMAIN" ]]; then
      certbot certonly --standalone -d "$CLEARGATE_DOMAIN" --non-interactive --agree-tos -m "admin@$CLEARGATE_DOMAIN"
    fi
    ln -sf "/etc/letsencrypt/live/$CLEARGATE_DOMAIN/fullchain.pem" "$ACTIVE_CRT"
    ln -sf "/etc/letsencrypt/live/$CLEARGATE_DOMAIN/privkey.pem" "$ACTIVE_KEY"
    ok "Let's Encrypt certificate wired"
    ;;
  *)
    fail "Unknown CLEARGATE_TLS_MODE=$CLEARGATE_TLS_MODE"
    ;;
esac

step "8/10 Build and start Docker stack"
compose pull || warn "Some images could not be pulled now; compose up/build will retry as needed."
compose build backend frontend
compose up -d
warn "First start can take 15-40 minutes while vLLM/BGE download and load model weights."

step "9/10 Wait for services and seed admin"
wait_for_container_health cleargate-vllm 2400
wait_for_container_health cleargate-bge 900
wait_for_container_health cleargate-backend 600
wait_for_container_health cleargate-frontend 300
wait_for_container_health cleargate-nginx 300

ADMIN_PASSWORD_FILE="$INSTALL_DIR/initial-admin-password.txt"
if [[ ! -f "$ADMIN_PASSWORD_FILE" ]]; then
  openssl rand -base64 24 > "$ADMIN_PASSWORD_FILE"
  chmod 600 "$ADMIN_PASSWORD_FILE"
fi
ADMIN_PASSWORD="$(cat "$ADMIN_PASSWORD_FILE")"
printf '%s' "$ADMIN_PASSWORD" \
  | docker exec -i cleargate-backend cleargate-admin seed --username admin --admin --if-empty --password-stdin \
  || warn "Admin seed failed or user already exists. Check docker logs cleargate-backend."
ok "Initial admin password file: $ADMIN_PASSWORD_FILE"

step "10/10 systemd service"
cat > /etc/systemd/system/cleargate.service <<EOF
[Unit]
Description=CLEARGATE pilot service
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$REPO_ROOT
Environment=COMPOSE_PROJECT_NAME=cleargate
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f $RELEASE_DIR/docker-compose.release.yml --profile gpu up -d
ExecStop=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f $RELEASE_DIR/docker-compose.release.yml --profile gpu down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable cleargate.service
ok "systemd unit enabled"

cat <<EOF

==============================================================================
Install complete.

URL:        https://$CLEARGATE_DOMAIN
Admin:      admin
Password:   $ADMIN_PASSWORD_FILE
Status:     bash $RELEASE_DIR/scripts/status-cleargate.sh
Logs:       bash $RELEASE_DIR/scripts/logs-cleargate.sh
Backup:     bash $RELEASE_DIR/scripts/backup-cleargate.sh
Install log: $LOG_FILE
==============================================================================
EOF
