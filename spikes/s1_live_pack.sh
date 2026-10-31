#!/bin/bash
# Spike S1: can new art reach a connected player with no disconnect and no restart?
# Usage: s1_live_pack.sh [variant] [slot]. Also hands the block to anyone else who is online.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

variant=${1:-1}
slot=${2:-s1001}
assets="$RUNTIME_DIR/prod/live-assets/assets/gm"
log=$(mktemp)

python3 -u scripts/smoketest_join.py --name s1bot --stay 60 >"$log" 2>&1 &
bot=$!
trap 'kill "$bot" 2>/dev/null; rm -f "$log"' EXIT

for _ in $(seq 1 100); do
  grep -q JOINED "$log" && break
  kill -0 "$bot" 2>/dev/null || { echo "FAIL: test client died before joining"; cat "$log"; exit 1; }
  sleep 0.2
done
grep -q JOINED "$log" || { echo "FAIL: test client never joined"; cat "$log"; exit 1; }
first_hash=$(grep -m1 PACK_OK "$log" | awk '{print $2}')
echo "joined with pack $first_hash"

mkdir -p "$assets/models/block" "$assets/textures/block"
python3 assetkit/proof_texture.py "$variant" >"$assets/textures/block/$slot.png"
cat >"$assets/models/block/$slot.json" <<EOF
{"parent":"minecraft:block/cube_all","textures":{"all":"gm:block/$slot"}}
EOF

started=$(date +%s.%N)
./scripts/mc.sh polymer generate-pack reload
for _ in $(seq 1 150); do
  second_hash=$(grep PACK_OK "$log" | tail -1 | awk '{print $2}')
  [[ -n "$second_hash" && "$second_hash" != "$first_hash" ]] && break
  sleep 0.2
done
if [[ "$second_hash" == "$first_hash" ]]; then
  echo "FAIL: no new pack reached the test client"; cat "$log"; exit 1
fi
python3 -c "import time; print('new pack delivered in %.2fs' % (time.time() - $started))"
echo "new pack $second_hash"

kill -0 "$bot" 2>/dev/null || { echo "FAIL: test client was disconnected"; cat "$log"; exit 1; }
./scripts/mc.sh give s1bot "gm:$slot" 1
./scripts/mc.sh list
echo "PASS: pack replaced with the test client still connected"
