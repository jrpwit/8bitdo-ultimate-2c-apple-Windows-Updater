@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo ============================================================
echo  8BitDo Ultimate 2C - Windows setup
echo ============================================================
echo.

rem The prebuilt hidapi wheels cover CPython 3.10-3.14 on 64-bit x64
rem Windows. An incompatible existing .venv caused the same MSVC error.
set "CHECK=import sys,platform; raise SystemExit(0 if sys.version_info[:2] in ((3,10),(3,11),(3,12),(3,13),(3,14)) and sys.maxsize.bit_length() == 63 and platform.machine().lower() in ('amd64','x86_64') else 1)"

echo Locating a supported 64-bit Python (3.12 recommended) ...
set "PY="
where py >nul 2>nul
if errorlevel 1 goto :try_path_python
call :try_py py -3.12-64
if defined PY goto :have_python
call :try_py py -3.13-64
if defined PY goto :have_python
call :try_py py -3.14-64
if defined PY goto :have_python
call :try_py py -3.11-64
if defined PY goto :have_python
call :try_py py -3.10-64
if defined PY goto :have_python
:try_path_python
call :try_py python
:have_python

if defined PY goto :check_existing_venv

rem No supported launcher found. A valid existing .venv can still be used.
if not exist ".venv\Scripts\python.exe" goto :no_python
".venv\Scripts\python.exe" -c "%CHECK%" >nul 2>nul
if errorlevel 1 goto :no_python
echo [1/4] Using the existing .venv (no supported launcher found) ...
goto :venv_ready

:check_existing_venv
if not exist ".venv\Scripts\python.exe" goto :create_venv
".venv\Scripts\python.exe" -c "%CHECK%" >nul 2>nul
if not errorlevel 1 goto :use_venv
echo.
echo [1/4] The existing .venv uses an unsupported Python build:
".venv\Scripts\python.exe" -c "import sys,platform; print('      Python', sys.version.split()[0], platform.machine())"
set "OLD=.venv.old-%RANDOM%%RANDOM%"
echo       Renaming it to %OLD% and creating a fresh .venv ...
move ".venv" "%OLD%" >nul
if errorlevel 1 goto :failed
goto :create_venv

:create_venv
echo [1/4] Creating private Python environment .venv ...
%PY% -m venv .venv
if errorlevel 1 goto :failed
goto :venv_ready

:use_venv
echo [1/4] Using existing .venv ...

:venv_ready
".venv\Scripts\python.exe" -c "import sys,platform; print('      Interpreter:', sys.version.split()[0], platform.machine())"

echo [2/4] Installing the Windows HID backend ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements-windows.txt
if errorlevel 1 goto :failed

echo [3/4] Installing optional joystick observation support ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements-observe.txt
if errorlevel 1 (
    echo.
    echo WARNING: the optional joystick observer has no prebuilt wheel here.
    echo          Flashing, backup, read and image-check tools are NOT affected.
    echo          Use Windows joy.cpl for manual controller testing, or install
    echo          Python 3.12 x64 and run this setup again for the observer.
    echo.
)

echo [4/4] Running offline safety tests ...
".venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo  Setup complete. Offline tests passed.
echo  Next: read WINDOWS.md and follow sections 4 onward.
echo ============================================================
exit /b 0

:try_py
%* -c "%CHECK%" >nul 2>nul
if not errorlevel 1 set "PY=%*"
goto :eof

:no_python
echo.
echo ERROR: No supported 64-bit CPython 3.10-3.14 was found.
echo.
echo Install the 64-bit Python 3.12 from:
echo   https://www.python.org/downloads/windows/
echo Tick "Add python.exe to PATH" and keep the Python launcher installed.
echo Do not use the Microsoft Store placeholder.
echo.
echo The hidapi package provides Windows wheels only for CPython 3.10-3.14
echo on 64-bit x64 Windows. Python 3.15, 32-bit Python, and ARM64 Python
echo would try to compile from source and need Microsoft Visual C++.
echo On Windows on ARM, install the x64 Python build.
echo.
echo Interpreters seen by the Python launcher:
py -0p
exit /b 1

:failed
echo.
echo ERROR: Setup failed. Read the message above; nothing was flashed.
echo If pip asked for Microsoft Visual C++, the Python build did not match
echo a prebuilt hidapi wheel. Install 64-bit Python 3.12 and rerun setup.
exit /b 1
