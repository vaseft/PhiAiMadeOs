@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo PAMOs Python environment is missing. Run Install-PAMOs.cmd first.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\launch_training.py"
exit /b
