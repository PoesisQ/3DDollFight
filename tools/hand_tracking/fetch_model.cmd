@echo off
setlocal
cd /d "%~dp0"

if not exist "models" mkdir models

if exist "models\hand_landmarker.task" (
  echo Model already present, skipping download.
  exit /b 0
)

echo Downloading hand_landmarker.task ...
curl -L --fail --max-time 300 -o "models\hand_landmarker.task" "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
if errorlevel 1 (
  echo.
  echo [ERROR] Download failed. Fetch it manually and save to models\hand_landmarker.task
  pause
  exit /b 1
)

echo Done.
exit /b 0
