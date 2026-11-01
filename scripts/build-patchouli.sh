#!/bin/bash
# Builds our port of Patchouli from upstream's source and puts it where the companion and the friend pack take it from.
# Only needed to change the port, because the result is committed. See third_party/patchouli/README.md.
# Usage: build-patchouli.sh
set -euo pipefail
cd "$(dirname "$0")/.."
. ./.env

upstream=4f94b07bbd287f2e208a7ea90b0ca066e54f738c
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git clone -q --branch 26.1 https://github.com/VazkiiMods/Patchouli "$work/patchouli"
git -C "$work/patchouli" checkout -q "$upstream"
git -C "$work/patchouli" apply "$PWD/third_party/patchouli/port.patch"
cp third_party/patchouli/build.gradle third_party/patchouli/settings.gradle third_party/patchouli/gradle.properties "$work/patchouli/"
cp -r mods/gradle mods/gradlew "$work/patchouli/"
chmod -R a+rwX "$work"

docker run --rm --user "$(id -u):$(id -g)" -e GRADLE_USER_HOME=/cache/gradle -e HOME=/cache/home \
	-v "$work/patchouli":/work -v "$RUNTIME_DIR/cache":/cache -w /work eclipse-temurin:25-jdk \
	./gradlew --no-daemon --console=plain build -x test </dev/null

rm -f mods/companion/libs/patchouli-fabric-*.jar
cp "$work"/patchouli/build/libs/patchouli-fabric-*.jar mods/companion/libs/
ls mods/companion/libs
