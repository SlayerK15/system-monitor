#!/usr/bin/env bash
# Launch the Performance Monitor on macOS or Linux via uv.
set -e

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it from https://docs.astral.sh/uv/ and rerun."
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

exec uv run system-monitor "$@"
