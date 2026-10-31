#!/bin/bash
# Makes the one file a friend imports into Prism Launcher: Minecraft and Fabric at the versions the server runs,
# Fabric API, and the companion with this server's signing key pinned inside it. The pinned versions are what
# stop a launcher moving someone to a newer Minecraft the server doesn't speak.
# Usage: make-friend-pack.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./versions.env; . ./.env; set +a

out="$RUNTIME_DIR/friend-pack"
work=$(mktemp -d)
resource=mods/companion/src/main/resources/module_key.pub
trap 'rm -rf "$work" "$resource"' EXIT

# Prints the key to pin, and makes the pair if this is the first time.
python3 -m broker.sign | tail -1 >"$resource"

./scripts/stack.sh run --rm -T builder ./gradlew --no-daemon --console=plain :companion:build </dev/null >/dev/null

instance="$work/instance"
mkdir -p "$instance/minecraft/mods"
find mods/companion/build/libs -maxdepth 1 -name 'companion-*.jar' ! -name '*-sources.jar' -exec cp {} "$instance/minecraft/mods/" \;

# Fabric API is checked against the same lock file the server uses.
line=$(grep -P '^server\tfabric-api-' infra/mods.lock)
file=$(cut -f2 <<<"$line"); url=$(cut -f3 <<<"$line"); sha=$(cut -f4 <<<"$line")
curl -fsSL --retry 3 -o "$instance/minecraft/mods/$file" "$url"
echo "$sha  $instance/minecraft/mods/$file" | sha512sum -c - >/dev/null

cat >"$instance/instance.cfg" <<EOF
InstanceType=OneSix
name=Living Mod
EOF
cat >"$instance/mmc-pack.json" <<EOF
{
  "formatVersion": 1,
  "components": [
    {"uid": "net.minecraft", "version": "$MINECRAFT_VERSION", "important": true},
    {"uid": "net.fabricmc.fabric-loader", "version": "$FABRIC_LOADER_VERSION"}
  ]
}
EOF

mkdir -p "$out"
target="$out/LivingMod-$(date +%Y%m%d-%H%M%S).zip"
python3 - "$instance" "$target" <<'PY'
import pathlib, sys, zipfile
root, target = pathlib.Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(root))
PY
echo "$target"
