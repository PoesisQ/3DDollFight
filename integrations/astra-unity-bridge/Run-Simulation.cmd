@echo off
setlocal
cd /d "%~dp0build\bin\Release"
if not exist "AstraUnityBridge.exe" (
    echo Run Build-Bridge.cmd first.
    pause
    exit /b 1
)
AstraUnityBridge.exe --simulate %*
pause
