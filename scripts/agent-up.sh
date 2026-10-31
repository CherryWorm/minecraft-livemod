#!/bin/bash
# Starts the broker's request loop on this host, then the agent's container.
# Usage: agent-up.sh [--no-build]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

./scripts/prepare-workspace.sh

if [[ "${1:-}" != "--no-build" ]]; then
  ./scripts/stack.sh --profile agent build agent egress web >/dev/null </dev/null
fi

pid_file="$RUNTIME_DIR/broker/daemon.pid"
if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  kill "$(cat "$pid_file")"
  sleep 1
fi
nohup python3 -m broker.daemon >>"$RUNTIME_DIR/broker/daemon.log" 2>&1 </dev/null &
echo $! >"$pid_file"

./scripts/stack.sh --profile agent up -d --force-recreate agent </dev/null
echo "agent and broker started"
