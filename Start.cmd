@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto ready
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 -m venv .venv
goto checkvenv
:usepython
python -m venv .venv
:checkvenv
if not exist ".venv\Scripts\python.exe" goto failed
:ready
".venv\Scripts\python.exe" bootstrap.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup failed. Install Python 3.11 or newer, then see README.md.
pause
exit /b 1
