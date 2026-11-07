@echo off
setlocal
cd /d "%~dp0"
if not exist "outputs\arcade-select\DollFight.exe" (
    echo No local Unity build yet. Open Start-Unity.cmd and build with:
    echo DollFight - Build Windows Demo
    pause
    exit /b 1
)
start "DollFight Unity" "outputs\arcade-select\DollFight.exe" -force-d3d12 -screen-width 1440 -screen-height 900 -screen-fullscreen 0 %*
