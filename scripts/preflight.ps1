# =============================================================================
# Cleargate - Pre-install preflight checker
# =============================================================================
# Runs FIRST in offline-install.bat to fail loud on known blockers before the
# operator spends time on a broken install. Each check prints [OK] / [!]  /
# [X] with a concrete remediation hint. Exits 0 on pass, 1 on any FAIL.
#
# Usage (from an elevated PowerShell):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight.ps1
#   powershell ... -File .\scripts\preflight.ps1 -Quick     (skip network checks)
#
# Philosophy: prefer WARN over FAIL for anything the operator can override.
# FAIL only on things that GUARANTEE the install will break.
# =============================================================================

[CmdletBinding()]
param(
    [switch]$Quick,
    [switch]$Offline
)

$ErrorActionPreference = "Continue"

# --- Cosmetic helpers --------------------------------------------------------
function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn2{ param([string]$m) Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Write-Err  { param([string]$m) Write-Host "    [X]  $m" -ForegroundColor Red }

$script:FailCount = 0
$script:WarnCount = 0
function Mark-Fail { param([string]$m) Write-Err $m; $script:FailCount++ }
function Mark-Warn { param([string]$m) Write-Warn2 $m; $script:WarnCount++ }

Write-Host ""
Write-Host "  Cleargate - Preflight check" -ForegroundColor White -BackgroundColor DarkBlue
Write-Host "  Mode: $(if($Offline){'offline'}else{'online'}) | Quick: $Quick"
Write-Host ""

# --- 1. Admin elevation ------------------------------------------------------
Write-Step "Administrator elevation"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Ok "Running as Administrator"
} else {
    Mark-Fail "NOT running as Administrator. Right-click install-offline.bat and choose 'Run as administrator'."
}

# --- 2. Windows version ------------------------------------------------------
Write-Step "Windows version"
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $caption = $os.Caption
    $version = $os.Version
    Write-Ok "$caption (build $version)"
    if ($caption -match "Windows Server 2016") {
        Mark-Warn "Server 2016 is old; tested on 2019/2022. Continue at your own risk."
    } elseif ($caption -notmatch "Server 201[9]|Server 2022|Server 2025|Windows 1[01]") {
        Mark-Warn "Untested Windows edition: $caption"
    }
} catch {
    Mark-Warn "Could not detect Windows version: $_"
}

# --- 3. PowerShell execution policy ------------------------------------------
Write-Step "PowerShell execution policy"
$policy = Get-ExecutionPolicy -Scope LocalMachine
if ($policy -eq "Restricted") {
    Mark-Fail "ExecutionPolicy is Restricted. Run in elevated PS: Set-ExecutionPolicy -Scope LocalMachine RemoteSigned"
} else {
    Write-Ok "ExecutionPolicy (LocalMachine) = $policy"
}

# --- 4. RAM ------------------------------------------------------------------
Write-Step "Physical RAM"
try {
    $totalBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    $totalGb = [math]::Round($totalBytes / 1GB, 1)
    if ($totalGb -lt 16) {
        Mark-Fail "Only $totalGb GB RAM. Minimum is 16 GB; Cleargate pilot needs 32 GB for the 7B model."
    } elseif ($totalGb -lt 28) {
        Mark-Warn "$totalGb GB RAM. Cleargate will run, but qwen2.5:7b may be slow or fall back to a smaller model."
    } else {
        Write-Ok "$totalGb GB RAM"
    }
} catch {
    Mark-Warn "Could not read RAM: $_"
}

# --- 5. Free disk on system drive --------------------------------------------
Write-Step "Free disk space"
try {
    $sysDrive = $env:SystemDrive.TrimEnd(":")
    $drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${sysDrive}:'"
    $freeGb = [math]::Round($drive.FreeSpace / 1GB, 1)
    if ($freeGb -lt 15) {
        Mark-Fail "Only $freeGb GB free on ${sysDrive}:. Need ~25 GB for images + model."
    } elseif ($freeGb -lt 25) {
        Mark-Warn "$freeGb GB free on ${sysDrive}:. Tight; 25+ GB recommended."
    } else {
        Write-Ok "$freeGb GB free on ${sysDrive}:"
    }
} catch {
    Mark-Warn "Could not read disk space: $_"
}

# --- 6. Docker installed + daemon reachable ----------------------------------
Write-Step "Docker"
$dockerOk = $false
try {
    $dv = & docker --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $dv) { throw "docker not on PATH" }
    Write-Ok "docker CLI: $dv"
    & docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Mark-Fail "Docker daemon is not running. Start Docker Desktop and wait for the whale icon to stop animating, then re-run."
    } else {
        Write-Ok "Docker daemon reachable"
        $dockerOk = $true
    }
} catch {
    Mark-Fail "Docker is not installed or not on PATH. Install Docker Desktop for Windows Server from https://docs.docker.com/desktop/install/windows-install/ (or Docker Engine via Mirantis)."
}

# --- 7. Docker is in Linux-container mode ------------------------------------
if ($dockerOk) {
    Write-Step "Docker container mode"
    try {
        $osType = & docker info --format "{{.OSType}}" 2>$null
        if ($osType -eq "linux") {
            Write-Ok "Linux containers (correct)"
        } else {
            Mark-Fail "Docker is in '$osType' container mode. Right-click the Docker tray icon -> 'Switch to Linux containers...', then re-run."
        }
    } catch {
        Mark-Warn "Could not query docker info: $_"
    }
}

# --- 8. docker compose v2 present --------------------------------------------
if ($dockerOk) {
    Write-Step "docker compose v2"
    try {
        $cv = & docker compose version 2>$null
        if ($LASTEXITCODE -eq 0 -and $cv) {
            Write-Ok "compose: $cv"
        } else {
            Mark-Fail "'docker compose' v2 missing. Update Docker Desktop to a recent version (>= 4.20)."
        }
    } catch {
        Mark-Fail "'docker compose' v2 is required. Update Docker Desktop."
    }
}

# --- 9. Ports free -----------------------------------------------------------
Write-Step "Required ports (80, 3000, 8000, 11434)"
$ports = @{ 80 = "nginx"; 3000 = "frontend"; 8000 = "backend"; 11434 = "ollama" }
foreach ($p in $ports.Keys | Sort-Object) {
    $role = $ports[$p]
    try {
        $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            $pids = ($conns | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
            $procs = @()
            foreach ($cpid in ($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
                $p2 = Get-Process -Id $cpid -ErrorAction SilentlyContinue
                if ($p2) { $procs += "$($p2.ProcessName)(PID $cpid)" }
            }
            Mark-Fail "Port $p ($role) is held by: $($procs -join ', '). Stop that process before installing."
        } else {
            Write-Ok "Port $p free ($role)"
        }
    } catch {
        Mark-Warn "Could not check port $p : $_"
    }
}

# --- 10. Outbound network (online mode only) ---------------------------------
if (-not $Offline -and -not $Quick) {
    Write-Step "Outbound network to Docker Hub / PyPI / HuggingFace"
    $targets = @(
        @{ Name = "Docker Hub";   Host = "registry-1.docker.io";     Port = 443 },
        @{ Name = "PyPI";         Host = "pypi.org";                  Port = 443 },
        @{ Name = "HuggingFace";  Host = "huggingface.co";            Port = 443 }
    )
    foreach ($t in $targets) {
        try {
            $r = Test-NetConnection -ComputerName $t.Host -Port $t.Port -WarningAction SilentlyContinue -InformationLevel Quiet
            if ($r) {
                Write-Ok "$($t.Name) reachable ($($t.Host):$($t.Port))"
            } else {
                Mark-Warn "$($t.Name) NOT reachable at $($t.Host):$($t.Port). Check corporate proxy/firewall. (OK in offline mode.)"
            }
        } catch {
            Mark-Warn "$($t.Name) check failed: $_"
        }
    }
} else {
    Write-Step "Outbound network (skipped)"
    Write-Ok "Skipped (Offline or Quick mode)"
}

# --- Summary -----------------------------------------------------------------
Write-Host ""
Write-Host "==> Preflight summary" -ForegroundColor Cyan
Write-Host "    Failures: $script:FailCount"
Write-Host "    Warnings: $script:WarnCount"
Write-Host ""

if ($script:FailCount -gt 0) {
    Write-Host "  PREFLIGHT FAILED - fix the [X] items above and re-run." -ForegroundColor White -BackgroundColor DarkRed
    Write-Host ""
    exit 1
} elseif ($script:WarnCount -gt 0) {
    Write-Host "  Preflight passed with warnings. Review [!] items - install may still succeed." -ForegroundColor Black -BackgroundColor Yellow
    Write-Host ""
    exit 0
} else {
    Write-Host "  Preflight PASSED. System is ready for Cleargate install." -ForegroundColor Green
    Write-Host ""
    exit 0
}
