#!/bin/bash
# First-time setup on the host: runtime folders, secrets and .env. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."

runtime="$(pwd)/../runtime"
mkdir -p "$runtime"/{secrets,velocity,prod,shadow,cache/gradle,cache/home,releases/current,releases/candidate}
runtime=$(cd "$runtime" && pwd)

for name in forwarding rcon; do
  file="$runtime/secrets/$name.secret"
  if [[ ! -f "$file" ]]; then
    (umask 077 && head -c 32 /dev/urandom | base64 | tr -d '/+=\n' >"$file")
  fi
done

# Empty until scripts/set-claude-token.sh fills it and makes it root-only.
[[ -e "$runtime/secrets/claude_token.secret" ]] || (umask 077 && : >"$runtime/secrets/claude_token.secret")

if [[ ! -f .env ]]; then
  cat >.env <<EOF
RUNTIME_DIR=$runtime
GAME_PORT=25565
PACK_PORT=25567
PACK_PUBLIC_URL=http://localhost:25567/
PROD_MEMORY=8G
SHADOW_MEMORY=6G
WHITE_LIST=true
# Checks each player's Minecraft login with Mojang. Keep this true on anything others can reach.
PROXY_ONLINE_MODE=true
LEVEL_SEED=
# Set this to true only once you've read and accepted https://aka.ms/MinecraftEULA
MINECRAFT_EULA=false
EOF
fi
echo "host ready: $runtime"
