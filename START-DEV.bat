@echo off
title VELUM - DEV

echo.
echo  ============================================
echo   VELUM - DEV MODE
echo  ============================================
echo.

set ROOT=%~dp0

echo [1/5] Switching to dev branch...
if exist "%ROOT%.git\index.lock" del /f "%ROOT%.git\index.lock"
pushd "%ROOT%"
git checkout dev
if errorlevel 1 (
    echo   ERROR: could not switch to dev
    popd
    pause
    exit /b 1
)
popd
echo   OK
echo.

echo [2/5] Checking prerequisites...
if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
    echo   ERROR: Backend venv not found.
    pause
    exit /b 1
)
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: npm not found.
    pause
    exit /b 1
)
echo   OK
echo.

echo [3/5] Starting backend on http://localhost:8000 ...
start "VELUM Backend DEV" cmd /k "cd /d %ROOT%backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 3 /nobreak >nul

echo [4/5] Starting frontend on http://localhost:3000 ...
start "VELUM Frontend DEV" cmd /k "cd /d %ROOT%frontend && npm run dev"

timeout /t 5 /nobreak >nul

echo [5/5] Opening browser...
start http://localhost:3000

echo.
echo  ============================================
echo   VELUM DEV is running!
echo.
echo   Frontend:  http://localhost:3000
echo   Backend:   http://localhost:8000
echo   Branch:    dev
echo.
echo   Close Backend/Frontend windows to stop.
echo  ============================================
echo.
pause
