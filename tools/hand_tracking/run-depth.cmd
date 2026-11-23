@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Hand tracking environment not found. Run install.cmd first.
  pause
  exit /b 1
)
if not exist "models\hand_landmarker.task" (
  echo [ERROR] Hand model not found. Run fetch_model.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py --start-bridge --preview --depth
if errorlevel 1 pause
