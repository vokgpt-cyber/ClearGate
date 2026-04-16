<#
.SYNOPSIS
    Download ML models for CLEARGATE based on deployment profile.

.PARAMETER Profile
    Deployment profile: alpha (RTX 4060), mvp (RTX 3090), or final (cluster).

.EXAMPLE
    .\scripts\download-models.ps1 -Profile alpha
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("alpha", "mvp", "final")]
    [string]$Profile
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  CLEARGATE Model Download — Profile: $Profile" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Models per profile
$models = switch ($Profile) {
    "alpha" {
        @{
            spacy   = "ru_core_news_lg"
            gliner  = "urchade/gliner_medium-v2.1"
            ollama  = "qwen2.5:7b-instruct-q4_K_M"
            sizeGB  = 5.8
        }
    }
    "mvp" {
        @{
            spacy   = "ru_core_news_lg"
            gliner  = "urchade/gliner_large-v2.1"
            ollama  = "qwen2.5:32b-instruct-q4_K_M"
            sizeGB  = 22
        }
    }
    "final" {
        @{
            spacy   = "ru_core_news_lg"
            gliner  = "urchade/gliner_large-v2.1"
            ollama  = "qwen2.5:72b-instruct"
            sizeGB  = 80
        }
    }
}

Write-Host "Profile $Profile requires approximately $($models.sizeGB) GB of disk/VRAM" -ForegroundColor Yellow
Write-Host ""

# 1. spaCy Russian model
Write-Host "▶ Downloading spaCy: $($models.spacy)" -ForegroundColor Cyan

if (Test-Path "backend\.venv\Scripts\python.exe") {
    & .\backend\.venv\Scripts\python.exe -m spacy download $models.spacy
}
else {
    & python -m spacy download $models.spacy
}
Write-Host "  ✓ spaCy model installed" -ForegroundColor Green

# 2. GLiNER (downloads on first use via huggingface_hub)
Write-Host ""
Write-Host "▶ Pre-downloading GLiNER: $($models.gliner)" -ForegroundColor Cyan

$glinerScript = @"
from gliner import GLiNER
print('Downloading GLiNER model...')
model = GLiNER.from_pretrained('$($models.gliner)')
print('GLiNER downloaded successfully')
"@

if (Test-Path "backend\.venv\Scripts\python.exe") {
    $glinerScript | & .\backend\.venv\Scripts\python.exe -
}
else {
    $glinerScript | & python -
}
Write-Host "  ✓ GLiNER downloaded" -ForegroundColor Green

# 3. Ollama / Qwen
Write-Host ""
Write-Host "▶ Downloading Ollama model: $($models.ollama)" -ForegroundColor Cyan

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "  ✗ Ollama not installed. Install from https://ollama.com/" -ForegroundColor Red
    Write-Host "  Or: winget install Ollama.Ollama" -ForegroundColor Yellow
    exit 1
}

# Check if Ollama service is running
try {
    $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -ErrorAction Stop
}
catch {
    Write-Host "  ⚠ Ollama service not running. Starting it..." -ForegroundColor Yellow
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

ollama pull $models.ollama
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Failed to pull Ollama model" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Ollama model downloaded" -ForegroundColor Green

# Verify
Write-Host ""
Write-Host "▶ Verifying installations" -ForegroundColor Cyan

ollama list | Select-String $models.ollama.Split(":")[0] | ForEach-Object {
    Write-Host "  ✓ $_" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Models downloaded successfully" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Update .env with the correct model names:" -ForegroundColor Yellow
Write-Host "  SPACY_MODEL=$($models.spacy)"
Write-Host "  GLINER_MODEL=$($models.gliner)"
Write-Host "  OLLAMA_MODEL=$($models.ollama)"
Write-Host "  CLEARGATE_PROFILE=$Profile"
Write-Host ""
