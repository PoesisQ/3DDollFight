@echo off
setlocal
cd /d "%~dp0build\bin\Release" || exit /b 1
if not exist "AstraUnityBridge.exe" (
    echo Build the Astra bridge first.
    pause
    exit /b 1
)
if defined ASTRA_BODY_LICENSE goto specified
if not defined ASTRA_LAB_ENV goto trial
if not exist "%ASTRA_LAB_ENV%\astra-body-license.txt" goto trial
AstraUnityBridge.exe --license "%ASTRA_LAB_ENV%\astra-body-license.txt" %*
goto done
:specified
AstraUnityBridge.exe --license "%ASTRA_BODY_LICENSE%" %*
goto done
:trial
AstraUnityBridge.exe %*
:done
pause
