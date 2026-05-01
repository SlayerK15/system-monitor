@echo off
REM Launch the Performance Monitor on Windows.
setlocal

cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
)

call .venv\Scripts\activate.bat

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

python app.py %*
endlocal
