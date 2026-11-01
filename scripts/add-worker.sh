#!/bin/bash
# Lets another machine run builders, by making it a token. Only the token's hash is kept, so this is the one time you see it.
# Usage: sudo ./scripts/add-worker.sh <name> <slots>
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root."
  exit 1
fi
name=${1:?Give the machine a name}
slots=${2:-2}

file="$RUNTIME_DIR/control/workers.json"
token=$(python3 - "$file" "$name" "$slots" <<'PY'
import hashlib, json, pathlib, secrets, sys
path, name, slots = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
machines = json.loads(path.read_text()) if path.exists() else {}
token = secrets.token_urlsafe(32)
machines[name] = {"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "slots": slots}
path.write_text(json.dumps(machines, indent=1))
print(token)
PY
)
chmod 644 "$file"

echo "$name's token, which it asks for when it starts. It won't be shown again:"
echo "$token"
echo
echo "On that machine, in a checkout of this repository at the same commit as this server:"
echo "  ./scripts/worker-up.sh https://${SITE_ADDRESS:-this-server} $slots self_hosted"
