@echo off
title Open - News Server
REM ============================================================
REM  Open - News : local Windows launcher
REM  Place this file in the project root (same folder that
REM  contains the "server" and "site" folders), double-click it.
REM ============================================================

cd /d "%~dp0"

echo.
echo  ==============================================
echo    OPEN - NEWS  ·  local server starting...
echo  ==============================================
echo.

REM ---- 1. check Python is installed ----
where python >nul 2>nul
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo  Install it from https://www.python.org/downloads/
    echo  IMPORTANT: tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

REM ---- 2. check project structure ----
if not exist "server\app.py" (
    echo  [ERROR] server\app.py not found.
    echo  Put run.bat in the project root folder ^(the one
    echo  containing the "server" and "site" folders^).
    echo.
    pause
    exit /b 1
)

REM ---- 3. create a private virtual environment (first run only) ----
if not exist ".venv\Scripts\python.exe" (
    echo  [SETUP] Creating virtual environment - first run only...
    python -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Could not create virtual environment.
        pause
        exit /b 1
    )
)

REM ---- 4. install dependencies (quick if already present) ----
echo  [SETUP] Checking dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check flask
if errorlevel 1 (
    echo  [ERROR] Could not install Flask. Check your internet connection.
    pause
    exit /b 1
)

REM ---- 5. set your admin password here (change any time) ----
if not defined ADMIN_PASSWORD set ADMIN_PASSWORD=change-me-please

REM ---- 6. run ----
set PORT=8080
echo.
echo  Site    :  http://localhost:%PORT%/
echo  Paper   :  http://localhost:%PORT%/paper.html
echo  Archives:  http://localhost:%PORT%/archives.html
echo.
echo  Admin   :  http://localhost:%PORT%/admin   ^(password = ADMIN_PASSWORD in this file^)
echo.
echo  Press CTRL+C in this window to stop the server.
echo  ----------------------------------------------
echo.

start "" http://localhost:%PORT%/

".venv\Scripts\python.exe" server\app.py

echo.
echo  Server stopped.
pause
