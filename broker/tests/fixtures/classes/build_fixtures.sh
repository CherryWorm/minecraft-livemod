#!/bin/bash
# Rebuilds the prebuilt test classes from src/ and the two feature fixtures, against the real game's jars, in a one-off
# JDK container. Only needed when a fixture changes. Run inside the distro, then copy the classes back to Windows,
# because the next wsl-sync would delete anything that only exists in the distro.
# Usage: build_fixtures.sh [output folder, default: this folder]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../.." && pwd)
mkdir -p "${1:-$here}"
out=$(cd "${1:-$here}" && pwd)
caches="$(grep ^RUNTIME_DIR= "$repo/.env" | cut -d= -f2)/cache/gradle/caches"
rm -rf "$out/gm"
docker run --rm -u "$(id -u):$(id -g)" -v "$repo:/repo:ro" -v "$caches:/caches:ro" -v "$out:/out" -w /repo \
  eclipse-temurin:25-jdk bash -c '
    classpath=/caches/fabric-loom/26.3/minecraft-client.jar:$(find /caches/modules-2/files-2.1 -name "*.jar" | tr "\n" ":")
    javac --release 25 -proc:none -implicit:none -nowarn -cp "$classpath" \
      -sourcepath mods/companion/src/main/java:mods/conduit/src/main/java -d /out \
      $(find broker/tests/fixtures/classes/src broker/tests/fixtures/ember broker/tests/fixtures/lore -name "*.java")'
