#!/bin/bash
# Starts the broker's request loop on this host, then the agent's container.
# Usage: agent-up.sh [--no-build]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

workspace="$RUNTIME_DIR/agent-workspace"
# The agent runs as a different user in the same group, so both need to be able to write here. Its repo
# isn't made here, because git refuses to work in a folder another user owns.
mkdir -p "$workspace"/{requests,responses,reports,state} "$RUNTIME_DIR/control"
chmod 2775 "$workspace" "$workspace"/{requests,responses,reports,state}

if [[ "${1:-}" != "--no-build" ]]; then
  ./scripts/stack.sh --profile agent build agent >/dev/null </dev/null
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
