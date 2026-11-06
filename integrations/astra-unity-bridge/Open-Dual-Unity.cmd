@echo off
setlocal
set "UNITY_EXE=D:\unity\Unity Hub\6000.3.10f1\Editor\Unity.exe"
if not exist "%UNITY_EXE%" (
    echo Open UnityProject in Unity Hub and open Assets/AstraUnity/DualCameraDemo.unity.
    pause
    exit /b 1
)
start "" "%UNITY_EXE%" -projectPath "%~dp0UnityProject" -executeMethod AstraUnity.Editor.AstraSkeletonSetup.OpenDualDemo
