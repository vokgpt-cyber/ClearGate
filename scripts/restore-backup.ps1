<#
.SYNOPSIS
    Restore VELUM project from a backup created by backup.ps1.

.DESCRIPTION
    Restores either git history (from .bundle) or full working directory
    (from .7z archive) to a target location.

.PARAMETER BackupPath
    Path to .bundle or .7z file to restore.

.PARAMETER TargetDir
    Where to restore. Will be created if not exists. Should be empty.

.PARAMETER Decrypt
    If backup is encrypted (.enc extension), decrypt first.

.EXAMPLE
    .\scripts\restore-backup.ps1 -BackupPath "D:\Backups\VELUM\daily\velum_2026-04-09_18-00-00.bundle" -TargetDir "D:\Restored\velum"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$BackupPath,

    [Parameter(Mandatory)]
    [string]$TargetDir,

    [switch]$Decrypt
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $BackupPath)) {
    throw "Backup file not found: $BackupPath"
}

if (Test-Path $TargetDir) {
    $contents = Get-ChildItem $TargetDir -Force
    if ($contents) {
        throw "Target directory is not empty: $TargetDir"
    }
}
else {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}

Write-Host "Restoring from $BackupPath to $TargetDir" -ForegroundColor Cyan

# Decrypt if needed
$workingFile = $BackupPath
if ($BackupPath -like "*.enc" -or $Decrypt) {
    Write-Host "Decrypting backup..." -ForegroundColor Yellow
    $passphrase = Read-Host "Enter backup passphrase" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($passphrase)
    $plainPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

    $decryptedPath = $BackupPath -replace "\.enc$", ""
    & 7z x "-p$plainPass" $BackupPath -o"$(Split-Path $decryptedPath -Parent)" -y 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Decryption failed (wrong passphrase or corrupted file)"
    }
    $workingFile = $decryptedPath
    $plainPass = $null
}

# Restore based on file type
if ($workingFile -like "*.bundle") {
    Write-Host "Restoring git history from bundle..." -ForegroundColor Cyan
    git clone $workingFile $TargetDir
    if ($LASTEXITCODE -ne 0) {
        throw "git clone from bundle failed"
    }
    Write-Host "Git history restored. Note: working directory needs to be populated separately." -ForegroundColor Green
}
elseif ($workingFile -like "*.7z" -or $workingFile -like "*.zip") {
    Write-Host "Extracting working directory archive..." -ForegroundColor Cyan
    if (Get-Command 7z -ErrorAction SilentlyContinue) {
        & 7z x $workingFile -o"$TargetDir" -y 2>&1 | Out-Null
    }
    else {
        Expand-Archive -Path $workingFile -DestinationPath $TargetDir
    }
    Write-Host "Working directory restored." -ForegroundColor Green
}
else {
    throw "Unknown backup format: $workingFile"
}

Write-Host "" 
Write-Host "Restore completed successfully." -ForegroundColor Green
Write-Host "Target: $TargetDir"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. cd $TargetDir"
Write-Host "  2. Re-create .env from .env.example"
Write-Host "  3. Run .\scripts\setup-dev.ps1 to install dependencies"
Write-Host "  4. Run .\scripts\download-models.ps1 to download ML models"
