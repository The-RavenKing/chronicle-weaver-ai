#!/usr/bin/env bash
# Chronicle Weaver — start server
# Port 7823 | binds 0.0.0.0 so other machines on the LAN can reach it.
# Access from other machines: http://<this-machine-ip>:7823

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

HOST="${CW_HOST:-0.0.0.0}"
PORT="${CW_PORT:-7823}"

echo "Chronicle Weaver API starting on http://${HOST}:${PORT}"
echo "  UI : http://${HOST}:${PORT}/"
echo "  API docs: http://${HOST}:${PORT}/docs"
echo ""
echo "  LAN access: http://$(hostname -I | awk '{print $1}'):${PORT}/"
echo ""

exec uvicorn chronicle_weaver_ai.api:app \
  --host "$HOST" \
  --port "$PORT" \
  --reload
