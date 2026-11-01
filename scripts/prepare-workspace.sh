#!/bin/bash
# Makes the folders the agent and the broker share. The agent runs as a different user in the same group, so both
# need to be able to write here. It runs as root in a container because Docker may have made a mount point as root.
# The agent's repo isn't made here, because git refuses to work in a folder another user owns.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

docker run --rm -v "$RUNTIME_DIR:/runtime" alpine:3.22 sh -c '
  cd /runtime
  mkdir -p control agent-workspace/requests agent-workspace/responses agent-workspace/reports agent-workspace/state
  chown 1000:1000 control agent-workspace agent-workspace/requests agent-workspace/responses agent-workspace/reports agent-workspace/state
  chmod 2775 agent-workspace agent-workspace/requests agent-workspace/responses agent-workspace/reports agent-workspace/state
  # Compose needs the file to exist, and an empty one means no self-hosted model.
  [ -e secrets/model_key.secret ] || { : >secrets/model_key.secret; chmod 400 secrets/model_key.secret; }
' </dev/null
