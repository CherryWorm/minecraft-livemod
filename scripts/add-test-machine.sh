#!/bin/bash
# Sets up another machine to take test runs, so they don't use the memory and cores of the one people play on. Run it on the main server, as root,
# which has to be able to reach the new machine as root over SSH already. Use a machine that's for nothing else, on Ubuntu 24.04 or later.
# This server's secrets stay here, and that machine gets none of them and no way back in. It does get a copy of the world and the game's files.
# Safe to run again, which also brings its images up to date after a ./scripts/stack.sh build here.
# Usage: ./scripts/add-test-machine.sh <address> <lanes>
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./versions.env; . ./.env; set +a

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root."
  exit 1
fi
address=${1:?Give the machine\'s address}
lanes=${2:-2}
user=livingmod
home=/srv/livingmod
as_root=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "root@$address")
as_broker=(sudo -u "$user" -H ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$user@$address")

echo "Installing what it needs"
"${as_root[@]}" 'bash -s' <infra/wsl/bootstrap.sh
"${as_root[@]}" "apt-get install -y -qq python3-cryptography >/dev/null; [[ \$(id -u $user) == 1000 ]] || { echo 'The $user user there has to have uid 1000, because that is what the containers run as.'; exit 1; }"

echo "Letting the broker in, in that direction only"
sudo -u "$user" -H bash -c '[[ -f ~/.ssh/id_ed25519 ]] || { install -d -m 700 ~/.ssh; ssh-keygen -q -t ed25519 -N "" -C livingmod-broker -f ~/.ssh/id_ed25519; }'
sudo -u "$user" -H bash -c 'cat ~/.ssh/id_ed25519.pub' | "${as_root[@]}" "install -d -m 700 -o $user -g $user ~$user/.ssh; touch ~$user/.ssh/authorized_keys; cat >>~$user/.ssh/authorized_keys; sort -u -o ~$user/.ssh/authorized_keys ~$user/.ssh/authorized_keys; chown $user:$user ~$user/.ssh/authorized_keys; chmod 600 ~$user/.ssh/authorized_keys"

echo "Settings and secrets of its own"
"${as_broker[@]}" "cat >$home/machine.env" <<EOF
RUNTIME_DIR=$home/runtime
MINECRAFT_EULA=${MINECRAFT_EULA:-false}
LEVEL_SEED=${LEVEL_SEED:-}
SHADOW_MEMORY=${SHADOW_MEMORY:-6G}
EOF
"${as_broker[@]}" "mkdir -p $home/runtime/secrets; cd $home/runtime/secrets; umask 077; for name in forwarding rcon bridge web_proxy; do [[ -f \$name.secret ]] || head -c 32 /dev/urandom | base64 | tr -d '/+=\n' >\$name.secret; done; touch claude_token.secret model_key.secret"

echo "The same images as here"
docker save "livingmod/server:$MINECRAFT_VERSION" "livingmod/velocity:$VELOCITY_VERSION-$VELOCITY_BUILD" "livingmod/testclient:$MINECRAFT_VERSION" "caddy:$CADDY_VERSION" eclipse-temurin:25-jdk \
  | nice zstd -q -T2 | "${as_broker[@]}" 'zstd -q -d | docker load -q'

for line in "TEST_MACHINE=$user@$address" "TEST_MACHINE_HOME=$home" "FAR_LANES=$lanes"; do
  key=${line%%=*}
  sudo -u "$user" -H bash -c "sed -i '/^$key=/d' .env; [ -z \"\$(tail -c1 .env)\" ] || echo >>.env; echo '$line' >>.env"
done

echo "Gradle's files, the release's records and the world, which takes a while the first time"
sudo -u "$user" -H bash -c "ssh -o BatchMode=yes $user@$address mkdir -p $home/runtime/cache; nice rsync -a --exclude='*.lock' --exclude=daemon/ '$RUNTIME_DIR/cache/' '$user@$address:$home/runtime/cache/'"
sudo -u "$user" -H env PYTHONDONTWRITEBYTECODE=1 python3 -c "from broker import far; far.prepare_folders(); far.send_release_records(); far.send_world()"

echo "Restarting the broker when what's running has finished, which needs nothing else to restart"
draining=$(sudo -u "$user" -H python3 -c "from broker import daemon; print(daemon.DRAINING)")
sudo -u "$user" -H touch "$draining"
while pgrep -f 'broker\.promote' >/dev/null; do sleep 0.5; done
systemctl restart livingmod-broker
echo "Test runs now go to $address first, with up to $lanes at once. Its journal lines say 'the test machine let it down' if it ever can't take one."
