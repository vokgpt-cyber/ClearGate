# =============================================================================
# build-frontend-hotfix.ps1
# =============================================================================
# Build the frontend image with the entity-overlay refit fix and package it
# as a drop-in tarball for the pilot server.
#
# Run from the project root (or from anywhere - the script cds to the repo
# root via $PSScriptRoot):
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-frontend-hotfix.ps1
#
# What it does:
#   1. Rebuilds cleargate-frontend image with NEXT_PUBLIC_* set to "" so the
#      bundle uses relative URLs (no IP baking)
#   2. Looks up the auto-generated image name compose used (project-frontend)
#   3. Re-tags it as cleargate-frontend:hotfix-20260423 so the IT-side script
#      can find it deterministically
#   4. docker save into dist\cleargate-frontend-hotfix-20260423\cleargate-frontend.tar
#   5. Prints SHA256 of the tarball + total size
#
# After this script:
#   - The folder dist\cleargate-frontend-hotfix-20260423\ contains:
#       cleargate-frontend.tar       (the loadable image)
#       apply-hotfix.bat              (already in the repo)
#       README_RU.txt                 (already in the repo)
#   - Zip that folder and email/upload to IT.
# =============================================================================

$ErrorActionPreference = 'Stop'

# Resolve repo root (one level above scripts\)
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $repoRoot

$hotfixDir = Join-Path $repoRoot 'dist\cleargate-frontend-v030-20260428'
$tarPath   = Join-Path $hotfixDir 'cleargate-frontend.tar'
$hotfixTag = 'cleargate-frontend:v030-20260428'

if (-not (Test-Path $hotfixDir)) {
    New-Item -ItemType Directory -Path $hotfixDir | Out-Null
}

Write-Host ''
Write-Host '============================================================'
Write-Host 'Cleargate frontend hotfix - build pipeline'
Write-Host '============================================================'
Write-Host "repo root:  $repoRoot"
Write-Host "output:     $tarPath"
Write-Host ''

# -- Step 0. Preflight: is the docker daemon reachable? -------------------
# Without this check we burn 5-10 seconds starting `docker compose build`,
# then fail with a low-level npipe error that makes it look like the
# script is broken. Catching it up front lets us print a friendly hint.
Write-Host '[0/4] Checking that Docker Desktop is running...'
& docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'ERROR: Docker daemon is not reachable.' -ForegroundColor Red
    Write-Host ''
    Write-Host 'Most likely cause: Docker Desktop is not running.'
    Write-Host ''
    Write-Host 'What to do:'
    Write-Host '  1. Start Docker Desktop  (Start menu -> Docker Desktop, or'
    Write-Host '     click the whale icon in the system tray if it''s there).'
    Write-Host '  2. Wait until the tray icon stops animating and tooltip says'
    Write-Host '     "Docker Desktop is running" (~30-60 seconds on first start).'
    Write-Host '  3. Verify by running:   docker info'
    Write-Host '     If you see "Server Version: ...", you''re ready.'
    Write-Host '  4. Re-run this script.'
    Write-Host ''
    throw 'Docker daemon unavailable - aborting before build.'
}
Write-Host '  Docker daemon is up.'
Write-Host ''

# -- Step 1. Build ---------------------------------------------------------
Write-Host '[1/4] docker compose build frontend (no cache, empty NEXT_PUBLIC_*)...'
Write-Host ''
$buildArgs = @(
    'compose',
    '-f', 'docker-compose.yml',
    '-f', 'docker-compose.pilot.yml',
    '--profile', 'pilot',
    'build', '--no-cache',
    '--build-arg', 'NEXT_PUBLIC_API_URL=',
    '--build-arg', 'NEXT_PUBLIC_WS_URL=',
    'frontend'
)
& docker @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "docker compose build failed (exit $LASTEXITCODE)"
}
Write-Host ''

# -- Step 2. Find the just-built image -------------------------------------
Write-Host '[2/4] Locating the freshly built frontend image...'
# Try the most common compose-default names. New compose uses a hyphen,
# old compose uses an underscore. Some installs strip dots.
$candidates = @(
    'cleargate-frontend:latest',
    'cleargate_frontend:latest',
    'velum-frontend:latest',
    'velum_frontend:latest'
)
$found = $null
foreach ($candidate in $candidates) {
    $imgId = & docker images -q $candidate 2>$null
    if ($LASTEXITCODE -eq 0 -and $imgId) {
        $found = $candidate
        Write-Host "  found image: $candidate (id=$imgId)"
        break
    }
}
if (-not $found) {
    Write-Host '  None of the common candidates matched. Listing recent frontend-ish images:'
    & docker images --filter 'reference=*frontend*' --format 'table {{.Repository}}:{{.Tag}}\t{{.CreatedAt}}\t{{.Size}}' | Select-Object -First 10
    throw 'Could not locate freshly built frontend image. Inspect docker images output above and re-tag manually:  docker tag <id> cleargate-frontend:latest'
}
Write-Host ''

# -- Step 3. Re-tag --------------------------------------------------------
Write-Host "[3/4] Re-tagging $found as $hotfixTag for deterministic load..."
& docker tag $found $hotfixTag
if ($LASTEXITCODE -ne 0) {
    throw "docker tag failed (exit $LASTEXITCODE)"
}
Write-Host '  ok'
Write-Host ''

# -- Step 4. Save ----------------------------------------------------------
Write-Host "[4/4] docker save -> $tarPath ..."
if (Test-Path $tarPath) {
    Remove-Item $tarPath -Force
}
& docker save $hotfixTag -o $tarPath
if ($LASTEXITCODE -ne 0) {
    throw "docker save failed (exit $LASTEXITCODE)"
}

$tarInfo = Get-Item $tarPath
$tarSizeMB = [math]::Round($tarInfo.Length / 1MB, 1)
$tarSha = Get-FileHash -Algorithm SHA256 $tarPath
Write-Host "  size:   $tarSizeMB MB"
Write-Host "  sha256: $($tarSha.Hash)"
Write-Host ''

# -- Done ------------------------------------------------------------------
Write-Host '============================================================'
Write-Host 'Done. Hotfix bundle ready:'
Write-Host "  $hotfixDir"
Write-Host ''
Write-Host 'Files in bundle:'
Get-ChildItem $hotfixDir | Format-Table Name, Length, LastWriteTime -AutoSize
Write-Host ''
Write-Host 'Next:'
Write-Host '  1. Smoke-test locally:    cd dist\cleargate-frontend-hotfix-20260423 ; .\apply-hotfix.bat'
Write-Host '  2. Zip the folder:        Compress-Archive -Path dist\cleargate-frontend-hotfix-20260423 -DestinationPath dist\cleargate-frontend-hotfix-20260423.zip'
Write-Host '  3. Send the .zip to IT (or copy via USB the same way as before)'
Write-Host '============================================================'
