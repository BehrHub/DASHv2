#!/usr/bin/env bash
set -euo pipefail

# Standalone preview — does NOT touch the existing Barrister/CleanDash project.
# Runs on its own port (8993) so it can sit next to the real app on 8992.

BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8993

if [ ! -d "$BUNDLE_DIR/.venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$BUNDLE_DIR/.venv"
  "$BUNDLE_DIR/.venv/bin/pip" install --quiet --upgrade pip
  "$BUNDLE_DIR/.venv/bin/pip" install --quiet streamlit pandas
fi

PID="$(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
[ -z "$PID" ] || kill "$PID" 2>/dev/null || true
sleep 1

cd "$BUNDLE_DIR"
echo "Starting preview on port $PORT ..."
nohup "$BUNDLE_DIR/.venv/bin/python3" -m streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.headless true \
  > "$BUNDLE_DIR/preview.log" 2>&1 </dev/null &

sleep 6

if curl -fsS "http://127.0.0.1:$PORT/" >/dev/null; then
  echo "SUCCESS"
  echo "VIEW: http://100.70.235.51:$PORT"
else
  echo "Server did not come up — showing log:"
  tail -n 100 "$BUNDLE_DIR/preview.log"
  exit 1
fi
