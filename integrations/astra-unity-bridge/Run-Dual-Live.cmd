@echo off
setlocal
cd /d "%~dp0build\bin\Release" || exit /b 1
if not exist "AstraUnityBridge.exe" (
    echo Run Build-Bridge.cmd first.
    pause
    exit /b 1
)
if exist "%~dp0..\lab-env\astra-body-license.txt" (
    AstraUnityBridge.exe --dual --license "%~dp0..\lab-env\astra-body-license.txt" %*
) else (
    AstraUnityBridge.exe --dual %*
)
pause
