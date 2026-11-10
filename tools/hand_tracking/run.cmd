@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python venv not found. Run install.cmd first.
  pause
  exit /b 1
)

if not exist "models\hand_landmarker.task" (
  echo [ERROR] Hand model not found. Run fetch_model.cmd first.
  pause
  exit /b 1
)

if "%~1"=="" (
  ".venv\Scripts\python.exe" run.py --start-bridge --preview
) else (
  ".venv\Scripts\python.exe" run.py %*
)

set RC=%errorlevel%
if not "%RC%"=="0" (
  echo.
  echo [ERROR] run.py exited with code %RC%
  pause
)
exit /b %RC%
