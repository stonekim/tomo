#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
PIP_CONFIG_FILE=/dev/null PIP_INDEX_URL=https://pypi.org/simple PIP_EXTRA_INDEX_URL='' .venv/bin/pip install -r deploy/requirements.lock
.venv/bin/pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m tomo.platform.cli migrate
exec .venv/bin/python -m uvicorn tomo.app:create_product_app --factory --host 127.0.0.1 --port "${TOMO_PORT:-8017}" --workers 1
