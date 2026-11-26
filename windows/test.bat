@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Run windows\setup.bat first.
    exit /b 1
)
echo Running offline tests (no controller access)...
".venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
exit /b %ERRORLEVEL%
