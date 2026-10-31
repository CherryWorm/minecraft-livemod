#!/bin/bash
# Run from Git Bash on Windows. Mirrors this working tree into the dev distro.
# The distro can't see Windows drives by design, so files are pushed in from this side.
# Scripts go over stdin because wsl.exe re-parses its command line and mangles $ expansions.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

tar --exclude=.git --exclude=runtime --exclude=.env --exclude=build --exclude=.gradle -cf - . \
  | wsl.exe -d livingmod -- sh -c 'cat > /tmp/livingmod-incoming.tar'

wsl.exe -d livingmod -- bash -s <<'EOF'
set -euo pipefail
incoming=$(mktemp -d)
tar -xf /tmp/livingmod-incoming.tar -C "$incoming"
rsync -a --delete --exclude=.env --exclude=build --exclude=.gradle --exclude=infra/mods.lock "$incoming/" /srv/livingmod/repo/
rm -rf "$incoming" /tmp/livingmod-incoming.tar
find /srv/livingmod/repo -name '*.sh' -exec chmod +x {} +
chmod +x /srv/livingmod/repo/mods/gradlew
echo "synced to livingmod:/srv/livingmod/repo"
EOF
