@echo off
cd /d "%~dp0"
call scripts\environment.cmd
if errorlevel 1 (pause & exit /b 1)
set "npm_config_cache=%PAMOS_ROOT%\.cache\npm"
echo Installing the workbench into the existing isolated Python environment...
"%PAMOS_ROOT%\.tools\uv\bin\uv.exe" pip install --python "%VIRTUAL_ENV%\Scripts\python.exe" -e ".[mcp]"
if errorlevel 1 (pause & exit /b 1)
pushd web
call npm ci --no-audit --no-fund
if errorlevel 1 (popd & pause & exit /b 1)
call npm run build
if errorlevel 1 (popd & pause & exit /b 1)
popd
echo Installation and production packaging finished. No tests were run by this script.
echo Start-PAMOs.cmd opens the local workbench server.
pause
