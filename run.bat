@echo off
REM Launch the Performance Monitor on Windows via uv.
setlocal

cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 (
    echo uv is not installed. Install it from https://docs.astral.sh/uv/ and rerun:
    echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    exit /b 1
)

uv run system-monitor %*
endlocal
