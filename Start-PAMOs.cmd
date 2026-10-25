@echo off
cd /d "%~dp0"
call scripts\environment.cmd
if errorlevel 1 (pause & exit /b 1)
set "PYTHONPATH=%PAMOS_ROOT%\src;%PAMOS_ROOT%"
if not exist "web\dist\index.html" (
  echo Please run Install-PAMOs.cmd to build the local interface.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8765 after the server reports startup complete.
"%VIRTUAL_ENV%\Scripts\python.exe" -m phiaimadeos --root "%PAMOS_ROOT%"
pause
