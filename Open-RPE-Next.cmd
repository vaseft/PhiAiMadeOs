@echo off
cd /d "%~dp0"
if not exist ".local\upstreams\rpe-next\tools\serve.mjs" (
  echo The pinned RPE Next source is missing. See docs\34_WINDOWS_ENVIRONMENT.md.
  pause
  exit /b 1
)
set "RPE_PORT=4173"
node .local\upstreams\rpe-next\tools\serve.mjs --open
pause
