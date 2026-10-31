#!/bin/bash
# Builds our mods in a container and publishes the server jars to a release folder.
# Usage: build-mods.sh [current|candidate]
set -euo pipefail
cd "$(dirname "$0")/.."
target=${1:-current}

# stdin is closed so the container can't swallow the rest of a calling script.
./scripts/stack.sh run --rm -T builder ./gradlew --no-daemon --console=plain build </dev/null

set -a
. ./.env
set +a
release="$RUNTIME_DIR/releases/$target"
rm -f "$release"/*.jar
# Only server mods go here. The companion and client modules reach players by other routes.
for mod in conduit; do
  find "mods/$mod/build/libs" -maxdepth 1 -name '*.jar' ! -name '*-sources.jar' -exec cp {} "$release/" \;
done
echo "published to $release:"
ls -l "$release"
