#!/bin/bash
# The parts of S1 and S2 only a real game client can answer: how long a pack reload freezes the game,
# and whether a restart that adds content holds the player. Usage: real_client_check.sh <player>
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

player=${1:?usage: real_client_check.sh <player>}
assets="$RUNTIME_DIR/prod/live-assets/assets/gm"
logs() { ./scripts/stack.sh logs --no-log-prefix --since "$1" "$2" 2>&1 </dev/null; }

online() { ./scripts/mc.sh list 2>/dev/null | grep -q "$player"; }
online || { echo "FAIL: $player isn't online"; exit 1; }

echo "=== placing the test block next to $player"
./scripts/mc.sh give "$player" gm:s1001 4
./scripts/mc.sh execute at "$player" run setblock '~2' '~1' '~' gm:s1001

mkdir -p "$assets/models/block" "$assets/textures/block"
cat >"$assets/models/block/s1001.json" <<'EOF'
{"parent":"minecraft:block/cube_all","textures":{"all":"gm:block/s1001"}}
EOF

echo "=== S1: three live texture changes, 15 seconds apart"
for variant in 0 2 1; do
  mark=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  python3 assetkit/proof_texture.py "$variant" >"$assets/textures/block/s1001.png"
  ./scripts/mc.sh polymer generate-pack reload >/dev/null
  result=""
  for _ in $(seq 1 120); do
    result=$(logs "$mark" prod | grep -E "pack (loaded by|problem for) $player" | tail -1)
    [[ -n "$result" ]] && break
    sleep 0.5
  done
  echo "variant $variant: ${result:-no answer from the client after 60s}" | cut -c1-110
  online || { echo "FAIL: $player disconnected during the pack change"; exit 1; }
  sleep 15
done

echo "=== S2: restarting with a new block and biome"
mkdir -p "$RUNTIME_DIR/prod/config/conduit"
python3 spikes/make_biome_pack.py "$RUNTIME_DIR/prod" 1
mark=$(date -u +%Y-%m-%dT%H:%M:%SZ)
started=$(date +%s.%N)
./scripts/stack.sh restart prod >/dev/null 2>&1 </dev/null
for _ in $(seq 1 240); do
  online && break
  sleep 0.5
done
python3 -c "import time; print('back in the world after %.1fs' % (time.time() - $started))"
if logs "$mark" velocity | grep -q "$player.*has disconnected:\|$player (.*) has disconnected"; then
  echo "FAIL: $player was disconnected from the proxy"
  logs "$mark" velocity | grep "$player" | cut -c1-150
  exit 1
fi
online || { echo "FAIL: $player never came back"; exit 1; }
./scripts/mc.sh execute at "$player" run setblock '~-2' '~1' '~' gm:s1009
./scripts/mc.sh execute at "$player" run fillbiome '~-16' '~-8' '~-16' '~16' '~8' '~16' s2:b01
echo "PASS: $player stayed connected through the restart"
