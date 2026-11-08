@echo off
setlocal
set "UNITY_EXE=%DOLLFIGHT_UNITY_EDITOR%"
if not defined UNITY_EXE set "UNITY_EXE=D:\unity\Unity Hub\6000.3.27f1\Unity.exe"
if not exist "%UNITY_EXE%" (
    echo Open the repository unity folder in Unity Hub, then Assets/AstraUnity/SingleCameraGame.unity.
    pause
    exit /b 1
)
start "" "%UNITY_EXE%" -projectPath "%~dp0..\..\unity" -executeMethod AstraUnity.Editor.AstraLiveScene.Open
