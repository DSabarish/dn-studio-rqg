@echo off
echo [INFO] Stopping all DN-Studio server processes...

taskkill /FI "WINDOWTITLE eq DN-Studio Server" /T /F >nul 2>&1

REM Also kill any python process running dn_studio.server
for /f "tokens=2" %%p in ('wmic process where "commandline like '%%dn_studio.server%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /PID %%p /T /F >nul 2>&1
)

timeout /t 1 /nobreak >nul

echo [OK] DN-Studio server stopped.
pause
