@echo off
REM Show Cleargate container status and a quick health-check of the backend.
setlocal
cd /d "%~dp0"
echo.
echo === Container state ===
docker compose -f docker-compose.yml -f docker-compose.pilot.yml --profile pilot ps
echo.
echo === Backend health via nginx (what pilot users hit - expect JSON) ===
curl -s http://localhost/health
echo.
echo.
echo === Backend health direct (bypass nginx - expect JSON) ===
curl -s http://localhost:8000/health
echo.
echo.
pause
endlocal
