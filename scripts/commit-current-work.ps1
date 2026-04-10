<#
.SYNOPSIS
    One-shot script to commit VELUM iteration-3 work as five logical
    Conventional Commits, then tag the final state as a snapshot.

.DESCRIPTION
    Iteration 3 accumulated a large amount of uncommitted changes across
    backend, frontend, and launcher. Rather than squash it all into one
    giant commit, this script stages files in logical groups and commits
    each group with a Conventional Commit message, then creates a named
    snapshot tag at the end.

    Run this ONCE from the repo root after clearing any stale .git\index.lock.

.EXAMPLE
    cd C:\Users\V\Documents\Claude\Projects\Velum
    Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue
    .\scripts\commit-current-work.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "=== VELUM iteration-3 commit pass ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"
Write-Host ""

if (-not (Test-Path ".git")) {
    Write-Error "Not a git repo."
    exit 1
}

# Clear stale lock if present.
$LockFile = Join-Path $RepoRoot ".git\index.lock"
if (Test-Path $LockFile) {
    Write-Host "Removing stale .git\index.lock..." -ForegroundColor Yellow
    Remove-Item $LockFile -Force
}

# Make sure we are clean to start (no staged files from prior attempt).
git reset | Out-Null

function Commit-Group {
    param(
        [string]$Message,
        [string[]]$Paths
    )
    Write-Host ""
    Write-Host ">>> $Message" -ForegroundColor Cyan

    $added = 0
    foreach ($p in $Paths) {
        $full = Join-Path $RepoRoot $p
        if ((Test-Path $full) -or (git ls-files --error-unmatch $p 2>$null)) {
            git add -- $p
            $added++
        } else {
            Write-Host "  (skipped, not present): $p" -ForegroundColor DarkGray
        }
    }

    if ($added -eq 0) {
        Write-Host "  (no files for this group, skipping commit)" -ForegroundColor DarkGray
        return
    }

    $staged = git diff --cached --name-only
    if (-not $staged) {
        Write-Host "  (nothing staged, skipping commit)" -ForegroundColor DarkGray
        return
    }

    Write-Host "  Staged:" -ForegroundColor DarkGray
    $staged | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

    git commit -m $Message | Out-Null
    Write-Host "  Committed." -ForegroundColor Green
}

# -------------------------------------------------------------------
# Commit 1: backend session and router fixes
# -------------------------------------------------------------------
Commit-Group -Message "fix(backend): stabilize session manager and anonymize/documents routers" -Paths @(
    "backend/app/routers/anonymize.py",
    "backend/app/routers/documents.py",
    "backend/app/services/session_manager.py"
)

# -------------------------------------------------------------------
# Commit 2: new frontend components (SplitWorkspace era)
# -------------------------------------------------------------------
Commit-Group -Message "feat(frontend): split-workspace, docx viewer, sidebar, entity popover, selection toolbar, legend" -Paths @(
    "frontend/src/components/SplitWorkspace.tsx",
    "frontend/src/components/DocxViewer.tsx",
    "frontend/src/components/Sidebar.tsx",
    "frontend/src/components/EmptyState.tsx",
    "frontend/src/components/EntityLegend.tsx",
    "frontend/src/components/EntityPopover.tsx",
    "frontend/src/components/SelectionToolbar.tsx",
    "frontend/src/components/Header.tsx"
)

# -------------------------------------------------------------------
# Commit 3: iteration 3 bug fixes (race, selection, multi-session, zoom)
# -------------------------------------------------------------------
Commit-Group -Message "fix(frontend): iter3 UX - anonymize race, custom selection, multi-session state, zoom 0.88" -Paths @(
    "frontend/src/app/page.tsx",
    "frontend/src/app/globals.css"
)

# -------------------------------------------------------------------
# Commit 4: hooks and package changes
# -------------------------------------------------------------------
Commit-Group -Message "chore(frontend): update locale/theme hooks and package deps" -Paths @(
    "frontend/src/hooks/useLocale.tsx",
    "frontend/src/hooks/useTheme.tsx",
    "frontend/package.json",
    "frontend/package-lock.json"
)

# -------------------------------------------------------------------
# Commit 5: launcher, claude local settings, snapshot scripts
# -------------------------------------------------------------------
Commit-Group -Message "chore: launcher tweaks, claude local settings, snapshot/commit scripts" -Paths @(
    "START-VELUM-Alpha.bat",
    ".claude/settings.local.json",
    "scripts/snapshot.ps1",
    "scripts/commit-current-work.ps1"
)

# -------------------------------------------------------------------
# Sweep: anything else still uncommitted (test files, misc)
# -------------------------------------------------------------------
$remaining = git status --short
if ($remaining) {
    Write-Host ""
    Write-Host ">>> Remaining untracked/modified files after logical groups:" -ForegroundColor Yellow
    $remaining | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Write-Host "  (left alone, review manually or run snapshot.ps1 to sweep)" -ForegroundColor DarkGray
}

# -------------------------------------------------------------------
# Final snapshot tag
# -------------------------------------------------------------------
Write-Host ""
Write-Host "Creating snapshot tag for iter3 baseline..." -ForegroundColor Cyan
$SnapshotScript = Join-Path $RepoRoot "scripts\snapshot.ps1"
& $SnapshotScript -Message "iter3 baseline: 4 UX bugs fixed, multi-session, zoom 0.88"

Write-Host ""
Write-Host "=== Done. Recent commits: ===" -ForegroundColor Green
git log --oneline -n 10
