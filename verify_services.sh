#!/usr/bin/env bash
# Wait for usable dependencies, not merely running containers.
set -euo pipefail
TIMEOUT="${STARTUP_TIMEOUT_SECONDS:-900}"
[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || { echo "Invalid startup timeout" >&2; exit 1; }
DEADLINE=$((SECONDS + TIMEOUT))
while (( SECONDS < DEADLINE )); do
  if curl --fail --silent --max-time 10 http://127.0.0.1:3000/ >/dev/null && \
     curl --fail --silent --max-time 10 http://127.0.0.1:8080/ready >/dev/null; then
    echo "Dashboard and core call backend are ready."
    exit 0
  fi
  sleep 10
done
echo "Startup timed out. Inspect: docker compose ps; journalctl -u voice-agent" >&2
exit 1
