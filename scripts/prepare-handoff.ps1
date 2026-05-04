# =============================================================================
# prepare-handoff.ps1 - bundle Cleargate context for transfer to PC #2
# -----------------------------------------------------------------------------
# Read-only on source. Produces a self-contained folder at:
#   C:\Users\<you>\Documents\Cleargate-Handoff\
# containing:
#   memory\           - all chat-engine memory .md files (~35 files)
#   HANDOFF_BRIEF.md  - what was done last, what is pending, bootstrap message
#   PC2_CHECKLIST.md  - pre-flight checklist for the new machine
#   VERSION_INFO.txt  - auto-generated: git HEAD, branch, file count, time
#
# Usage:
#   .\scripts\prepare-handoff.ps1
#   .\scripts\prepare-handoff.ps1 -CreateZip                # also makes a ZIP on Desktop
#   .\scripts\prepare-handoff.ps1 -DestRoot 'D:\Handoff'    # custom destination
#   .\scripts\prepare-handoff.ps1 -MemoryDir 'C:\path\...'  # explicit memory path
#
# This script does NOT:
#   - modify any source files
#   - run git commits
#   - delete anything (overwrites destination contents only)
# =============================================================================

[CmdletBinding()]
param(
    [string]$DestRoot   = "$env:USERPROFILE\Documents\Cleargate-Handoff",
    [string]$MemoryDir  = $null,
    [switch]$CreateZip
)

$ErrorActionPreference = 'Stop'

function Write-Step  ($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================================================"
Write-Host "  Cleargate handoff bundle preparation"
Write-Host "  Destination: $DestRoot"
Write-Host "============================================================================"
Write-Host ""

# -------------------------------------------------------------------------
# Step 1: locate memory directory (auto-detect or use -MemoryDir override)
# -------------------------------------------------------------------------
Write-Step "Locating memory directory..."
if (-not $MemoryDir) {
    $searchRoot = "$env:APPDATA\Claude\local-agent-mode-sessions"
    if (-not (Test-Path $searchRoot)) {
        Write-Fail "Claude Desktop sessions root not found at: $searchRoot"
        Write-Host "        Pass -MemoryDir <path> explicitly if your install is non-standard."
        exit 1
    }
    Write-Host "        Searching under $searchRoot ..."
    $candidates = Get-ChildItem -Path $searchRoot -Recurse -Filter "MEMORY.md" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*\spaces\*\memory\MEMORY.md" } |
        Where-Object {
            $content = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
            $content -match "Cleargate|Velum|EPAM"
        }
    if (-not $candidates -or $candidates.Count -eq 0) {
        Write-Fail "Could not auto-detect a Cleargate memory dir."
        Write-Host "        Pass -MemoryDir explicitly. Common pattern:"
        Write-Host "        $env:APPDATA\Claude\local-agent-mode-sessions\<sessId>\<installId>\spaces\<spaceId>\memory"
        exit 1
    }
    if ($candidates.Count -gt 1) {
        Write-Warn2 "Multiple matching memory dirs found; using the most recently modified:"
        $candidates | ForEach-Object { Write-Host "          $($_.FullName)" }
        $candidates = $candidates | Sort-Object LastWriteTime -Descending
    }
    $MemoryDir = (Split-Path $candidates[0].FullName)
}

if (-not (Test-Path $MemoryDir)) {
    Write-Fail "Memory dir does not exist: $MemoryDir"
    exit 1
}
Write-Ok "Memory dir: $MemoryDir"
$memoryFiles = Get-ChildItem -Path $MemoryDir -Filter "*.md"
Write-Ok "Found $($memoryFiles.Count) memory file(s)"

# -------------------------------------------------------------------------
# Step 2: locate the Cleargate repo (must contain docs/handoff-pc2/)
# -------------------------------------------------------------------------
Write-Step "Locating Cleargate repo..."
$repoRoot = $null
$candidatePaths = @(
    "$PSScriptRoot\..",
    "$env:USERPROFILE\Documents\Claude\Projects\Velum",
    (Get-Location).Path
)
foreach ($p in $candidatePaths) {
    try {
        $resolved = (Resolve-Path $p -ErrorAction Stop).Path
        if (Test-Path "$resolved\docs\handoff-pc2\HANDOFF_BRIEF.md") {
            $repoRoot = $resolved
            break
        }
    } catch {
        # try next
    }
}
if (-not $repoRoot) {
    Write-Fail "Cleargate repo with docs/handoff-pc2/ not found."
    Write-Host "        Run this script from inside the Velum repo, or cd into it first."
    exit 1
}
Write-Ok "Repo root: $repoRoot"

# -------------------------------------------------------------------------
# Step 3: prepare destination
# -------------------------------------------------------------------------
Write-Step "Preparing destination folder..."
if (Test-Path $DestRoot) {
    Write-Warn2 "Destination already exists; existing memory/brief/checklist will be overwritten."
}
New-Item -ItemType Directory -Force -Path $DestRoot | Out-Null
New-Item -ItemType Directory -Force -Path "$DestRoot\memory" | Out-Null
Write-Ok "Destination ready: $DestRoot"

# -------------------------------------------------------------------------
# Step 4: copy memory files
# -------------------------------------------------------------------------
Write-Step "Copying memory files..."
Get-ChildItem -Path $MemoryDir -Filter "*.md" | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination "$DestRoot\memory\" -Force
}
$copied = (Get-ChildItem -Path "$DestRoot\memory" -Filter "*.md").Count
if ($copied -ne $memoryFiles.Count) {
    Write-Fail "Copied $copied memory files but source had $($memoryFiles.Count). Aborting."
    exit 1
}
Write-Ok "Copied $copied memory file(s) to $DestRoot\memory\"

# -------------------------------------------------------------------------
# Step 5: copy handoff brief and checklist
# -------------------------------------------------------------------------
Write-Step "Copying handoff documents..."
Copy-Item -Path "$repoRoot\docs\handoff-pc2\HANDOFF_BRIEF.md" -Destination "$DestRoot\" -Force
Copy-Item -Path "$repoRoot\docs\handoff-pc2\PC2_CHECKLIST.md" -Destination "$DestRoot\" -Force
Write-Ok "Brief and checklist copied"

# -------------------------------------------------------------------------
# Step 6: generate VERSION_INFO.txt
# -------------------------------------------------------------------------
Write-Step "Generating VERSION_INFO.txt..."
Push-Location $repoRoot
try {
    $branch    = (git rev-parse --abbrev-ref HEAD 2>$null)
    $headShort = (git rev-parse --short HEAD 2>$null)
    $headLong  = (git rev-parse HEAD 2>$null)
    $msg       = (git log -1 --pretty=%s 2>$null)
    $tags      = (git tag --points-at HEAD 2>$null)
} finally {
    Pop-Location
}
if (-not $branch)    { $branch    = "(git not available)" }
if (-not $headShort) { $headShort = "(unknown)" }
if (-not $tags)      { $tags      = "(none)" }

$versionInfo = @"
Cleargate handoff bundle
========================
Generated:        $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Source machine:   $env:COMPUTERNAME (user $env:USERNAME)
Source memory:    $MemoryDir
Source repo:      $repoRoot

Git state at handoff time:
  Branch:    $branch
  HEAD:      $headShort  ($headLong)
  Subject:   $msg
  Tags here: $tags

Bundle contents:
  HANDOFF_BRIEF.md   - read this first
  PC2_CHECKLIST.md   - pre-flight checklist for the new machine
  memory\*.md        - $copied files (chat-engine context)
  VERSION_INFO.txt   - this file

Next steps:
  1. Copy the entire Cleargate-Handoff folder to PC #2
     (USB / OneDrive / Yandex Disk - your choice).
  2. Place it at the SAME path on PC #2 so brief instructions match:
       C:\Users\<you>\Documents\Cleargate-Handoff\
  3. On PC #2, follow PC2_CHECKLIST.md to set up the environment.
  4. Open Claude Desktop, create new chat in the Velum project,
     paste the bootstrap message from HANDOFF_BRIEF.md (section 7).
"@
$versionInfo | Out-File -FilePath "$DestRoot\VERSION_INFO.txt" -Encoding UTF8
Write-Ok "VERSION_INFO.txt created"

# -------------------------------------------------------------------------
# Step 7 (optional): create ZIP for USB transfer
# -------------------------------------------------------------------------
if ($CreateZip) {
    Write-Step "Creating ZIP archive for USB transfer..."
    $stamp = Get-Date -Format 'yyyyMMdd-HHmm'
    $zipPath = "$env:USERPROFILE\Desktop\Cleargate-Handoff-$stamp.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path "$DestRoot\*" -DestinationPath $zipPath -CompressionLevel Optimal
    $zipSize = [math]::Round((Get-Item $zipPath).Length / 1KB, 1)
    Write-Ok "ZIP created: $zipPath ($zipSize KB)"
}

# -------------------------------------------------------------------------
# Final summary
# -------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================================"
Write-Host "  DONE"
Write-Host ""
Write-Host "  Bundle prepared at:"
Write-Host "    $DestRoot"
Write-Host ""
Write-Host "  Contents:"
Write-Host "    HANDOFF_BRIEF.md"
Write-Host "    PC2_CHECKLIST.md"
Write-Host "    VERSION_INFO.txt"
Write-Host "    memory\ ($copied files)"
if ($CreateZip) {
    Write-Host ""
    Write-Host "  ZIP for USB transfer:"
    Write-Host "    $zipPath"
}
Write-Host ""
Write-Host "  Next:"
Write-Host "    1. Copy the bundle to PC #2 at the same path."
Write-Host "    2. Open HANDOFF_BRIEF.md on PC #2 and follow its instructions."
Write-Host "============================================================================"
Write-Host ""
