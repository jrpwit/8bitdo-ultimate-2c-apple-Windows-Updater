@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "OUT=work\windows-evidence"
if not exist "work" mkdir "work"
if not exist "%OUT%" mkdir "%OUT%"

echo ============================================================
echo  Windows evidence collector (read-only)
echo ============================================================
echo.
echo This records environment/tool output only. It never flashes,
echo erases, programs or resets the controller.
echo.

(
    echo Date: %DATE% %TIME%
    echo.
    ver
    echo.
    where python
    python --version
    echo.
    where py
    py -0p
    py -3 --version
    echo.
    if exist ".venv\Scripts\python.exe" .venv\Scripts\python.exe -c "import sys,platform; print('venv:', sys.version.split()[0], platform.machine())"
) > "%OUT%\environment.txt" 2>&1

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv is missing. Run windows\setup.bat first.
    echo Evidence folder: %OUT%
    exit /b 1
)

echo [1/3] Running offline tests ...
call windows\test.bat > "%OUT%\tests.txt" 2>&1
echo       tests exit code: %ERRORLEVEL%

echo [2/3] Listing HID devices ...
call windows\list-devices.bat > "%OUT%\devices.txt" 2>&1
echo       list exit code: %ERRORLEVEL%

echo [3/3] Reading firmware version (no writes) ...
call windows\read-firmware.bat > "%OUT%\read-firmware.txt" 2>&1
echo       read exit code: %ERRORLEVEL%

echo.
echo ============================================================
echo  Evidence written to: %OUT%
echo ============================================================
echo  Files:
echo    environment.txt
echo    tests.txt
echo    devices.txt
echo    read-firmware.txt
echo.
echo  These logs contain environment text and HID interface paths only.
echo  Do not add firmware images, full flash dumps or Bluetooth addresses.
echo.
echo  Hardware flashing must be done manually by following WINDOWS.md
echo  sections 6 and 7. This collector never writes to the controller.
exit /b 0
