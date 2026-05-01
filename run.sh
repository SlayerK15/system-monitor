#!/usr/bin/env bash
# Launch the Performance Monitor on macOS or Linux.
set -e

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

exec python app.py "$@"
