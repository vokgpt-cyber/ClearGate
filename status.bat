@echo off
REM Show Cleargate container status and a quick health-check of the backend.
setlocal
cd /d "%~dp0"
echo.
echo === Container state ===
docker compose -f docker-compose.yml -f docker-compose.pilot.yml --profile pilot ps
echo.
echo === Backend health (expect a JSON response) ===
curl -s http://localhost:8000/health
echo.
echo.
pause
endlocal
