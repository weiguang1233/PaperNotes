#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  papernote_python=python3
elif command -v python >/dev/null 2>&1; then
  papernote_python=python
else
  echo "Python 3.10 or newer is required." >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  "$papernote_python" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
echo "PaperNote companion service is ready. Start it with ./start.sh"
