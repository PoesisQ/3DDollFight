@echo off
setlocal
set "UNITY_EXE=D:\unity\Unity Hub\6000.3.10f1\Editor\Unity.exe"
if not exist "%UNITY_EXE%" (
    echo Unity Editor was not found at the configured path.
    echo In Unity Hub choose Add project from disk and select the UnityProject folder.
    pause
    exit /b 1
)
start "" "%UNITY_EXE%" -projectPath "%~dp0UnityProject" -executeMethod AstraUnity.Editor.AstraSkeletonSetup.OpenDemo
