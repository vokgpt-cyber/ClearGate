@echo off
title CLEARGATE Alpha Launcher

echo.
echo  ============================================
echo   CLEARGATE Alpha - Launcher
echo  ============================================
echo.

set ROOT=%~dp0

echo [1/4] Checking prerequisites...

if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
    echo   ERROR: Backend venv not found.
    echo   Run: cd backend ^& py -3.12 -m venv .venv ^& .venv\Scripts\pip install -e ".[dev]"
    pause
    exit /b 1
)

where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: npm not found. Install Node.js 20+.
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\node_modules" (
    echo   Frontend deps not installed - running npm install...
    pushd "%ROOT%frontend"
    call npm install
    if errorlevel 1 (
        echo   ERROR: npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    rem Re-run npm install automatically if package.json is newer than
    rem node_modules\.package-lock.json. Catches the case where a new
    rem dependency was added but npm install has not been run yet.
    powershell -NoProfile -Command "$pkg = Get-Item '%ROOT%frontend\package.json'; $lock = Get-Item '%ROOT%frontend\node_modules\.package-lock.json' -ErrorAction SilentlyContinue; if (-not $lock -or $pkg.LastWriteTime -gt $lock.LastWriteTime) { exit 1 } else { exit 0 }"
    if errorlevel 1 (
        echo   package.json changed - syncing with npm install...
        pushd "%ROOT%frontend"
        call npm install
        if errorlevel 1 (
            echo   ERROR: npm install failed.
            popd
            pause
            exit /b 1
        )
        popd
    )
)

echo   OK - all prerequisites found.
echo.

echo [2/4] Starting backend on http://localhost:8000 ...
start "CLEARGATE Backend" cmd /k "cd /d %ROOT%backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 3 /nobreak >nul

echo [3/4] Starting frontend on http://localhost:3000 ...
start "CLEARGATE Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"

timeout /t 5 /nobreak >nul

echo [4/4] Opening browser...
start http://localhost:3000

echo.
echo  ============================================
echo   CLEARGATE Alpha is running!
echo.
echo   Frontend:  http://localhost:3000
echo   Backend:   http://localhost:8000
echo   API docs:  http://localhost:8000/docs
echo.
echo   Close the terminal windows to stop.
echo  ============================================
echo.
pause
