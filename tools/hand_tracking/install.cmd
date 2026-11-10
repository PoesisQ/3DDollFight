@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uv not found on PATH. See https://docs.astral.sh/uv/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating Python 3.10 environment ...
  uv venv .venv --python 3.10
  if errorlevel 1 goto failed
)

echo [2/2] Installing MediaPipe ...
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto failed

echo.
echo Done. Next: run fetch_model.cmd to download the hand model.
exit /b 0

:failed
echo.
echo [ERROR] Install failed. Check your network connection and that uv works.
pause
exit /b 1
