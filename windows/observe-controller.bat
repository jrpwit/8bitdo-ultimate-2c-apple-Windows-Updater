@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Run windows\setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" tools\observe_controller.py %*
exit /b %ERRORLEVEL%
