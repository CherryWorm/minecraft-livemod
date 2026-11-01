#!/bin/bash
# Makes the one file a friend imports into Prism Launcher: Minecraft and Fabric at the versions the server runs,
# Fabric API, the companion with this server's signing key pinned inside it, and the client mods everyone plays with.
# The pinned versions are what stop a launcher moving someone to a newer Minecraft the server doesn't speak.
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
bash infra/fetch-mods.sh infra/mods.lock client "$instance/minecraft/mods" >/dev/null
# Our port of Patchouli, which nowhere offers for this Minecraft yet. See third_party/patchouli.
cp mods/companion/libs/patchouli-fabric-*.jar "$instance/minecraft/mods/"

cat >"$instance/instance.cfg" <<EOF
[General]
InstanceType=OneSix
name=Living Mod
EOF
# After this, the pack keeps itself up to date: Prism runs the updater before each launch, in the game's folder. See updater/Updater.java.
if [[ -n "${UPDATE_TOKEN:-}" ]]; then
  ./scripts/build-updater.sh infra/client_release.pub "$instance/minecraft/livingmod-updater.jar"
  echo "url=https://$SITE_ADDRESS/update/$UPDATE_TOKEN" >"$instance/minecraft/livingmod-updater.properties"
  {
    echo "generation 0"
    for path in "$instance"/minecraft/mods/*; do echo "managed mods/$(basename "$path")"; done
  } >"$instance/minecraft/livingmod-updater.state"
  # Written as Prism writes it, with no quotes around the whole value. Prism reads a file like this one with an older parser, which keeps
  # them, and then it can't find the program, so the game won't start at all.
  cat >>"$instance/instance.cfg" <<'EOF'
OverrideCommands=true
PreLaunchCommand=\"$INST_JAVA\" -jar livingmod-updater.jar
EOF
fi
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
python3 - "$instance" "$target" "${GAME_ADDRESS:-localhost}" <<'PY'
import pathlib, struct, sys, zipfile
root, target, address = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]

def text(value):
    data = value.encode("utf-8")
    return struct.pack(">H", len(data)) + data

# The game's server list, with this server already in it and its resource pack already accepted.
server = (b"\x08" + text("ip") + text(address) + b"\x08" + text("name") + text("Living Mod")
          + b"\x01" + text("acceptTextures") + b"\x01" + b"\x00")
servers = b"\x09" + text("servers") + b"\x0a" + struct.pack(">i", 1) + server
(root / "minecraft" / "servers.dat").write_bytes(b"\x0a" + text("") + servers + b"\x00")

with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(root))
PY
# The site offers this name, which never changes, so its link stays the same across rebuilds.
cp "$target" "$out/LivingMod.zip"
echo "$target"
