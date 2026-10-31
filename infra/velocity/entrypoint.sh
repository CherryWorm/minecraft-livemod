#!/bin/bash
set -euo pipefail
cd /data

mkdir -p plugins/bStats plugins/velocityreconnect
cp /opt/velocity/velocityreconnect.yml plugins/velocityreconnect/config.yml
sed -e "s|@PROXY_ONLINE_MODE@|${PROXY_ONLINE_MODE:-true}|g" \
    -e "s|@BACKEND@|${BACKEND:-prod:25565}|g" \
    /opt/velocity/velocity.toml >velocity.toml
cp /opt/velocity/plugins/*.jar plugins/

# Velocity reports usage to bStats by default. This is a private server, so that's turned off.
cat >plugins/bStats/config.txt <<'EOF'
enabled=false
server-uuid=00000000-0000-0000-0000-000000000000
log-errors=false
log-sent-data=false
log-response-status-text=false
EOF

exec java -Xms512M -Xmx512M -XX:+UseG1GC -jar /opt/velocity/velocity.jar
