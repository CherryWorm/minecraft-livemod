#!/bin/bash
# Builds the updater with a public key pinned inside it. Only needs Docker, and uses no Minecraft, so it's quick.
# Usage: build-updater.sh <public key file> <jar to write>
set -euo pipefail
key=$(realpath "$1")
target=$(realpath -m "$2")
repo=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp "$repo/updater/Updater.java" "$work/"
cp "$key" "$work/client_release.pub"
chmod -R a+rwX "$work"

docker run --rm --user "$(id -u):$(id -g)" -v "$work":/work -w /work eclipse-temurin:25-jdk bash -c '
  javac --release 25 -d classes Updater.java &&
  cp client_release.pub classes/ &&
  jar cfe updater.jar gm.updater.Updater -C classes .' </dev/null >&2
mkdir -p "$(dirname "$target")"
cp "$work/updater.jar" "$target"
