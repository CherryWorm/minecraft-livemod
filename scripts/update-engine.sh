#!/bin/bash
# Puts new engine code live with the world's own features, through every gate, the way the agent's own releases go.
# Run it as root on a rented server, because it stops and starts the broker. Players get one restart, at a safe moment.
# Usage: update-engine.sh
set -euo pipefail
cd "$(dirname "$0")/.."
user=livingmod
agent_repo=$(sudo -u "$user" -H python3 -c "from broker import daemon; print(daemon.AGENT_REPO)")

# Stopped between jobs, so the agent waits rather than having a release cut off, and nothing else is using the broker's work folder.
while pgrep -f 'broker\.promote' >/dev/null; do sleep 0.5; done
systemctl stop livingmod-broker
trap 'systemctl start livingmod-broker' EXIT

before=$(sudo -u "$user" -H git rev-parse HEAD)
sudo -u "$user" -H git pull --ff-only
# The agent's main is what's live, so this changes the engine and nothing else.
commit=$(git -c safe.directory='*' -C "$agent_repo" rev-parse main)
sudo -u "$user" -H env PYTHONDONTWRITEBYTECODE=1 python3 - "$commit" "engine$(date +%s)" <<'EOF'
import json, sys
from broker import daemon
report = daemon.promote(sys.argv[1], sys.argv[2])
print(json.dumps({key: report.get(key) for key in ("release", "result", "gate", "reason", "tier", "stages")}, indent=1))
sys.exit(0 if report.get("result") in ("released", "nothing_to_release") else 1)
EOF

systemctl start livingmod-broker
trap - EXIT
sudo -u "$user" -H ./scripts/agent-down.sh </dev/null
sudo -u "$user" -H ./scripts/agent-up.sh </dev/null

if ! git -c safe.directory='*' diff --quiet "$before" HEAD -- mods/companion/src/main infra/mods.lock; then
  sudo -u "$user" -H ./scripts/make-friend-pack.sh </dev/null
  echo "The companion changed, so everyone needs to download the pack from the site and import it again."
fi
