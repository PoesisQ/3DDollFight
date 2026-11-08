@echo off
setlocal
cd /d "%~dp0build\bin\Release" || exit /b 1
if not exist "AstraUnityBridge.exe" (
    echo Run Build-Bridge.cmd first. See README.md for ASTRA_LAB_ENV.
    pause
    exit /b 1
)
if defined ASTRA_BODY_LICENSE goto specified_license
if not defined ASTRA_LAB_ENV goto trial
if not exist "%ASTRA_LAB_ENV%\astra-body-license.txt" goto trial
AstraUnityBridge.exe --dual --license "%ASTRA_LAB_ENV%\astra-body-license.txt" %*
goto done
:specified_license
AstraUnityBridge.exe --dual --license "%ASTRA_BODY_LICENSE%" %*
goto done
:trial
AstraUnityBridge.exe --dual %*
:done
pause
