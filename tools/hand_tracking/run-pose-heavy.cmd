@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Hand environment missing. Run install.cmd first.
  pause
  exit /b 1
)
if not exist "..\gemini_tracking\models\pose_landmarker_heavy.task" (
  echo [ERROR] Pose Heavy model missing. See README.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py --start-bridge --preview --pose-heavy
if errorlevel 1 pause
