@echo off
setlocal
cd /d "%~dp0"

if exist "models\pose_landmarker_full.task" (
  echo Pose model already present, skipping download.
  exit /b 0
)

if not exist "models" mkdir models

echo Downloading pose_landmarker_full.task ...
curl -L --fail --max-time 300 -o "models\pose_landmarker_full.task" "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task"
if errorlevel 1 (
  echo.
  echo [ERROR] Download failed. Fetch it manually and save to models\pose_landmarker_full.task
  pause
  exit /b 1
)

echo Done.
exit /b 0
