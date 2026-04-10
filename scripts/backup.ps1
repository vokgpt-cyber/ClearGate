<#
.SYNOPSIS
    VELUM project backup script with GFS rotation, encryption and integrity check.

.DESCRIPTION
    Creates a portable backup of the VELUM project consisting of:
    - Git bundle (full repository history)
    - Working directory archive (excluding node_modules, .venv, models, etc.)
    - Optional AES encryption
    - GFS rotation: daily (7) + weekly (4) + monthly (12)
    - Integrity check via git fsck

    Designed for solo developer with local git (no GitHub/GitLab).
    Tested on Windows 11 + PowerShell 7+.

.PARAMETER Destination
    Directory where backups are stored. Default: D:\Backups\VELUM

.PARAMETER ProjectRoot
    Path to VELUM project root. Default: current directory.

.PARAMETER Encrypt
    Encrypt the working-directory archive with AES-256.
    Will prompt for passphrase if VELUM_BACKUP_PASSPHRASE env var is not set.

.PARAMETER RetentionDaily
    Number of daily backups to keep. Default: 7.

.PARAMETER RetentionWeekly
    Number of weekly backups to keep. Default: 4.

.PARAMETER RetentionMonthly
    Number of monthly backups to keep. Default: 12.

.PARAMETER SkipIntegrityCheck
    Skip git fsck verification (faster, but riskier).

.EXAMPLE
    .\scripts\backup.ps1
    # Default backup to D:\Backups\VELUM, no encryption

.EXAMPLE
    .\scripts\backup.ps1 -Destination "E:\Backups\VELUM" -Encrypt
    # Backup to external drive with encryption

.EXAMPLE
    .\scripts\backup.ps1 -RetentionDaily 14 -RetentionWeekly 8
    # Custom retention
#>

[CmdletBinding()]
param(
    [string]$Destination = "D:\Backups\VELUM",
    [string]$ProjectRoot = (Get-Location).Path,
    [switch]$Encrypt,
    [int]$RetentionDaily = 7,
    [int]$RetentionWeekly = 4,
    [int]$RetentionMonthly = 12,
    [switch]$SkipIntegrityCheck
)

# ================================================================
# Setup
# ================================================================

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$dateOnly = Get-Date -Format "yyyy-MM-dd"

# Logging
$logFile = Join-Path $Destination "backup.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $logEntry = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Write-Host $logEntry -ForegroundColor $(
        switch ($Level) {
            "ERROR" { "Red" }
            "WARN" { "Yellow" }
            "OK" { "Green" }
            default { "White" }
        }
    )
    if (Test-Path (Split-Path $logFile -Parent)) {
        Add-Content -Path $logFile -Value $logEntry -ErrorAction SilentlyContinue
    }
}

function Test-Prerequisites {
    Write-Log "Checking prerequisites..."

    # Git
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is not installed or not in PATH"
    }

    # Project root has .git
    if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
        throw "ProjectRoot '$ProjectRoot' is not a git repository"
    }

    # Destination exists or can be created
    if (-not (Test-Path $Destination)) {
        Write-Log "Creating destination: $Destination"
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    Write-Log "Prerequisites OK" "OK"
}

# ================================================================
# Backup operations
# ================================================================

function New-GitBundle {
    param([string]$OutputPath)

    Write-Log "Creating git bundle..."
    Push-Location $ProjectRoot
    try {
        git bundle create $OutputPath --all 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "git bundle failed with exit code $LASTEXITCODE"
        }
        $size = [math]::Round((Get-Item $OutputPath).Length / 1MB, 2)
        Write-Log "Git bundle created: $OutputPath ($size MB)" "OK"
    }
    finally {
        Pop-Location
    }
}

function Test-GitBundle {
    param([string]$BundlePath)

    Write-Log "Verifying git bundle integrity..."
    Push-Location $ProjectRoot
    try {
        git bundle verify $BundlePath 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "git bundle verification failed"
        }
        Write-Log "Git bundle verified" "OK"
    }
    finally {
        Pop-Location
    }
}

function Test-RepoIntegrity {
    Write-Log "Running git fsck..."
    Push-Location $ProjectRoot
    try {
        $output = git fsck --full 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "git fsck reported issues:" "WARN"
            $output | ForEach-Object { Write-Log "  $_" "WARN" }
            throw "Repository integrity check failed. Resolve issues before backup."
        }
        Write-Log "Repository integrity OK" "OK"
    }
    finally {
        Pop-Location
    }
}

function New-WorkingDirArchive {
    param([string]$OutputPath)

    Write-Log "Creating working directory archive..."

    # Files/directories to exclude (built artifacts and dependencies)
    $excludePatterns = @(
        "node_modules",
        ".venv",
        "venv",
        ".next",
        "out",
        "dist",
        "build",
        "target",
        "models",
        "ollama_data",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "*.gguf",
        "*.safetensors",
        "*.pt",
        "*.bin",
        "logs/*.log",
        "tmp",
        ".coverage",
        "htmlcov"
    )

    # Use 7-Zip if available (much faster and better compression)
    $useSevenZip = $null -ne (Get-Command 7z -ErrorAction SilentlyContinue)

    if ($useSevenZip) {
        $excludeArgs = $excludePatterns | ForEach-Object { "-xr!$_" }
        Push-Location $ProjectRoot
        try {
            & 7z a -t7z -mx=5 -mhe=on $OutputPath "." @excludeArgs 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "7z archive creation failed"
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        # Fallback to PowerShell Compress-Archive (slower, no encryption)
        Write-Log "7-Zip not found, using PowerShell Compress-Archive (slower)" "WARN"

        $tempDir = Join-Path $env:TEMP "velum-backup-$timestamp"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

        try {
            # Robocopy with exclusions
            $robocopyArgs = @(
                $ProjectRoot,
                $tempDir,
                "/E",
                "/XD"
            ) + ($excludePatterns | Where-Object { $_ -notlike "*.*" -and $_ -notlike "*/*" })

            $robocopyArgs += "/XF"
            $robocopyArgs += $excludePatterns | Where-Object { $_ -like "*.*" -or $_ -like "*/*" }

            & robocopy @robocopyArgs /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null

            Compress-Archive -Path "$tempDir\*" -DestinationPath ($OutputPath -replace "\.7z$", ".zip") -Force
        }
        finally {
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    if (Test-Path $OutputPath) {
        $size = [math]::Round((Get-Item $OutputPath).Length / 1MB, 2)
        Write-Log "Working directory archive: $OutputPath ($size MB)" "OK"
    }
}

function Protect-BackupFile {
    param([string]$FilePath)

    Write-Log "Encrypting $FilePath..."

    # Get passphrase
    $passphrase = $env:VELUM_BACKUP_PASSPHRASE
    if (-not $passphrase) {
        $secureString = Read-Host "Enter backup passphrase" -AsSecureString
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureString)
        $passphrase = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }

    # Use 7-Zip with AES-256
    $encryptedPath = "$FilePath.enc"
    if (Get-Command 7z -ErrorAction SilentlyContinue) {
        & 7z a -t7z -mhe=on "-p$passphrase" $encryptedPath $FilePath 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Remove-Item $FilePath -Force
            Write-Log "Encrypted: $encryptedPath" "OK"
        }
        else {
            throw "Encryption failed"
        }
    }
    else {
        # Fallback: use .NET AES (less convenient but works)
        Write-Log "7-Zip not available; using .NET AES" "WARN"
        Protect-FileWithAES -InputPath $FilePath -OutputPath $encryptedPath -Passphrase $passphrase
        Remove-Item $FilePath -Force
    }

    # Clear passphrase from memory
    $passphrase = $null
    [System.GC]::Collect()
}

function Protect-FileWithAES {
    param(
        [string]$InputPath,
        [string]$OutputPath,
        [string]$Passphrase
    )

    Add-Type -AssemblyName System.Security

    # Derive 256-bit key from passphrase via PBKDF2
    $salt = New-Object byte[] 16
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($salt)

    $deriver = New-Object System.Security.Cryptography.Rfc2898DeriveBytes(
        $Passphrase,
        $salt,
        100000,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $key = $deriver.GetBytes(32)
    $iv = $deriver.GetBytes(16)

    try {
        $aes = [System.Security.Cryptography.Aes]::Create()
        $aes.KeySize = 256
        $aes.Key = $key
        $aes.IV = $iv

        $encryptor = $aes.CreateEncryptor()
        $inBytes = [System.IO.File]::ReadAllBytes($InputPath)
        $outBytes = $encryptor.TransformFinalBlock($inBytes, 0, $inBytes.Length)

        # Write: salt (16) + iv (16) + ciphertext
        $finalBytes = $salt + $iv + $outBytes
        [System.IO.File]::WriteAllBytes($OutputPath, $finalBytes)
    }
    finally {
        if ($aes) { $aes.Dispose() }
        if ($encryptor) { $encryptor.Dispose() }
        if ($deriver) { $deriver.Dispose() }
    }
}

# ================================================================
# GFS Rotation
# ================================================================

function Invoke-GfsRotation {
    Write-Log "Running GFS rotation..."

    $dailyDir = Join-Path $Destination "daily"
    $weeklyDir = Join-Path $Destination "weekly"
    $monthlyDir = Join-Path $Destination "monthly"

    foreach ($dir in @($dailyDir, $weeklyDir, $monthlyDir)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    # Daily: keep last N
    $dailyFiles = Get-ChildItem $dailyDir -File | Sort-Object LastWriteTime -Descending
    if ($dailyFiles.Count -gt $RetentionDaily) {
        $toDelete = $dailyFiles | Select-Object -Skip $RetentionDaily
        foreach ($file in $toDelete) {
            Remove-Item $file.FullName -Force
            Write-Log "Removed old daily: $($file.Name)"
        }
    }

    # Weekly: promote daily backups from last Sunday to weekly
    $today = Get-Date
    if ($today.DayOfWeek -eq "Sunday") {
        $latestDaily = $dailyFiles | Select-Object -First 1
        if ($latestDaily) {
            $weeklyName = "weekly_$($latestDaily.Name)"
            Copy-Item $latestDaily.FullName -Destination (Join-Path $weeklyDir $weeklyName)
            Write-Log "Promoted to weekly: $weeklyName" "OK"
        }
    }

    $weeklyFiles = Get-ChildItem $weeklyDir -File | Sort-Object LastWriteTime -Descending
    if ($weeklyFiles.Count -gt $RetentionWeekly) {
        $toDelete = $weeklyFiles | Select-Object -Skip $RetentionWeekly
        foreach ($file in $toDelete) {
            Remove-Item $file.FullName -Force
            Write-Log "Removed old weekly: $($file.Name)"
        }
    }

    # Monthly: promote on the 1st of the month
    if ($today.Day -eq 1) {
        $latestDaily = $dailyFiles | Select-Object -First 1
        if ($latestDaily) {
            $monthlyName = "monthly_$($latestDaily.Name)"
            Copy-Item $latestDaily.FullName -Destination (Join-Path $monthlyDir $monthlyName)
            Write-Log "Promoted to monthly: $monthlyName" "OK"
        }
    }

    $monthlyFiles = Get-ChildItem $monthlyDir -File | Sort-Object LastWriteTime -Descending
    if ($monthlyFiles.Count -gt $RetentionMonthly) {
        $toDelete = $monthlyFiles | Select-Object -Skip $RetentionMonthly
        foreach ($file in $toDelete) {
            Remove-Item $file.FullName -Force
            Write-Log "Removed old monthly: $($file.Name)"
        }
    }

    Write-Log "GFS rotation done" "OK"
}

# ================================================================
# Main
# ================================================================

try {
    Write-Log "================================================================"
    Write-Log "VELUM backup started"
    Write-Log "Project: $ProjectRoot"
    Write-Log "Destination: $Destination"
    Write-Log "Encryption: $Encrypt"
    Write-Log "================================================================"

    Test-Prerequisites

    if (-not $SkipIntegrityCheck) {
        Test-RepoIntegrity
    }

    # Determine output paths
    $dailyDir = Join-Path $Destination "daily"
    if (-not (Test-Path $dailyDir)) {
        New-Item -ItemType Directory -Path $dailyDir -Force | Out-Null
    }

    $bundlePath = Join-Path $dailyDir "velum_${timestamp}.bundle"
    $archivePath = Join-Path $dailyDir "velum_${timestamp}.7z"

    # Create git bundle
    New-GitBundle -OutputPath $bundlePath
    Test-GitBundle -BundlePath $bundlePath

    # Create working dir archive
    New-WorkingDirArchive -OutputPath $archivePath

    # Encrypt if requested
    if ($Encrypt) {
        Protect-BackupFile -FilePath $archivePath
        Protect-BackupFile -FilePath $bundlePath
    }

    # Rotate
    Invoke-GfsRotation

    # Summary
    $totalSize = (Get-ChildItem $Destination -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Log "================================================================"
    Write-Log "Backup completed successfully" "OK"
    Write-Log "Total backups size: $([math]::Round($totalSize, 2)) MB"
    Write-Log "================================================================"

    exit 0
}
catch {
    Write-Log "Backup failed: $($_.Exception.Message)" "ERROR"
    Write-Log $_.ScriptStackTrace "ERROR"
    exit 1
}
