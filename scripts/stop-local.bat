@echo off
REM ============================================================================
REM stop-local.bat - stop the local Cleargate stack (PC #2)
REM ----------------------------------------------------------------------------
REM Removes containers but keeps the cleargate-local-data volume so users,
REM sessions, and audit log survive across runs.
REM
REM To wipe data too:
REM   docker compose -f docker-compose.local.yml down -v
REM ============================================================================

cd /d "%~dp0\.."

echo.
echo Stopping Cleargate local stack ^(data is preserved^)...
docker compose -f docker-compose.local.yml down
if errorlevel 1 (
    echo Stop returned an error. See output above.
    pause
    exit /b 1
)

echo.
echo Stopped. Re-launch with: scripts\start-local.bat
echo.
exit /b 0
