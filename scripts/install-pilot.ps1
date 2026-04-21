# =============================================================================
# Cleargate - Pilot installer (PowerShell)
# =============================================================================
# Called by install.bat in the repo root. Do not run directly unless you know
# what you're doing - the .bat handles execution-policy bypass.
#
# What this script does (idempotent - safe to re-run):
#   1. Verifies Docker Desktop is installed and running
#   2. Detects the server's primary LAN IP (or asks the operator)
#   3. Creates .env from .env.example if missing, injecting:
#        - a fresh CLEARGATE_MASTER_KEY
#        - empty NEXT_PUBLIC_API_URL / NEXT_PUBLIC_WS_URL (same-origin via nginx)
#        - BACKEND_CORS_ORIGINS=*
#   4. Opens Windows Firewall for TCP 80 (nginx), 3000, 8000
#   5. Builds and starts the containers via docker compose (pilot profile)
#   6. Waits for Ollama to be healthy, then pulls qwen2.5:7b-instruct-q4_K_M
#   7. Prints the URL for pilot users
# =============================================================================

[CmdletBinding()]
param(
    [string]$ServerIp = "",
    [switch]$ResetEnv,
    [switch]$SkipFirewall,
    [switch]$SkipModelPull
)

$ErrorActionPreference = "Stop"

# --- Cosmetic helpers --------------------------------------------------------
function Write-Step   { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok     { param([string]$m) Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn2  { param([string]$m) Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Write-Err    { param([string]$m) Write-Host "    [X]  $m" -ForegroundColor Red }
function Stop-Fail    { param([string]$m) Write-Err $m; Write-Host ""; Read-Host "Press Enter to close" | Out-Null; exit 1 }

# --- Locate repo root --------------------------------------------------------
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host ""
Write-Host "  Cleargate - Pilot installer" -ForegroundColor White -BackgroundColor DarkRed
Write-Host "  Repo: $RepoRoot" -ForegroundColor DarkGray
Write-Host ""

# --- 1. Docker sanity check --------------------------------------------------
Write-Step "Checking Docker Desktop"
try {
    $dv = docker --version 2>$null
    if (-not $dv) { throw "docker not on PATH" }
    Write-Ok "docker: $dv"
} catch {
    Stop-Fail "Docker not installed or not on PATH. Install Docker Desktop from https://docker.com/products/docker-desktop"
}
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "daemon down" }
    Write-Ok "Docker daemon reachable"
} catch {
    Stop-Fail "Docker Desktop is installed but not running. Open Docker Desktop, wait for the whale icon to go green, then re-run install.bat."
}
try {
    $cv = docker compose version 2>$null
    Write-Ok "compose: $cv"
} catch {
    Stop-Fail "`docker compose` plugin missing. Update Docker Desktop to a recent version."
}

# --- 2. Determine server IP --------------------------------------------------
Write-Step "Server IP"
if (-not $ServerIp) {
    # Auto-detect: first non-loopback, non-link-local IPv4
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -ExpandProperty IPAddress -Unique
    if ($candidates.Count -eq 0) {
        $detected = Read-Host "Could not auto-detect server IP. Enter it manually (e.g. 10.1.2.3)"
    } elseif ($candidates.Count -eq 1) {
        $detected = $candidates[0]
        Write-Ok "Auto-detected: $detected"
        $confirm = Read-Host "Press Enter to use $detected, or type a different IP"
        if ($confirm) { $detected = $confirm }
    } else {
        Write-Host "    Multiple candidates found:" -ForegroundColor DarkGray
        for ($i = 0; $i -lt $candidates.Count; $i++) {
            Write-Host "      [$($i+1)] $($candidates[$i])"
        }
        $pick = Read-Host "Pick a number (or type IP manually)"
        if ($pick -match '^\d+$' -and [int]$pick -ge 1 -and [int]$pick -le $candidates.Count) {
            $detected = $candidates[[int]$pick - 1]
        } else {
            $detected = $pick
        }
    }
    $ServerIp = $detected
}
if (-not ($ServerIp -match '^\d{1,3}(\.\d{1,3}){3}$')) {
    Stop-Fail "Invalid IP address: '$ServerIp'"
}
Write-Ok "Using server IP: $ServerIp"

# Same-origin via nginx on port 80. Empty NEXT_PUBLIC_* values mean the
# frontend build emits relative URLs ("/api/...", "/ws/...") which nginx
# then proxies to the backend on behalf of the user's browser. No more
# IP baking, no CORS round-trip, a single URL on a single port.
$apiUrl = ""
$wsUrl  = ""
$appUrl = "http://${ServerIp}"

# --- 3. .env --------------------------------------------------------------
Write-Step "Configuring .env"
$envPath     = Join-Path $RepoRoot ".env"
$exampleEnv  = Join-Path $RepoRoot ".env.example"

if (-not (Test-Path $exampleEnv)) { Stop-Fail ".env.example missing from repo root - re-clone the repository." }

if ($ResetEnv -and (Test-Path $envPath)) {
    $backup = "$envPath.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $envPath $backup
    Write-Warn2 "Reset requested - existing .env backed up to $(Split-Path $backup -Leaf)"
    Remove-Item $envPath
}

if (-not (Test-Path $envPath)) {
    Copy-Item $exampleEnv $envPath
    Write-Ok "Created .env from .env.example"
} else {
    Write-Ok "Keeping existing .env (use -ResetEnv to regenerate)"
}

function Set-EnvLine {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = Get-Content $Path -Encoding UTF8
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) {
            $lines[$i] = "$Key=$Value"
            $found = $true
            break
        }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    $lines | Set-Content $Path -Encoding UTF8
}

function Get-EnvLine {
    param([string]$Path, [string]$Key)
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*=(.*)$'
    foreach ($l in (Get-Content $Path -Encoding UTF8)) {
        if ($l -match $pattern) { return $Matches[1].Trim() }
    }
    return ""
}

# Master key
$existingKey = Get-EnvLine -Path $envPath -Key "CLEARGATE_MASTER_KEY"
$needNewKey = $true
if ($existingKey -and $existingKey -notmatch 'xxxxxxxx' -and $existingKey.Length -ge 32) {
    $needNewKey = $false
    Write-Ok "Master key already set - keeping it"
}
if ($needNewKey) {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $newKey = [Convert]::ToBase64String($bytes)
    Set-EnvLine -Path $envPath -Key "CLEARGATE_MASTER_KEY" -Value $newKey
    Write-Ok "Generated fresh CLEARGATE_MASTER_KEY (256-bit)"
}

# URLs and CORS - always rewrite so the IP stays fresh if operator re-runs
Set-EnvLine -Path $envPath -Key "CLEARGATE_PROFILE" -Value "pilot"
Set-EnvLine -Path $envPath -Key "OLLAMA_HOST"      -Value "http://ollama:11434"
Set-EnvLine -Path $envPath -Key "OLLAMA_MODEL"     -Value "qwen2.5:7b-instruct-q4_K_M"
Set-EnvLine -Path $envPath -Key "NEXT_PUBLIC_API_URL" -Value $apiUrl
Set-EnvLine -Path $envPath -Key "NEXT_PUBLIC_WS_URL"  -Value $wsUrl
Set-EnvLine -Path $envPath -Key "BACKEND_CORS_ORIGINS" -Value "*"
# COMPOSE_FILE / COMPOSE_PROFILES tell every bare "docker compose ..."
# command run from this folder to automatically load the pilot override
# and activate the pilot profile. Without this, if someone runs "docker
# compose restart" or "docker compose down" without the -f/--profile
# flags, the frontend service drops out of the effective config and
# disappears. With COMPOSE_FILE in .env, the correct files are always
# loaded. Windows uses ";" as the path separator for this variable.
Set-EnvLine -Path $envPath -Key "COMPOSE_FILE"     -Value "docker-compose.yml;docker-compose.pilot.yml"
Set-EnvLine -Path $envPath -Key "COMPOSE_PROFILES" -Value "pilot"
Write-Ok "NEXT_PUBLIC_API_URL=(empty - same-origin via nginx)"
Write-Ok "NEXT_PUBLIC_WS_URL=(empty - same-origin via nginx)"
Write-Ok "BACKEND_CORS_ORIGINS=*"
Write-Ok "COMPOSE_FILE + COMPOSE_PROFILES (bare 'docker compose' now picks up pilot)"

# --- 4. Firewall -----------------------------------------------------------
# Port 80 is the one pilot users actually need (nginx reverse proxy).
# 3000 and 8000 stay open for operator-side debugging - you can hit the
# frontend container or the backend directly if the proxy is acting up.
# If TCP/80 is already taken by IIS on this Windows Server, install.bat
# will succeed but docker compose will fail to publish nginx on :80 -
# stop IIS ("Stop-Service W3SVC") or change the port mapping in
# docker-compose.pilot.yml before re-running.
if (-not $SkipFirewall) {
    Write-Step "Windows Firewall (TCP 80, 3000, 8000)"
    $rules = @(
        @{ Name = "Cleargate Web (HTTP)"; Port = 80 },
        @{ Name = "Cleargate Frontend";   Port = 3000 },
        @{ Name = "Cleargate Backend";    Port = 8000 }
    )
    foreach ($r in $rules) {
        $exists = Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue
        if ($exists) {
            Write-Ok "'$($r.Name)' already present"
        } else {
            try {
                New-NetFirewallRule -DisplayName $r.Name -Direction Inbound -Protocol TCP -LocalPort $r.Port -Action Allow | Out-Null
                Write-Ok "Opened TCP $($r.Port)"
            } catch {
                Write-Warn2 "Could not add rule '$($r.Name)' - run install.bat as Administrator if pilot users can't connect. Error: $($_.Exception.Message)"
            }
        }
    }
} else {
    Write-Warn2 "-SkipFirewall - skipping firewall setup"
}

# --- 5. Build & start ------------------------------------------------------
Write-Step "Building and starting Cleargate (this may take 10-15 minutes on first run)"
$composeArgs = @(
    "-f", "docker-compose.yml",
    "-f", "docker-compose.pilot.yml",
    "--profile", "pilot"
)
Write-Host "    docker compose $($composeArgs -join ' ') up -d --build" -ForegroundColor DarkGray
& docker compose @composeArgs up -d --build
if ($LASTEXITCODE -ne 0) { Stop-Fail "docker compose up failed - scroll up for the error, or run logs.bat to see container output." }
Write-Ok "Containers started"

# --- 6. Pull the LLM model --------------------------------------------------
if (-not $SkipModelPull) {
    Write-Step "Waiting for Ollama to be healthy"
    $ok = $false
    for ($i = 1; $i -le 24; $i++) {
        Start-Sleep -Seconds 5
        $status = docker inspect --format '{{.State.Health.Status}}' cleargate-ollama 2>$null
        if ($status -eq "healthy") { $ok = $true; break }
        Write-Host "    waiting... ($i/24, status=$status)" -ForegroundColor DarkGray
    }
    if (-not $ok) {
        Write-Warn2 "Ollama did not become healthy within 2 minutes. Check logs.bat. Skipping model pull - you can run it manually later:"
        Write-Host "      docker exec cleargate-ollama ollama pull qwen2.5:7b-instruct-q4_K_M" -ForegroundColor DarkGray
    } else {
        Write-Ok "Ollama healthy"
        Write-Step "Pulling qwen2.5:7b-instruct-q4_K_M (~4.7 GB, one-time download)"
        docker exec cleargate-ollama ollama pull qwen2.5:7b-instruct-q4_K_M
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 "Model pull failed. You can retry later with: docker exec cleargate-ollama ollama pull qwen2.5:7b-instruct-q4_K_M"
        } else {
            Write-Ok "Model pulled"
        }
    }
} else {
    Write-Warn2 "-SkipModelPull - skipping; pull manually when ready"
}

# --- 7. Done ----------------------------------------------------------------
Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "  Cleargate is running." -ForegroundColor Green
Write-Host "  Share this URL with pilot users:" -ForegroundColor Green
Write-Host ""
Write-Host "      $appUrl" -ForegroundColor White -BackgroundColor DarkGreen
Write-Host ""
Write-Host "  Helper scripts (double-click any of these):" -ForegroundColor Green
Write-Host "      start.bat     - start containers"
Write-Host "      stop.bat      - stop containers"
Write-Host "      status.bat    - show container state"
Write-Host "      logs.bat      - tail logs"
Write-Host "      update.bat    - git pull + rebuild"
Write-Host "=================================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to close" | Out-Null
