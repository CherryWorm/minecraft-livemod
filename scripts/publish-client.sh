#!/bin/bash
# Run from Git Bash on Windows, after pushing anything that changes what's on friends' PCs: mods/companion, or the client mods in
# infra/mods.lock. Everyone gets it the next time they start the game. It's the owner's PC that signs, because the signing key can install
# anything on friends' PCs, so it must never go on the server. See broker/client_release.py.
# Usage: LIVE_HOST=<server address> scripts/publish-client.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 WSL_UTF8=1
host=${LIVE_HOST:?Set LIVE_HOST to the server's address.}
remote="root@$host"

url=$(git remote get-url origin)
commit=$(git ls-remote origin refs/heads/main | cut -f1)
echo "publishing $commit" >&2
module_key=$(ssh -o BatchMode=yes "$remote" cat /srv/livingmod/runtime/broker/signing/module_key.pub)

wsl.exe -d livingmod -- bash -s -- "$url" "$commit" "$module_key" <scripts/publish-client-build.sh |
  ssh -o BatchMode=yes "$remote" 'set -e; folder=/srv/livingmod/runtime/friend-pack/update; mkdir -p "$folder"; tar -xf - -C "$folder" --no-same-owner; chmod -R a+rX "$folder"; sed -n 2p "$folder/manifest"; grep -c "^file " "$folder/manifest"'
echo "published. Everyone gets it the next time they start the game." >&2
