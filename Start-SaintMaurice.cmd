@echo off
setlocal
cd /d "%~dp0"
uv sync --locked
if errorlevel 1 goto failed
git lfs pull
if errorlevel 1 goto failed
uv run --locked python tools/prepare_unity.py
if errorlevel 1 goto failed
uv run --locked python tools/prepare_saint_maurice.py
if errorlevel 1 goto failed
powershell -NoProfile -File "%~dp0tools\open_unity.ps1" -ExecuteMethod DollFight.Environments.Editor.SaintMauriceScene.OpenDuel -D3D12
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Saint Maurice could not start. See docs/saint-maurice-scene.md.
pause
exit /b 1
