@echo off
setlocal
cd /d "%~dp0"
if not exist "..\gemini_tracking\models" mkdir "..\gemini_tracking\models"
if exist "..\gemini_tracking\models\pose_landmarker_heavy.task" (
  echo Pose Heavy model is already present.
  exit /b 0
)
curl -L --fail --max-time 300 -o "..\gemini_tracking\models\pose_landmarker_heavy.task.download" "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/1/pose_landmarker_heavy.task"
if errorlevel 1 (
  echo [ERROR] Download failed. Retry after checking the network.
  pause
  exit /b 1
)
move /Y "..\gemini_tracking\models\pose_landmarker_heavy.task.download" "..\gemini_tracking\models\pose_landmarker_heavy.task" >nul
if errorlevel 1 exit /b 1
echo Pose Heavy model downloaded.
