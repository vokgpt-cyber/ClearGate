@echo off
REM Pull the latest Cleargate code from git, then rebuild and restart.
setlocal
cd /d "%~dp0"

if not exist ".git" (
    echo This installation was not deployed from a git clone.
    echo To update, replace the folder contents from the new ZIP and run install.bat again.
    pause
    exit /b 1
)

echo.
echo === Pulling latest code ===
git pull
if %errorlevel% neq 0 (
    echo [X] git pull failed. Resolve conflicts and try again.
    pause
    exit /b 1
)

echo.
echo === Rebuilding and restarting ===
docker compose -f docker-compose.yml -f docker-compose.pilot.yml --profile pilot up -d --build
echo.
echo Update complete.
echo.
pause
endlocal
