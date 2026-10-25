@echo off
cd /d "%~dp0"
set "PAMOS_CLIENT=%~dp0.tools\Phira-Pro\PhiraPro-v0.8.2-pro.16-win64"
if not exist "%PAMOS_CLIENT%\phira-main.exe" (
  echo Run .venv\Scripts\python.exe scripts\install_phira_client.py first.
  pause
  exit /b 1
)
echo Client v0.8.2-pro.16. Source contract and client runtime acceptance are separate.
start "" /D "%PAMOS_CLIENT%" "%PAMOS_CLIENT%\phira-main.exe"
