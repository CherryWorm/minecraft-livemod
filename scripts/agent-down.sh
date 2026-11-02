#!/bin/bash
# Stops the agent and the broker's request loop. The game keeps running.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

./scripts/stack.sh --profile agent stop agent web egress world </dev/null
pid_file="$RUNTIME_DIR/broker/daemon.pid"
if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  kill "$(cat "$pid_file")"
fi
rm -f "$pid_file"
echo "agent and broker stopped"
