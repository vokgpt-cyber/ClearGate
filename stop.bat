@echo off
REM Stop Cleargate. Containers and the LLM model survive - start.bat brings them back.
setlocal
cd /d "%~dp0"
docker compose -f docker-compose.yml -f docker-compose.pilot.yml --profile pilot down
echo.
echo Cleargate stopped.
echo.
pause
endlocal
