@echo off
REM Tail logs from all Cleargate containers. Ctrl+C to exit - services keep running.
setlocal
cd /d "%~dp0"
echo.
echo Tailing logs. Press Ctrl+C to stop watching (Cleargate keeps running).
echo.
docker compose -f docker-compose.yml -f docker-compose.pilot.yml --profile pilot logs -f --tail 100
endlocal
