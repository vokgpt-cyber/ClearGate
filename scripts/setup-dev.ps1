<#
.SYNOPSIS
    Initialize VELUM development environment on Windows 11.

.DESCRIPTION
    Checks prerequisites, creates Python venv, installs dependencies,
    sets up pre-commit hooks, and prepares the project for development.

.PARAMETER SkipPython
    Skip Python venv setup.

.PARAMETER SkipNode
    Skip Node.js / Tauri setup.

.PARAMETER SkipHooks
    Skip pre-commit hooks installation.
#>

[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$SkipNode,
    [switch]$SkipHooks
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "▶ $Message" -ForegroundColor Cyan
}

function Write-OK {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Write-Skip {
    param([string]$Message)
    Write-Host "  ⊘ $Message" -ForegroundColor Yellow
}

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

# ----------------------------------------------------------------
# Banner
# ----------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  VELUM Development Environment Setup" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# ----------------------------------------------------------------
# Prerequisites check
# ----------------------------------------------------------------
Write-Step "Checking prerequisites"

$prereqs = @{
    "git"    = "Git"
    "python" = "Python 3.12+"
    "node"   = "Node.js 20+"
    "npm"    = "npm"
    "docker" = "Docker Desktop"
    "cargo"  = "Rust toolchain (for Tauri)"
}

$missing = @()
foreach ($cmd in $prereqs.Keys) {
    if (Test-Command $cmd) {
        Write-OK "$($prereqs[$cmd]) found"
    }
    else {
        Write-Host "  ✗ $($prereqs[$cmd]) NOT found" -ForegroundColor Red
        $missing += $prereqs[$cmd]
    }
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing prerequisites:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Install instructions:" -ForegroundColor Yellow
    Write-Host "  Git:    winget install Git.Git"
    Write-Host "  Python: winget install Python.Python.3.12"
    Write-Host "  Node:   winget install OpenJS.NodeJS.LTS"
    Write-Host "  Docker: https://www.docker.com/products/docker-desktop/"
    Write-Host "  Rust:   winget install Rustlang.Rustup"
    exit 1
}

# Python version check
$pythonVersion = & python --version 2>&1
if ($pythonVersion -notmatch "Python 3\.(1[2-9]|[2-9]\d)") {
    Write-Host "  ✗ Python version too old: $pythonVersion (need 3.12+)" -ForegroundColor Red
    exit 1
}
Write-OK "Python version: $pythonVersion"

# ----------------------------------------------------------------
# Git initialization
# ----------------------------------------------------------------
Write-Step "Git repository"

if (-not (Test-Path ".git")) {
    git init -b main
    Write-OK "Initialized git repository"
}
else {
    Write-Skip "Git repository already initialized"
}

# Configure git for the project (local config only)
git config core.autocrlf false
git config core.eol lf
git config user.name "VELUM Developer" -ErrorAction SilentlyContinue
Write-OK "Git config set"

# ----------------------------------------------------------------
# Backend setup
# ----------------------------------------------------------------
if (-not $SkipPython) {
    Write-Step "Backend (Python)"

    Push-Location backend
    try {
        if (-not (Test-Path ".venv")) {
            python -m venv .venv
            Write-OK "Created virtual environment"
        }
        else {
            Write-Skip "Virtual environment exists"
        }

        # Activate and install
        & .\.venv\Scripts\python.exe -m pip install --upgrade pip
        Write-OK "Upgraded pip"

        & .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
        Write-OK "Installed Python dependencies"
    }
    finally {
        Pop-Location
    }
}

# ----------------------------------------------------------------
# Frontend setup
# ----------------------------------------------------------------
if (-not $SkipNode) {
    Write-Step "Frontend (Tauri + Next.js)"

    Push-Location frontend
    try {
        if (-not (Test-Path "node_modules")) {
            npm install
            Write-OK "Installed Node dependencies"
        }
        else {
            Write-Skip "node_modules already exists"
        }

        # Tauri CLI
        if (-not (Test-Command "cargo-tauri")) {
            cargo install tauri-cli --version "^2.0.0"
            Write-OK "Installed Tauri CLI"
        }
        else {
            Write-Skip "Tauri CLI already installed"
        }
    }
    finally {
        Pop-Location
    }
}

# ----------------------------------------------------------------
# Pre-commit hooks
# ----------------------------------------------------------------
if (-not $SkipHooks) {
    Write-Step "Pre-commit hooks"

    # Try to use backend venv pre-commit
    $preCommit = ".\backend\.venv\Scripts\pre-commit.exe"
    if (Test-Path $preCommit) {
        & $preCommit install
        Write-OK "Pre-commit hooks installed"
    }
    elseif (Test-Command "pre-commit") {
        pre-commit install
        Write-OK "Pre-commit hooks installed (global)"
    }
    else {
        Write-Skip "pre-commit not found, skipping"
    }
}

# ----------------------------------------------------------------
# .env file
# ----------------------------------------------------------------
Write-Step "Environment variables"

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-OK "Created .env from .env.example"
        Write-Host "  ⚠ Don't forget to fill in API keys in .env" -ForegroundColor Yellow
    }
}
else {
    Write-Skip ".env already exists"
}

# Generate VELUM_MASTER_KEY if not set
$envContent = Get-Content .env -Raw -ErrorAction SilentlyContinue
if ($envContent -and $envContent -match "VELUM_MASTER_KEY=replace-me") {
    $newKey = & python -c "import secrets; print(secrets.token_urlsafe(32))"
    $envContent = $envContent -replace "VELUM_MASTER_KEY=replace-me-with-32-byte-random-key", "VELUM_MASTER_KEY=$newKey"
    Set-Content .env $envContent -NoNewline
    Write-OK "Generated VELUM_MASTER_KEY"
}

# ----------------------------------------------------------------
# Directories
# ----------------------------------------------------------------
Write-Step "Project directories"

foreach ($dir in @("logs", "models", "backups", "tmp")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        New-Item -ItemType File -Path "$dir\.gitkeep" -Force | Out-Null
    }
}
Write-OK "Created logs/, models/, backups/, tmp/"

# ----------------------------------------------------------------
# Done
# ----------------------------------------------------------------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Edit .env and fill in API keys (Anthropic, OpenAI, Google)"
Write-Host "  2. Download ML models: .\scripts\download-models.ps1 -Profile alpha"
Write-Host "  3. Start backend:  cd backend && .\.venv\Scripts\activate && uvicorn app.main:app --reload"
Write-Host "  4. Start frontend: cd frontend && npm run tauri dev"
Write-Host ""
Write-Host "Documentation:" -ForegroundColor Cyan
Write-Host "  - CLAUDE.md           (main instructions for Claude Code)"
Write-Host "  - docs/ARCHITECTURE.md"
Write-Host "  - docs/tasks/         (development tasks)"
Write-Host ""
