#!/bin/bash
# Prepares another machine to take test runs, so they don't use the memory and cores of the one people play on. Run it on the main server, as root.
# It needs nothing but an ordinary account there that this server's broker can log in to, and containers run without root, so the account gains no power over that
# machine, and whatever's being tested can only reach its own lane. Someone with root there has to have run this once:
#   apt-get install -y podman uidmap passt docker-compose
# This server's secrets stay here, and that machine gets none of them and no way back in. It does get a copy of the world and the game's files.
# Safe to run again, which also brings its images up to date after a ./scripts/stack.sh build here.
# It leaves test runs going where they were. To send them there, once a test run has been tried: scripts/add-test-machine.sh --use <lanes> [compile check lanes]
# Usage: ./scripts/add-test-machine.sh <account@address> [folder]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./versions.env; . ./.env; set +a

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root."
  exit 1
fi
broker=livingmod
as_broker=(sudo -u "$broker" -H)
key=$(eval echo "~$broker")/.ssh/id_ed25519
"${as_broker[@]}" bash -c '[[ -f ~/.ssh/id_ed25519 ]] || { install -d -m 700 ~/.ssh; ssh-keygen -q -t ed25519 -N "" -C livingmod-broker -f ~/.ssh/id_ed25519; }'

set_setting() {
  "${as_broker[@]}" bash -c "sed -i '/^$1=/d' .env; [ -z \"\$(tail -c1 .env)\" ] || echo >>.env; echo '$1=$2' >>.env"
}

if [[ "${1:-}" == "--use" ]]; then
  lanes=${2:?Say how many lanes}
  set_setting FAR_LANES "$lanes"
  set_setting FAR_CHECK_LANES "${3:-$lanes}"
  echo "Restarting the broker when what's running has finished, which needs nothing else to restart"
  draining=$("${as_broker[@]}" python3 -c "from broker import daemon; print(daemon.DRAINING)")
  "${as_broker[@]}" touch "$draining"
  while pgrep -f 'broker\.promote' >/dev/null; do sleep 0.5; done
  systemctl restart livingmod-broker
  echo "Test runs and compile checks now go to ${TEST_MACHINE:-that machine} first, with up to $lanes and ${3:-$lanes} at once. The broker's log says 'the test machine let it down' if it ever can't take one."
  exit 0
fi

machine=${1:?Give the account and address, like tester@203.0.113.5}
there() {
  "${as_broker[@]}" ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$machine" "$@"
}
if ! there true; then
  echo "The broker can't log in there. Add this to that account's ~/.ssh/authorized_keys and run this again:"
  cat "$key.pub"
  exit 1
fi
home=${2:-$(there 'echo $HOME')/livingmod}
missing=$(there 'for tool in podman newuidmap pasta docker flock rsync zstd; do command -v $tool >/dev/null || echo $tool; done; docker compose version >/dev/null 2>&1 || echo docker-compose')
if [[ -n "$missing" ]]; then
  echo "It's missing: $missing"
  echo "Someone with root there has to run: apt-get install -y podman uidmap passt docker-compose"
  exit 1
fi

echo "Containers and Python, in that account alone"
there "set -e
mkdir -p $home/runtime/secrets
systemctl --user enable --now podman.socket
loginctl enable-linger
python3 -m venv $home/venv
$home/venv/bin/pip install --quiet pillow cryptography
cat >$home/environment <<EOF
export PATH=$home/venv/bin:\$PATH
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
export DOCKER_HOST=unix:///run/user/\$(id -u)/podman/podman.sock
EOF"

echo "Settings and secrets of its own"
there "cat >$home/machine.env" <<EOF
RUNTIME_DIR=$home/runtime
MINECRAFT_EULA=${MINECRAFT_EULA:-false}
LEVEL_SEED=${LEVEL_SEED:-}
SHADOW_MEMORY=${SHADOW_MEMORY:-6G}
TOOLS_CPUS=${TOOLS_CPUS:-8}
STACK_USER=0:0
TEST_CLIENT_APART=true
TEST_CLIENT_INIT=false
PACK_PUBLIC_URL=http://localhost/
EOF
there "cd $home/runtime/secrets; umask 077; for name in forwarding rcon bridge web_proxy; do [[ -f \$name.secret ]] || head -c 32 /dev/urandom | base64 | tr -d '/+=\n' >\$name.secret; done; touch claude_token.secret model_key.secret"

echo "The same images as here"
docker save "livingmod/server:$MINECRAFT_VERSION" "livingmod/velocity:$VELOCITY_VERSION-$VELOCITY_BUILD" "livingmod/testclient:$MINECRAFT_VERSION" "caddy:$CADDY_VERSION" eclipse-temurin:25-jdk \
  | nice zstd -q -T2 | there "zstd -q -d | podman load -q"

set_setting TEST_MACHINE "$machine"
set_setting TEST_MACHINE_HOME "$home"

echo "Gradle's files, the release's records and the world, which takes a while the first time"
there "mkdir -p $home/runtime/cache"
"${as_broker[@]}" nice rsync -a --exclude='*.lock' --exclude=daemon/ "$RUNTIME_DIR/cache/" "$machine:$home/runtime/cache/"
"${as_broker[@]}" env PYTHONDONTWRITEBYTECODE=1 python3 -c "from broker import far; far.prepare_folders(); far.send_release_records(); far.send_world()"
echo "Ready. Try a test run there, then send them there with: scripts/add-test-machine.sh --use <lanes>"
