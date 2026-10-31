#!/bin/bash
# Development only: starts over with a blank world, no releases and an agent that remembers nothing.
# A copy of the old world goes to the backups folder first. It refuses to run on a stack with login
# checks on, because that means real players could be using it.
# Usage: reset-dev-world.sh --yes
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

if [[ "${PROXY_ONLINE_MODE:-true}" != "false" ]]; then
  echo "Refusing: login checks are on, so this may be a real server." >&2
  exit 1
fi
if [[ "${1:-}" != "--yes" ]]; then
  echo "This deletes the dev world and all release history. Run with --yes to go ahead." >&2
  exit 1
fi

./scripts/stack.sh --profile agent stop agent </dev/null >/dev/null 2>&1 || true
./scripts/stack.sh --profile shadow stop shadow shadow-proxy </dev/null >/dev/null 2>&1 || true
./scripts/stack.sh stop prod </dev/null >/dev/null

if [[ -d "$RUNTIME_DIR/prod/world" ]]; then
  mkdir -p "$RUNTIME_DIR/backups"
  tar --zstd -cf "$RUNTIME_DIR/backups/before-reset-$(date +%Y%m%d-%H%M%S).tar.zst" --exclude=session.lock \
    -C "$RUNTIME_DIR/prod" world
fi

for server in prod shadow; do
  rm -rf "${RUNTIME_DIR:?}/$server"/{world,live-assets,modules,polymer,config/conduit}
done
rm -rf "${RUNTIME_DIR:?}/broker"/{state.json,last.json,passed_gates.json,assembled,work,reports}
rm -rf "${RUNTIME_DIR:?}/releases/history"
rm -f "${RUNTIME_DIR:?}/timeline.jsonl" "$RUNTIME_DIR/control/decide_now" "$RUNTIME_DIR/control/agent_disabled"
rm -f "$RUNTIME_DIR/velocity/server-icon.png"
timeout 2 bash -c 'echo "velocity reload" >"$RUNTIME_DIR/velocity/console.pipe"' || true
# The agent's container runs as another user, so some of these files aren't ours to remove directly.
docker run --rm -v "$RUNTIME_DIR:/runtime" alpine:3.22 rm -rf /runtime/agent-workspace </dev/null
./scripts/prepare-workspace.sh
mkdir -p "$RUNTIME_DIR/releases/history" "$RUNTIME_DIR/broker"

./scripts/build-mods.sh current >/dev/null
./scripts/stack.sh up -d prod velocity </dev/null >/dev/null
echo "blank world started"
