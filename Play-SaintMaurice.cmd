@echo off
setlocal
cd /d "%~dp0"
if not exist "outputs\arcade-select\DollFight.exe" (
    echo Build the latest three-stage player first: DollFight - Build Windows Demo
    pause
    exit /b 1
)
start "DollFight - Saint Maurice" "outputs\arcade-select\DollFight.exe" -dollfightMenuStage saint-maurice -force-d3d12 -screen-width 1440 -screen-height 900 -screen-fullscreen 0 %*
