#!/bin/bash
# Run from Git Bash on Windows. Copies only the mods to a scratch folder and compiles them there, so
# work in progress can be checked while a test is using the real repo in the dev distro.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
tar --exclude=build --exclude=.gradle --exclude=run -cf - mods | wsl.exe -d livingmod -- bash -c 'mkdir -p /srv/livingmod/dev && cd /srv/livingmod/dev && tar -xf -'
wsl.exe -d livingmod -- bash -s <<'EOF'
cd /srv/livingmod/repo
chmod +x /srv/livingmod/dev/mods/gradlew
MODS_DIR=/srv/livingmod/dev/mods ./scripts/stack.sh run --rm -T builder ./gradlew --no-daemon --console=plain build </dev/null 2>&1 \
  | grep -E 'error:|symbol:|location:|BUILD|^\s+\^|warning: \[' | cut -c1-170 | head -40
EOF
