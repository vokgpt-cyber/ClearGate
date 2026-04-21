@echo off
REM Start Cleargate (pilot profile). Idempotent - safe to run if already up.
setlocal
cd /d "%~dp0"
docker compose -f docker-compose.yml -f docker-compose.pilot.yml --profile pilot up -d
if %errorlevel% neq 0 (
    echo.
    echo [X] Failed to start. See output above. Run install.bat if this is the first time.
    pause
    exit /b 1
)
echo.
echo Cleargate is up. Pilot users open: http://^<server-ip^>
echo (served by nginx on port 80 - no explicit port in the URL)
echo Use status.bat to check container health.
echo.
pause
endlocal
