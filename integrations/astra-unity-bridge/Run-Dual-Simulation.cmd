@echo off
setlocal
cd /d "%~dp0build\bin\Release" || exit /b 1
if not exist "AstraUnityBridge.exe" (
    echo Run Build-Bridge.cmd first.
    pause
    exit /b 1
)
AstraUnityBridge.exe --dual --simulate %*
pause
