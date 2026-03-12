@echo off
REM DN-Studio launcher: stop any existing server, start a fresh one, open browser

REM Change to script directory
cd /d "%~dp0"

REM Activate virtual environment
IF EXIST "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) ELSE (
    echo [ERROR] venv not found. Please create it first:
    echo   python -m venv venv
    echo   venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo [INFO] Checking for existing DN-Studio server windows...

REM Kill any previous server window we started (by title)
REM This is safe even if no such window exists.
taskkill /FI "WINDOWTITLE eq DN-Studio Server" /T /F >nul 2>&1

echo [INFO] Starting fresh DN-Studio server...

REM Start Flask server in a new window
start "DN-Studio Server" cmd /k "python -m dn_studio.server"

REM Small delay to let the server start
timeout /t 3 /nobreak >nul

REM Open the app in the default browser
start "" "http://localhost:5050"

echo.
echo [OK] DN-Studio server started and browser opened.
echo You can close this window if you don't need it anymore.
pause

