#!/bin/bash
# Downloads the jars for one role from mods.lock and verifies each SHA-512.
# Usage: fetch-mods.sh <lock file> <role> <destination>
set -euo pipefail
lock=$1
role=$2
dest=$3

mkdir -p "$dest"
while IFS=$'\t' read -r line_role file url sha512; do
  [[ "$line_role" == "$role" ]] || continue
  curl -fsSL --retry 3 -o "$dest/$file" "$url"
  echo "$sha512  $dest/$file" | sha512sum -c --quiet -
  echo "verified $file"
done <"$lock"
