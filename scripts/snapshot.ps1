<#
.SYNOPSIS
    VELUM snapshot script - "videogame save point" for working code.

.DESCRIPTION
    Stages all changes, commits them with a `snapshot:` message, and creates a
    git tag `snapshot-YYYYMMDD-HHMM`. Gives you a named restore point you can
    diff against or roll back to without reconstructing files by memory.

    Use this whenever you reach a known-good state: after a feature works
    end-to-end, before a risky refactor, at the end of a work session.

.PARAMETER Message
    Optional human-readable label that becomes part of the commit message and
    the tag annotation. Defaults to "working state".

.PARAMETER Backup
    Also run scripts/backup.ps1 for an off-tree encrypted archive. Slower, but
    protects against a dead disk or a corrupted .git directory.

.PARAMETER Push
    Push the commit and tag to `origin` after creating them. Off by default
    because VELUM is currently developed locally only.

.EXAMPLE
    .\scripts\snapshot.ps1
    # snapshot-20260410-1842, "working state"

.EXAMPLE
    .\scripts\snapshot.ps1 -Message "iter3 all four UX bugs fixed"
    # snapshot-20260410-1842, "iter3 all four UX bugs fixed"

.EXAMPLE
    .\scripts\snapshot.ps1 -Message "before LLM adapter refactor" -Backup
    # commit + tag + off-tree encrypted backup

.NOTES
    List all snapshots: git tag -l "snapshot-*" --sort=-creatordate
    Restore one into working tree: git checkout <tag> -- .
    Hard reset to one: git reset --hard <tag>
#>

[CmdletBinding()]
param(
    [string]$Message = "working state",
    [switch]$Backup,
    [switch]$Push
)

$ErrorActionPreference = "Stop"

# Resolve repo root relative to this script.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== VELUM snapshot ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"
Write-Host "Label: $Message"
Write-Host ""

# Safety: ensure we are inside a git repo.
if (-not (Test-Path ".git")) {
    Write-Error "Not a git repo at $RepoRoot. Run this from the VELUM project root."
    exit 1
}

# Clear any stale lock file left over from a crashed git process.
$LockFile = Join-Path $RepoRoot ".git\index.lock"
if (Test-Path $LockFile) {
    Write-Host "Removing stale .git\index.lock..." -ForegroundColor Yellow
    Remove-Item $LockFile -Force
}

# Show what is about to be snapshotted.
Write-Host "Working tree state:" -ForegroundColor Cyan
git status --short
Write-Host ""

# Stage everything tracked + untracked (honors .gitignore).
git add -A

# Check if there is actually anything to commit.
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "Working tree clean, nothing to commit." -ForegroundColor Yellow
    Write-Host "Creating a tag anyway on HEAD so you have a named reference." -ForegroundColor Yellow
    $HasChanges = $false
} else {
    $HasChanges = $true
    $FileCount = ($staged | Measure-Object).Count
    Write-Host "Staging $FileCount file(s)." -ForegroundColor Green
}

# Build timestamp-based tag name.
$Timestamp = Get-Date -Format "yyyyMMdd-HHmm"
$TagName = "snapshot-$Timestamp"

# If a tag with this exact minute already exists, add a seconds suffix.
$existing = git tag -l $TagName
if ($existing) {
    $TagName = "snapshot-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}

# Commit if there are changes.
if ($HasChanges) {
    $CommitMessage = "snapshot: $Message ($Timestamp)"
    git commit -m $CommitMessage | Out-Null
    Write-Host "Committed: $CommitMessage" -ForegroundColor Green
}

# Create annotated tag pointing at HEAD.
git tag -a $TagName -m "snapshot: $Message"
Write-Host "Tagged: $TagName" -ForegroundColor Green

# Optional push.
if ($Push) {
    Write-Host "Pushing commit + tag to origin..." -ForegroundColor Cyan
    git push origin HEAD
    git push origin $TagName
}

# Optional off-tree backup.
if ($Backup) {
    $BackupScript = Join-Path $RepoRoot "scripts\backup.ps1"
    if (Test-Path $BackupScript) {
        Write-Host ""
        Write-Host "Running off-tree backup..." -ForegroundColor Cyan
        & $BackupScript -Destination "D:\Backups\VELUM"
    } else {
        Write-Warning "scripts/backup.ps1 not found, skipping off-tree backup."
    }
}

Write-Host ""
Write-Host "=== Snapshot complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Recent snapshots:" -ForegroundColor Cyan
git tag -l "snapshot-*" --sort=-creatordate | Select-Object -First 5
Write-Host ""
Write-Host "To restore files from this snapshot (without moving HEAD):" -ForegroundColor DarkGray
Write-Host "  git checkout $TagName -- ." -ForegroundColor DarkGray
Write-Host "To hard-reset to this snapshot:" -ForegroundColor DarkGray
Write-Host "  git reset --hard $TagName" -ForegroundColor DarkGray
