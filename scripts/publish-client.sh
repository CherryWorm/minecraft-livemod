#!/bin/bash
# Run from Git Bash on Windows, after pushing anything that changes what's on friends' PCs: mods/companion, or the client mods in
# infra/mods.lock. Everyone gets it the next time they start the game, and anyone playing is told. It's the owner's PC that signs, because the
# signing key can install anything on friends' PCs, so it must never go on the server. See broker/client_release.py.
# Usage: LIVE_HOST=<server address> scripts/publish-client.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 WSL_UTF8=1
host=${LIVE_HOST:?Set LIVE_HOST to the address of the server.}
remote="root@$host"

# The distro has no GitHub key, and the repository is public anyway.
url=$(git remote get-url origin | sed "s#^git@github.com:#https://github.com/#")
commit=$(git ls-remote origin refs/heads/main | cut -f1)
echo "publishing $commit" >&2
module_key=$(ssh -o BatchMode=yes "$remote" cat /srv/livingmod/runtime/broker/signing/module_key.pub)

# Nobody has to restart, because the server keeps working with older versions, so they only hear about it if something really changed.
# Through a pipe, because wsl.exe hangs on a script redirected from a file.
cat scripts/publish-client-build.sh | wsl.exe -d livingmod -- bash -s -- "$url" "$commit" "$module_key" |
  ssh -o BatchMode=yes "$remote" '
    set -e
    folder=/srv/livingmod/runtime/friend-pack/update
    mkdir -p "$folder"
    before=$(grep "^file " "$folder/manifest" 2>/dev/null || true)
    tar -xf - -C "$folder" --no-same-owner
    chmod -R a+rX "$folder"
    sed -n 2p "$folder/manifest"
    grep -c "^file " "$folder/manifest"
    if [ -n "$before" ] && [ "$before" != "$(grep "^file " "$folder/manifest")" ]; then
      cd /srv/livingmod/repo
      sudo -u livingmod -H ./scripts/mc.sh tellraw @a "{\"text\":\"A new version of the mod is out, and you will get it the next time you start your game. If you have not downloaded the pack since 1 November, download it once more from the site.\",\"color\":\"gray\"}" >/dev/null || true
      echo "told everyone online"
    fi'
echo "published. Everyone gets it the next time they start the game." >&2
