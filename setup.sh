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

papernote_major=$(.venv/bin/python -c 'import sys; print(sys.version_info[0])')
papernote_minor=$(.venv/bin/python -c 'import sys; print(sys.version_info[1])')
if [ "$papernote_major" -lt 3 ] || { [ "$papernote_major" -eq 3 ] && [ "$papernote_minor" -lt 10 ]; }; then
  echo "PaperNote requires Python 3.10 or newer." >&2
  exit 1
fi

# Do not guess a local proxy. Use PAPERNOTE_PIP_PROXY only when the user has
# explicitly supplied a verified HTTP proxy.
if [ -n "${PAPERNOTE_PIP_PROXY:-}" ]; then
  .venv/bin/python -m pip --isolated install --disable-pip-version-check --timeout 60 --retries 2 --proxy "$PAPERNOTE_PIP_PROXY" -r requirements.txt
else
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
    -u PIP_PROXY -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL -u PIP_TRUSTED_HOST -u PIP_CONFIG_FILE \
    .venv/bin/python -m pip --isolated install --disable-pip-version-check --timeout 60 --retries 2 -r requirements.txt
fi
.venv/bin/python -c "import fastapi, pydantic, uvicorn; print('Runtime dependency check passed.')"
echo "PaperNote companion service is ready. Start it with ./start.sh"
