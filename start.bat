@echo off
setlocal EnableExtensions
rem Alfa Insight - start on Windows without Docker. ASCII-only on purpose: cmd.exe misreads UTF-8 batch files.
cd /d "%~dp0"
title Alfa Insight
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "services\insight\server.py" goto :wrongdir

rem ---- 1. find Python (3.12 preferred, 3.11-3.14 accepted) ----
set "PY="
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.12"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set "PY="%ProgramFiles%\Python312\python.exe""
if not defined PY (
  py -3.13 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=py -3.13"
)
if not defined PY (
  py -3.11 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=py -3.11"
)
if not defined PY (
  py -3.14 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=py -3.14"
)
if not defined PY goto :nopython

echo Python:
%PY% --version
if errorlevel 1 goto :nopython

rem ---- 2. dependencies ----
echo.
echo Installing dependencies, first run takes 1-2 minutes...
%PY% -m pip --version >nul 2>&1
if errorlevel 1 %PY% -m ensurepip --upgrade
%PY% -m pip install --disable-pip-version-check -r requirements.lock.txt
if errorlevel 1 goto :piperror

rem ---- 3. free port ----
set "PORT=8080"
netstat -ano -p tcp | findstr ":8080 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 set "PORT=8090"

rem ---- 4. run ----
echo.
echo ==================================================================
echo   Alfa Insight:  http://localhost:%PORT%/
echo   Login: demo    Password: demo
echo   The browser opens in about 15 seconds. Stop the server: Ctrl+C
echo ==================================================================
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 15; Start-Process 'http://localhost:%PORT%/'"
%PY% -m services.insight.server
echo.
echo Server stopped. If you see an error above, send a screenshot of this window.
pause
exit /b 0

:wrongdir
echo start.bat must lie in the project folder next to the "services" folder.
echo Unpack the whole archive and run start.bat from the alfa-insight folder.
pause
exit /b 1

:nopython
echo Python 3.12 was not found.
echo Install it: https://www.python.org/downloads/release/python-3129/
echo   "Windows installer 64-bit", tick "Add python.exe to PATH", then run start.bat again.
pause
exit /b 1

:piperror
echo Failed to install dependencies. Check the internet connection and send a screenshot of this window.
pause
exit /b 1
