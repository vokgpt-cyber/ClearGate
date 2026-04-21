@echo off
REM ==========================================================================
REM Cleargate pilot installer
REM
REM Double-click this file (or run it from an elevated PowerShell prompt if
REM you want the Windows Firewall rules to be added automatically).
REM
REM What it does: verifies Docker, writes .env with the right server IP,
REM opens firewall ports 3000/8000, builds & starts Cleargate, pulls the
REM language model. Re-running is safe.
REM ==========================================================================
setlocal
cd /d "%~dp0"

echo.
echo   Cleargate - installing in: %~dp0
echo.

REM Self-elevate so firewall rules can be added without a second prompt.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo   Requesting Administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-pilot.ps1" %*
endlocal
