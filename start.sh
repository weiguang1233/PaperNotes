#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "PaperNote needs its companion environment. Run ./setup.sh once." >&2
  exit 1
fi
if ! .venv/bin/python -c "import fastapi, pydantic, uvicorn" >/dev/null 2>&1; then
  echo "PaperNote dependencies are incomplete. Fix the network/proxy problem and run ./setup.sh again." >&2
  exit 1
fi
exec .venv/bin/python scripts/launcher.py --mode server
