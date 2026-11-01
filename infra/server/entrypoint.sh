#!/bin/bash
# Prepares /data from the image and the current release, then starts the server.
# Mods and config are rebuilt on every boot, so what's running always matches git and the release.
set -euo pipefail
cd /data

cp -an /opt/mc/bake/. .

rm -rf mods
mkdir -p mods config/polymer
cp /opt/mc/mods/*.jar mods/
if [[ "${SERVER_ROLE:-prod}" == "shadow" && "${SHADOW_TEST_MODS:-true}" == "true" ]]; then
  cp /opt/mc/mods-shadow/*.jar mods/
fi
if compgen -G "/opt/release/*.jar" >/dev/null; then
  cp /opt/release/*.jar mods/
fi

# The answer comes from whoever runs the stack. The server refuses to start unless it's true.
echo "eula=${MINECRAFT_EULA:-false}" >eula.txt

rcon_password=$(cat /run/secrets/rcon)
sed -e "s|@WHITE_LIST@|${WHITE_LIST:-true}|g" \
    -e "s|@LEVEL_SEED@|${LEVEL_SEED:-}|g" \
    -e "s|@VIEW_DISTANCE@|${VIEW_DISTANCE:-10}|g" \
    -e "s|@RCON_PASSWORD@|${rcon_password}|g" \
    /opt/mc/server.properties >server.properties
sed -e "s|@PACK_PUBLIC_URL@|${PACK_PUBLIC_URL}|g" \
    /opt/mc/auto-host.json >config/polymer/auto-host.json

# Whose in-game command can stop the agent. Empty means only the server console can.
mkdir -p config/conduit
printf '%s\n' "${OWNER_UUID:-}" >config/conduit/owner.txt

export FABRIC_PROXY_SECRET_FILE=/run/secrets/forwarding
export FABRIC_PROXY_HACK_ONLINE_MODE=true

exec java \
  "-Xms${JAVA_MEMORY:-4G}" "-Xmx${JAVA_MEMORY:-4G}" \
  -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=100 \
  -jar /opt/mc/fabric-server.jar nogui
