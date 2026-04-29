# =============================================================================
# Cleargate - Offline bundle packager
# =============================================================================
# Run this AFTER a successful `install.bat` on your dev/test box, once all
# 4 containers are healthy and the qwen2.5:7b model has been pulled.
# Produces a self-contained folder that the IT team can copy to the pilot
# server and install without ANY internet access (other than Docker itself).
#
# Output bundle contains:
#   images/cleargate-images.tar       <- 4 Docker images in one tar
#   images/ollama-model.tar            <- qwen2.5:7b weights (~4-5 GB, NOT gzipped)
#   backend/app/                      <- backend source (mounted by compose)
#   models/                           <- empty placeholder (mounted ro by compose)
#   logs/                             <- empty placeholder (mounted rw by compose)
#   docker-compose.yml
#   docker-compose.pilot.yml
#   nginx.pilot.conf
#   scripts/install-pilot.ps1
#   scripts/preflight.ps1
#   install.bat
#   offline-install.bat               <- entry point for the IT operator
#   start.bat, stop.bat, status.bat, logs.bat, users.bat, update.bat
#   .env.example
#   INSTALL_README.md (EN)
#   INSTALL_README_RU.md (RU)
#
# Usage (from an elevated PS, in the repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package-offline.ps1
#   powershell ... -File .\scripts\package-offline.ps1 -OutputDir D:\Shipping
#   powershell ... -File .\scripts\package-offline.ps1 -Zip
# =============================================================================

[CmdletBinding()]
param(
    [string]$OutputDir = "",
    [switch]$Zip,
    [switch]$SkipModel
)

$ErrorActionPreference = "Stop"

# --- Cosmetic helpers --------------------------------------------------------
function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn2{ param([string]$m) Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Write-Err  { param([string]$m) Write-Host "    [X]  $m" -ForegroundColor Red }
function Stop-Fail  { param([string]$m) Write-Err $m; Write-Host ""; exit 1 }

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$stamp = Get-Date -Format "yyyyMMdd-HHmm"
if (-not $OutputDir) {
    $OutputDir = Join-Path $RepoRoot "dist\cleargate-offline-$stamp"
}

Write-Host ""
Write-Host "  Cleargate - Offline bundle packager" -ForegroundColor White -BackgroundColor DarkMagenta
Write-Host "  Repo:   $RepoRoot"
Write-Host "  Output: $OutputDir"
Write-Host ""

# --- 1. Sanity: Docker up ----------------------------------------------------
Write-Step "Checking Docker daemon"
& docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Fail "Docker daemon not reachable. Start Docker Desktop and retry." }
Write-Ok "Docker reachable"

# --- 2. Sanity: required images exist locally --------------------------------
Write-Step "Checking required images"
# Image names match what docker-compose builds. COMPOSE_PROJECT_NAME=cleargate
# (set in .env.example) gives compose the prefix `cleargate-` for built images.
# If the dev box ever shows `velum-backend:latest` instead, the .env override
# is missing or compose was invoked from a different directory - fix that
# before re-packaging instead of changing the names here.
$requiredImages = @(
    "cleargate-backend:latest",
    "cleargate-frontend:latest",
    "ollama/ollama:0.5.7",
    "nginx:1.27-alpine"
)
$missing = @()
foreach ($img in $requiredImages) {
    $hit = & docker image inspect $img 2>$null
    if ($LASTEXITCODE -ne 0) { $missing += $img } else { Write-Ok "$img" }
}
if ($missing.Count -gt 0) {
    Stop-Fail "Missing images: $($missing -join ', '). Run install.bat first, then re-run packager."
}

# --- 3. Sanity: model present in ollama-data volume --------------------------
if (-not $SkipModel) {
    Write-Step "Checking qwen2.5 model in ollama-data volume"
    $modelCheck = & docker run --rm -v cleargate_ollama-data:/data alpine sh -c "ls /data/models/manifests/registry.ollama.ai/library/qwen2.5 2>/dev/null || echo MISSING"
    if ($LASTEXITCODE -ne 0 -or $modelCheck -match "MISSING") {
        Write-Warn2 "qwen2.5 not found in volume 'cleargate_ollama-data'."
        Write-Warn2 "Pull it now with:"
        Write-Warn2 "  docker exec cleargate-ollama ollama pull qwen2.5:7b-instruct-q4_K_M"
        Stop-Fail "Aborting. (Use -SkipModel to package without the model; IT team will need internet.)"
    }
    Write-Ok "Model found"
}

# --- 4. Prepare output directory --------------------------------------------
Write-Step "Preparing output directory"
if (Test-Path $OutputDir) {
    Write-Warn2 "Output dir already exists; contents will be overwritten: $OutputDir"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputDir "images")  | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputDir "scripts") | Out-Null
Write-Ok "Created $OutputDir"

# --- 5. Save Docker images ---------------------------------------------------
Write-Step "Saving Docker images to tar (this takes several minutes)"
$imagesTar = Join-Path $OutputDir "images\cleargate-images.tar"
$saveArgs = @("save", "-o", $imagesTar) + $requiredImages
& docker @saveArgs
if ($LASTEXITCODE -ne 0) { Stop-Fail "docker save failed" }
$sizeMb = [math]::Round((Get-Item $imagesTar).Length / 1MB, 0)
Write-Ok "cleargate-images.tar = $sizeMb MB"

# --- 6. Back up the ollama-data volume (the model) ---------------------------
# NOTE: do NOT gzip. The qwen2.5 GGUF weights inside the volume are already
# k-quantised (q4_K_M) - gzipping them only shaves ~1% off the size while
# adding ~10 minutes to the packaging step and ~5 minutes to the restore on
# the pilot server. Plain tar lets us stream and is dramatically faster.
if (-not $SkipModel) {
    Write-Step "Backing up ollama-data volume (model weights, this takes 1-3 minutes)"
    $modelTar = Join-Path $OutputDir "images\ollama-model.tar"
    # Convert Windows path to forward slashes for the alpine mount
    $winPath = (Resolve-Path (Split-Path $modelTar)).Path
    & docker run --rm `
        -v "cleargate_ollama-data:/data:ro" `
        -v "${winPath}:/backup" `
        alpine sh -c "cd /data && tar cf /backup/ollama-model.tar ."
    if ($LASTEXITCODE -ne 0) { Stop-Fail "Volume backup failed" }
    $sizeMb = [math]::Round((Get-Item $modelTar).Length / 1MB, 0)
    Write-Ok "ollama-model.tar = $sizeMb MB"
}

# --- 7. Copy compose + config files ------------------------------------------
Write-Step "Copying compose files and config"
$toCopy = @(
    "docker-compose.yml",
    "docker-compose.pilot.yml",
    "nginx.pilot.conf",
    ".env.example"
)
foreach ($f in $toCopy) {
    $src = Join-Path $RepoRoot $f
    if (Test-Path $src) {
        Copy-Item $src $OutputDir -Force
        Write-Ok $f
    } else {
        Write-Warn2 "Missing (skipped): $f"
    }
}

# --- 8. Copy .bat scripts ----------------------------------------------------
Write-Step "Copying operator .bat scripts"
$bats = @("install.bat", "start.bat", "stop.bat", "status.bat", "logs.bat", "update.bat", "users.bat")
foreach ($b in $bats) {
    $src = Join-Path $RepoRoot $b
    if (Test-Path $src) {
        Copy-Item $src $OutputDir -Force
        Write-Ok $b
    } else {
        Write-Warn2 "Missing (skipped): $b"
    }
}

# --- 9. Copy PowerShell scripts ---------------------------------------------
Write-Step "Copying PowerShell helpers"
$ps = @("install-pilot.ps1", "preflight.ps1")
foreach ($p in $ps) {
    $src = Join-Path $RepoRoot "scripts\$p"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $OutputDir "scripts") -Force
        Write-Ok "scripts\$p"
    } else {
        Write-Warn2 "Missing (skipped): scripts\$p"
    }
}

# --- 9b. Copy host-mounted directories --------------------------------------
# docker-compose.yml mounts these from the host. Without them, compose either
# fails outright or silently creates empty dirs that shadow what's inside the
# image. Ship the live source for backend/app (so install-pilot can re-exec
# admin tools), and empty placeholders for models/ and logs/ so the read-only
# mount points exist.
Write-Step "Copying backend source + mount placeholders"

$backendSrc = Join-Path $RepoRoot "backend\app"
$backendDst = Join-Path $OutputDir "backend\app"
if (Test-Path $backendSrc) {
    New-Item -ItemType Directory -Force -Path (Join-Path $OutputDir "backend") | Out-Null
    # Exclude __pycache__ / .pyc to keep the bundle clean and reproducible.
    Copy-Item $backendSrc $backendDst -Recurse -Force -Exclude @("__pycache__", "*.pyc")
    # Second pass: prune any nested __pycache__ that survived the top-level filter.
    Get-ChildItem -Path $backendDst -Recurse -Force -Directory |
        Where-Object { $_.Name -eq "__pycache__" } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok "backend\app\"
} else {
    Stop-Fail "backend\app missing - cannot package without backend source."
}

# models/ is mounted ro. The image bakes spaCy + GLiNER weights internally,
# so ./models is just an empty placeholder to satisfy the bind mount. If we
# ever need to ship loose model files, drop them in here.
$modelsDst = Join-Path $OutputDir "models"
New-Item -ItemType Directory -Force -Path $modelsDst | Out-Null
# Add a .gitkeep-style README so the directory survives any future zip/extract.
Set-Content -Path (Join-Path $modelsDst "README.txt") -Value "Empty placeholder - the image bakes models internally. Leave this directory in place." -Encoding ASCII
Write-Ok "models\ (placeholder)"

# logs/ is mounted rw. Backend writes cleargate.log here.
$logsDst = Join-Path $OutputDir "logs"
New-Item -ItemType Directory -Force -Path $logsDst | Out-Null
Set-Content -Path (Join-Path $logsDst "README.txt") -Value "Backend writes cleargate.log into this directory at runtime." -Encoding ASCII
Write-Ok "logs\ (placeholder)"

# --- 10. Generate offline-install.bat ---------------------------------------
Write-Step "Generating offline-install.bat"
$offlineBat = @"
@echo off
REM =============================================================================
REM Cleargate - OFFLINE installer (for pilot servers without internet access)
REM =============================================================================
REM What this does:
REM   1. Runs preflight checks (Docker, RAM, disk, ports)
REM   2. Loads Docker images from images\cleargate-images.tar
REM   3. Restores the qwen2.5 model into the ollama-data volume
REM   4. Runs the standard install-pilot.ps1 (with -SkipModelPull)
REM   5. Starts the stack
REM
REM Prerequisites (install these first):
REM   - Docker Desktop for Windows Server (or Docker Engine)
REM   - 32 GB RAM, 4+ CPU cores, 25 GB free disk
REM
REM Double-click to run (it will self-elevate to Administrator).
REM =============================================================================
setlocal
cd /d "%~dp0"

REM Self-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo   Requesting Administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo   Cleargate OFFLINE installer
echo.

REM -- Step 1: preflight --
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\preflight.ps1" -Offline
if errorlevel 1 (
    echo.
    echo   Preflight FAILED. Fix the issues above and re-run.
    pause
    exit /b 1
)

REM -- Step 2: load images --
echo.
echo ==^> Loading Docker images (this takes 1-2 minutes)...
docker load -i "%~dp0images\cleargate-images.tar"
if errorlevel 1 (
    echo   docker load failed.
    pause
    exit /b 1
)

REM -- Step 3: restore model volume (if tar exists) --
if exist "%~dp0images\ollama-model.tar" (
    echo.
    echo ==^> Restoring qwen2.5 model into ollama-data volume...
    docker volume create cleargate_ollama-data >nul
    docker run --rm -v cleargate_ollama-data:/data -v "%~dp0images:/backup:ro" alpine sh -c "cd /data && tar xf /backup/ollama-model.tar"
    if errorlevel 1 (
        echo   Model restore failed.
        pause
        exit /b 1
    )
) else (
    echo.
    echo   [!] No ollama-model.tar found - installer will pull model from internet.
)

REM -- Step 4: run installer with -SkipModelPull -NoBuild --
REM   -SkipModelPull: model was just side-loaded above, no need to fetch again.
REM   -NoBuild:       images were just side-loaded via `docker load`, so
REM                   `docker compose up --build` would try to rebuild from
REM                   source and fail on this air-gapped host.
echo.
echo ==^> Running pilot installer...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-pilot.ps1" -SkipModelPull -NoBuild %*

endlocal
pause
"@
Set-Content -Path (Join-Path $OutputDir "offline-install.bat") -Value $offlineBat -Encoding ASCII
Write-Ok "offline-install.bat"

# --- 11/12. Copy INSTALL_README templates -----------------------------------
# Russian text used to live in a here-string in this script. PowerShell 5.1
# reads BOM-less .ps1 files as the system ANSI codepage (Windows-1251 / 1252)
# and silently transcodes the Cyrillic source bytes, so the on-disk README
# came out as double-encoded mojibake. The fix is to keep the Russian (and
# English, for symmetry) README in their own .md files under
# scripts\templates\ and Copy-Item them verbatim - byte-for-byte, no
# encoding conversion in PowerShell. KEEP THIS FILE ASCII-ONLY.
Write-Step "Copying INSTALL_README templates (EN + RU)"
$templates = @(
    @{ Src = "scripts\templates\INSTALL_README.md";    Name = "INSTALL_README.md" },
    @{ Src = "scripts\templates\INSTALL_README_RU.md"; Name = "INSTALL_README_RU.md" }
)
foreach ($t in $templates) {
    $src = Join-Path $RepoRoot $t.Src
    if (-not (Test-Path $src)) {
        Stop-Fail "Template missing: $($t.Src). Cannot package without README."
    }
    Copy-Item $src (Join-Path $OutputDir $t.Name) -Force
    Write-Ok $t.Name
}

# --- 13. Optional ZIP --------------------------------------------------------
if ($Zip) {
    Write-Step "Creating ZIP archive"
    $zipPath = "$OutputDir.zip"
    Compress-Archive -Path "$OutputDir\*" -DestinationPath $zipPath -Force
    $sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 0)
    Write-Ok "$zipPath = $sizeMb MB"
}

# --- Summary -----------------------------------------------------------------
$totalSize = (Get-ChildItem $OutputDir -Recurse | Measure-Object -Property Length -Sum).Sum
$totalMb = [math]::Round($totalSize / 1MB, 0)

Write-Host ""
Write-Host "==> Packaging complete" -ForegroundColor Cyan
Write-Host "    Output:     $OutputDir"
Write-Host "    Total size: $totalMb MB"
Write-Host ""
Write-Host "  Next step: copy the output folder to the pilot server and run offline-install.bat" -ForegroundColor Green
Write-Host ""
