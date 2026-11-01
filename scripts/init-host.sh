#!/bin/bash
# First-time setup on the host: runtime folders, secrets and .env. Safe to run again.
# On a server other people will reach, pass its public address: init-host.sh --public 203.0.113.7
set -euo pipefail
cd "$(dirname "$0")/.."

public=""
if [[ "${1:-}" == "--public" ]]; then
  public="${2:?Usage: init-host.sh [--public ADDRESS]}"
fi

runtime="$(pwd)/../runtime"
mkdir -p "$runtime"/{secrets,velocity,prod,shadow,shadow-proxy,cache/gradle,cache/home,releases/current,releases/candidate,releases/history,broker,backups,control,agent-workspace,friend-pack,site-auth,caddy/data,caddy/config}
runtime=$(cd "$runtime" && pwd)

for name in forwarding rcon bridge web_proxy; do
  file="$runtime/secrets/$name.secret"
  if [[ ! -f "$file" ]]; then
    (umask 077 && head -c 32 /dev/urandom | base64 | tr -d '/+=\n' >"$file")
  fi
done

# Empty until scripts/set-claude-token.sh fills it and makes it root-only.
[[ -e "$runtime/secrets/claude_token.secret" ]] || (umask 077 && : >"$runtime/secrets/claude_token.secret")
[[ -e "$runtime/secrets/model_key.secret" ]] || (umask 077 && : >"$runtime/secrets/model_key.secret")

if [[ ! -f .env ]]; then
  cat >.env <<EOF
RUNTIME_DIR=$runtime
GAME_PORT=25565
PACK_PORT=25567
PROD_MEMORY=8G
SHADOW_MEMORY=6G
# Checks each player's Minecraft login with Mojang. Keep this true on anything others can reach.
PROXY_ONLINE_MODE=true
LEVEL_SEED=
# Set this to true only once you've read and accepted https://aka.ms/MinecraftEULA
MINECRAFT_EULA=false
# Your Minecraft account's UUID, which lets /agentstop work for you in game.
OWNER_UUID=
EOF
  if [[ -n "$public" ]]; then
    token=$(head -c 32 /dev/urandom | base64 | tr -d '/+=\n')
    update_token=$(head -c 32 /dev/urandom | base64 | tr -d '/+=\n')
    cat >>.env <<EOF
# The password is what keeps people out here, so there's no whitelist to manage as well.
WHITE_LIST=false
GAME_PASSWORD_FILE=$runtime/secrets/game_password.secret
SITE_ADDRESS=$public
GAME_ADDRESS=$public
SITE_HTTP_BIND=80
SITE_HTTPS_BIND=443
# Minecraft can't send a password for a resource pack, so this token is the only thing guarding the pack's address.
PACK_TOKEN=$token
PACK_PUBLIC_URL=https://$public/pack/$token/
# The pack's updater has no password either, so this token guards the address it updates from.
UPDATE_TOKEN=$update_token
TOOLS_CPUS=8
AGENT_RESTART=unless-stopped
OPENING_BORDER=128
EOF
  else
    cat >>.env <<EOF
WHITE_LIST=true
PACK_PUBLIC_URL=http://localhost:25567/
EOF
  fi
fi

[[ -f "$runtime/secrets/password.secret" ]] || ./scripts/set-password.sh
echo "host ready: $runtime"
