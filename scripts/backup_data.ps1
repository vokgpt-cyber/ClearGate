param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$BackupRoot = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path "backups"),
    [int]$RetentionDays = 30,
    [switch]$IncludeLogs
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$backupRootPath = if (Test-Path -LiteralPath $BackupRoot) {
    (Resolve-Path -LiteralPath $BackupRoot).Path
} else {
    (New-Item -ItemType Directory -Force -Path $BackupRoot).FullName
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archivePath = Join-Path $backupRootPath "cleargate-data-$stamp.zip"
$bundlePath = Join-Path $backupRootPath "cleargate-source-$stamp.bundle"
$workDir = Join-Path ([System.IO.Path]::GetTempPath()) "cleargate-backup-$stamp"

function Copy-IfExists {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    $source = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        return
    }
    $resolvedSource = (Resolve-Path -LiteralPath $source).Path
    $resolvedRepo = (Resolve-Path -LiteralPath $repoRoot).Path
    if (-not $resolvedSource.StartsWith($resolvedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to copy path outside repository: $resolvedSource"
    }

    $dest = Join-Path $DestinationRoot $RelativePath
    $destParent = Split-Path -Parent $dest
    New-Item -ItemType Directory -Force -Path $destParent | Out-Null
    Copy-Item -LiteralPath $resolvedSource -Destination $dest -Recurse -Force
}

try {
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null

    $manifest = [ordered]@{
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        project_root = $repoRoot
        include_logs = [bool]$IncludeLogs
        retention_days = $RetentionDays
        note = "Archive is local and not encrypted. Store it only on trusted encrypted media."
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $workDir "manifest.json") -Encoding UTF8

    Copy-IfExists -RelativePath "backend\data" -DestinationRoot $workDir
    Copy-IfExists -RelativePath "qa\private_corpus" -DestinationRoot $workDir
    if ($IncludeLogs) {
        Copy-IfExists -RelativePath "logs" -DestinationRoot $workDir
    }

    Push-Location $repoRoot
    try {
        git bundle create $bundlePath HEAD
    } finally {
        Pop-Location
    }

    $archiveItems = @(Get-ChildItem -LiteralPath $workDir | Select-Object -ExpandProperty FullName)
    Compress-Archive -LiteralPath $archiveItems -DestinationPath $archivePath -Force

    if ($RetentionDays -gt 0) {
        $cutoff = (Get-Date).AddDays(-$RetentionDays)
        Get-ChildItem -LiteralPath $backupRootPath -File |
            Where-Object {
                ($_.Name -like "cleargate-data-*.zip" -or $_.Name -like "cleargate-source-*.bundle") -and
                $_.LastWriteTime -lt $cutoff
            } |
            ForEach-Object {
                $candidate = $_.FullName
                $resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
                if (-not $resolvedCandidate.StartsWith($backupRootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Refusing to delete path outside backup root: $resolvedCandidate"
                }
                Remove-Item -LiteralPath $resolvedCandidate -Force
            }
    }

    Write-Output "Data archive: $archivePath"
    Write-Output "Source bundle: $bundlePath"
} finally {
    if (Test-Path -LiteralPath $workDir) {
        $resolvedWorkDir = (Resolve-Path -LiteralPath $workDir).Path
        $tempRoot = [System.IO.Path]::GetTempPath()
        if ($resolvedWorkDir.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedWorkDir -Recurse -Force
        }
    }
}
