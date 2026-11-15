@echo off
setlocal
cd /d "%~dp0..\.."
"%~dp0..\hand_tracking\.venv\Scripts\python.exe" "%~dp0gemini_run.py" %*
