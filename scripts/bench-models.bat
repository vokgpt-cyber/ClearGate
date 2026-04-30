@echo off
REM ============================================================================
REM bench-models.bat - run the Cleargate benchmark across N Ollama models
REM                    and produce a side-by-side comparison report.
REM ----------------------------------------------------------------------------
REM Designed to run on PC #2 alongside the local profile (start-local.bat).
REM
REM What it does, per model in the list below:
REM   1) Pull the model in Ollama if missing.
REM   2) Restart the local backend container with OLLAMA_MODEL=<model>.
REM   3) Wait for backend healthy.
REM   4) Run scripts\benchmark_v040.py --tag <safe_model_name>
REM      (writes bench-results\bench-<ts>-<safe>.json + .md per model)
REM
REM After all models, runs compare_bench_results.py to produce a single
REM Markdown comparison table.
REM
REM Usage (defaults shown):
REM   scripts\bench-models.bat
REM
REM Override the model list:
REM   set MODELS=qwen2.5:7b-instruct-q4_K_M gemma3:27b qwen2.5:14b-instruct-q4_K_M
REM   scripts\bench-models.bat
REM
REM Override admin password (default "admin"):
REM   set ADMIN_PASSWORD=mySecret
REM   scripts\bench-models.bat
REM ============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0\.."

if "%MODELS%"=="" set "MODELS=qwen2.5:7b-instruct-q4_K_M gemma3:27b"
if "%ADMIN_PASSWORD%"=="" set "ADMIN_PASSWORD=admin"

set "BENCH_DIR=bench-results"
if not exist "%BENCH_DIR%" mkdir "%BENCH_DIR%"

echo.
echo ============================================================================
echo   Cleargate model comparison benchmark
echo   Models to test: %MODELS%
echo   Backend admin login password: %ADMIN_PASSWORD% (set ADMIN_PASSWORD env var to change)
echo ============================================================================

REM Verify prerequisites once.
docker info >nul 2>&1 || (echo FAIL: Docker not running. & exit /b 1)
curl -fsS http://localhost:11434/api/tags >nul 2>&1 || (echo FAIL: Ollama not on :11434. & exit /b 1)
where python >nul 2>&1 || (echo FAIL: python not in PATH. & exit /b 1)

set "INPUTS_LIST="
set "MODEL_COUNT=0"

for %%M in (%MODELS%) do (
    set /a MODEL_COUNT+=1
    set "MODEL=%%M"
    REM Sanitise the model name for filenames: replace : / with _
    set "SAFE=!MODEL::=_!"
    set "SAFE=!SAFE:/=_!"

    echo.
    echo ----------------------------------------------------------------------------
    echo   [Model !MODEL_COUNT!] !MODEL!
    echo ----------------------------------------------------------------------------

    REM 1) Pull if missing.
    curl -fsS http://localhost:11434/api/tags | findstr /C:"!MODEL!" >nul 2>&1
    if errorlevel 1 (
        echo Pulling !MODEL! ^(can take 5-15 minutes^)...
        ollama pull "!MODEL!"
        if errorlevel 1 (
            echo   FAIL: ollama pull failed for !MODEL!. Skipping.
            goto :next_model
        )
    ) else (
        echo Model already present in Ollama.
    )

    REM 2) Restart backend with new OLLAMA_MODEL env override.
    echo Restarting backend with OLLAMA_MODEL=!MODEL! ...
    set "OLLAMA_MODEL=!MODEL!"
    docker compose -f docker-compose.local.yml up -d --no-deps backend >nul 2>&1
    if errorlevel 1 (
        echo   FAIL: docker compose up failed. Skipping.
        goto :next_model
    )

    REM 3) Wait for backend healthy via nginx.
    set /a TRIES=0
    :wait_health
    set /a TRIES+=1
    curl -fsS http://localhost/health >nul 2>&1
    if not errorlevel 1 goto :health_ok
    if !TRIES! geq 36 (
        echo   FAIL: backend did not become healthy in 3 minutes. Skipping !MODEL!.
        goto :next_model
    )
    timeout /t 5 /nobreak >nul
    goto :wait_health

    :health_ok
    echo Backend healthy. Starting benchmark...

    REM 4) Run benchmark with model tag.
    python scripts\benchmark_v040.py ^
        --base-url http://localhost ^
        --password "%ADMIN_PASSWORD%" ^
        --tag "!SAFE!" ^
        --min-precision 0.0 ^
        --min-recall 0.0
    if errorlevel 1 (
        echo   WARN: benchmark exited non-zero ^(thresholds not met or error^), continuing anyway.
    )

    REM Find the latest JSON output that matches the tag.
    for /f "delims=" %%F in ('dir /b /o-d "%BENCH_DIR%\bench-*-!SAFE!.json" 2^>nul') do (
        set "LATEST=%BENCH_DIR%\%%F"
        goto :got_latest
    )
    echo   WARN: could not find bench output JSON for !SAFE!.
    goto :next_model

    :got_latest
    echo   Got: !LATEST!
    set "INPUTS_LIST=!INPUTS_LIST! !LATEST!"

    :next_model
)

REM 5) Combine into one comparison report.
if "!INPUTS_LIST!"=="" (
    echo.
    echo No successful model runs to compare. Aborting.
    exit /b 1
)

set "STAMP=%DATE:~-4%%DATE:~3,2%%DATE:~0,2%-%TIME:~0,2%%TIME:~3,2%"
set "STAMP=%STAMP: =0%"
set "REPORT=%BENCH_DIR%\comparison-%STAMP%.md"

echo.
echo ----------------------------------------------------------------------------
echo Building comparison report...
echo ----------------------------------------------------------------------------
python scripts\compare_bench_results.py --inputs !INPUTS_LIST! --output "%REPORT%"
if errorlevel 1 (
    echo FAIL: compare script exited non-zero.
    exit /b 1
)

echo.
echo ============================================================================
echo   DONE
echo   Comparison report: %REPORT%
echo   Per-model JSONs:   %BENCH_DIR%\bench-*-^<model^>.json
echo ============================================================================
endlocal
exit /b 0
