@echo off
setlocal
cd /d "%~dp0"
if not exist "outputs\unity-build\DollFight.exe" (
    echo No local Unity build yet. Open Start-Unity.cmd and build with:
    echo DollFight - Build Windows Demo
    pause
    exit /b 1
)
start "DollFight Unity" "outputs\unity-build\DollFight.exe" -screen-width 1280 -screen-height 1000 -screen-fullscreen 0
