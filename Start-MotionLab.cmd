@echo off
setlocal
cd /d "%~dp0"
uv sync --locked
if errorlevel 1 goto failed
uv run --locked python -m dollfight.server --open
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Motion Lab could not start. Check the message above.
pause
exit /b 1
