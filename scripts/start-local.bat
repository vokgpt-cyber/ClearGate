@echo off
REM ============================================================================
REM start-local.bat - one-click local Cleargate launcher (PC #2)
REM ----------------------------------------------------------------------------
REM What it does, in order:
REM   1. Checks Docker Desktop is running.
REM   2. Checks Ollama is reachable on http://localhost:11434.
REM   3. Pulls the configured Russian-friendly model if missing.
REM   4. Builds + starts backend + frontend + nginx via docker-compose.local.yml.
REM   5. Waits for the stack to become healthy (up to ~3 minutes).
REM   6. Opens http://localhost in the default browser.
REM
REM Login: admin / admin
REM Stop:  scripts\stop-local.bat
REM ============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0\.."

set "MODEL=qwen2.5:7b-instruct-q4_K_M"
if not "%OLLAMA_MODEL%"=="" set "MODEL=%OLLAMA_MODEL%"

echo.
echo ============================================================================
echo   CLEARGATE - local launch on this PC
echo   Model: %MODEL%
echo ============================================================================
echo.

REM --- Step 1: Docker Desktop -------------------------------------------------
echo [1/6] Checking Docker Desktop...
docker info >nul 2>&1
if errorlevel 1 (
    echo   FAIL: Docker is not running. Start Docker Desktop and re-run this script.
    pause
    exit /b 1
)
echo   OK: Docker is running.

REM --- Step 2: Ollama on host -------------------------------------------------
echo [2/6] Checking Ollama on http://localhost:11434 ...
curl -fsS http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo   FAIL: Ollama is not reachable on port 11434.
    echo         Start Ollama desktop app or run "ollama serve" and re-run this script.
    pause
    exit /b 1
)
echo   OK: Ollama responds.

REM --- Step 3: Required model present? ---------------------------------------
echo [3/6] Checking model "%MODEL%" ...
curl -fsS http://localhost:11434/api/tags | findstr /C:"%MODEL%" >nul 2>&1
if errorlevel 1 (
    echo   Model not found locally. Pulling now ^(this can take 5-15 minutes^)...
    ollama pull "%MODEL%"
    if errorlevel 1 (
        echo   FAIL: ollama pull failed. Check the model name or your network.
        pause
        exit /b 1
    )
)
echo   OK: model "%MODEL%" available.

REM --- Step 4: Build + start the compose stack -------------------------------
echo [4/6] Starting Cleargate containers ^(first run includes build, ~5-10 min^)...
docker compose -f docker-compose.local.yml up -d --build
if errorlevel 1 (
    echo   FAIL: docker compose up returned an error. See output above.
    pause
    exit /b 1
)
echo   OK: containers launched.

REM --- Step 5: Wait for nginx /health to respond -----------------------------
echo [5/6] Waiting for backend to be healthy through nginx ^(up to 3 minutes^)...
set /a TRIES=0
:wait_loop
set /a TRIES+=1
curl -fsS http://localhost/health >nul 2>&1
if not errorlevel 1 goto ready
if %TRIES% geq 36 goto timeout
timeout /t 5 /nobreak >nul
goto wait_loop

:timeout
echo   WARN: backend did not respond in 3 minutes. Check logs:
echo         docker compose -f docker-compose.local.yml logs --tail 100 backend
echo   You can still try opening http://localhost in your browser.
goto open_browser

:ready
echo   OK: backend is responsive.

REM --- Step 5b: Seed admin/admin user (idempotent, no-op if any user exists) -
echo [5b] Seeding admin user (skipped if users table already populated)...
echo admin| docker exec -i cleargate-local-backend cleargate-admin seed --username admin --password-stdin --if-empty >nul 2>&1
if errorlevel 1 (
    echo   WARN: seed command failed. You may need to create the admin user manually:
    echo         echo admin^| docker exec -i cleargate-local-backend cleargate-admin seed --username admin --password-stdin --if-empty
) else (
    echo   OK: admin/admin ready.
)

:open_browser
echo [6/6] Opening browser at http://localhost ...
start "" "http://localhost"

echo.
echo ============================================================================
echo   Cleargate is running.
echo   URL:    http://localhost
echo   Login:  admin / admin
echo   Stop:   scripts\stop-local.bat
echo   Logs:   docker compose -f docker-compose.local.yml logs -f
echo ============================================================================
echo.
endlocal
exit /b 0
