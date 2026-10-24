@echo off
rem Configure only this terminal; no system-wide PATH or registry changes.
for %%I in ("%~dp0..") do set "PAMOS_ROOT=%%~fI"
if not exist "%PAMOS_ROOT%\.venv\Scripts\python.exe" (
  echo Python environment is missing. See docs\34_WINDOWS_ENVIRONMENT.md.
  exit /b 1
)
set "VIRTUAL_ENV=%PAMOS_ROOT%\.venv"
set "PATH=%VIRTUAL_ENV%\Scripts;%PAMOS_ROOT%\.tools\uv\bin;%PATH%"
for /d %%D in ("%PAMOS_ROOT%\.tools\ffmpeg\*") do if exist "%%~fD\bin\ffmpeg.exe" set "PATH=%%~fD\bin;%PATH%"
set "TEMP=%PAMOS_ROOT%\.local\tmp"
set "TMP=%TEMP%"
set "UV_CACHE_DIR=%PAMOS_ROOT%\.cache\uv"
set "UV_PYTHON_INSTALL_DIR=%PAMOS_ROOT%\.runtime\python"
set "PIP_CACHE_DIR=%PAMOS_ROOT%\.cache\pip"
set "XDG_CACHE_HOME=%PAMOS_ROOT%\.cache"
set "NUMBA_CACHE_DIR=%PAMOS_ROOT%\.cache\numba"
set "TORCH_HOME=%PAMOS_ROOT%\.cache\torch"
set "HF_HOME=%PAMOS_ROOT%\.cache\huggingface"
set "MPLCONFIGDIR=%PAMOS_ROOT%\.cache\matplotlib"
set "PYTHONUTF8=1"
set "PAMOs_RPE_WORKSPACE=%PAMOS_ROOT%\.local\charts"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%PAMOs_RPE_WORKSPACE%" mkdir "%PAMOs_RPE_WORKSPACE%"
exit /b 0
