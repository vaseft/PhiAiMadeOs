@echo off
cd /d "%~dp0"
call scripts\environment.cmd
if errorlevel 1 (
  pause
  exit /b 1
)
echo PAMOs development environment: %PAMOS_ROOT%
echo Python, CUDA PyTorch, audio tools and MCP are available in this terminal.
echo Project documentation: docs\34_WINDOWS_ENVIRONMENT.md
cmd /k
