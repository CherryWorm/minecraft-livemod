#!/bin/bash
# Spike S2: do players stay connected through restarts that add blocks and biomes?
# Usage: s2_restart_hold.sh [rounds] [--crash]. --crash uses kill -9 instead of a clean stop.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

rounds=${1:-20}
mode=${2:-}
base_slots=8
log=$(mktemp)
failures=0
slowest=0

python3 -u scripts/smoketest_join.py --name s2bot --stay 7200 >"$log" 2>&1 &
bot=$!
trap 'kill "$bot" 2>/dev/null; rm -f "$log"' EXIT

for _ in $(seq 1 100); do
  grep -q JOINED "$log" && break
  sleep 0.2
done
grep -q JOINED "$log" || { echo "FAIL: test client never joined"; cat "$log"; exit 1; }
sleep 2
baseline=$(./scripts/mc.sh data get entity s2bot Inventory)
echo "baseline inventory: $baseline"

for round in $(seq 1 "$rounds"); do
  slots=$((base_slots + round))
  mkdir -p "$RUNTIME_DIR/prod/config/conduit"
  echo "$slots" >"$RUNTIME_DIR/prod/config/conduit/slots"
  python3 spikes/make_biome_pack.py "$RUNTIME_DIR/prod" "$round"

  joins_before=$(grep -c JOINED "$log")
  started=$(date +%s.%N)
  if [[ "$mode" == "--crash" ]]; then
    docker kill --signal=KILL livingmod-prod-1 >/dev/null
    ./scripts/stack.sh up -d prod >/dev/null 2>&1 </dev/null
  else
    ./scripts/stack.sh restart prod >/dev/null 2>&1 </dev/null
  fi

  back=no
  for _ in $(seq 1 240); do
    kill -0 "$bot" 2>/dev/null || break
    if [[ $(grep -c JOINED "$log") -gt "$joins_before" ]]; then back=yes; break; fi
    sleep 0.5
  done
  held=$(python3 -c "import time; print('%.1f' % (time.time() - $started))")

  if ! kill -0 "$bot" 2>/dev/null; then
    echo "round $round: FAIL, test client was disconnected after ${held}s"
    tail -5 "$log"
    exit 1
  fi
  if [[ "$back" == "no" ]]; then
    echo "round $round: FAIL, not back after ${held}s"
    tail -5 "$log"
    exit 1
  fi

  sleep 1
  inventory=$(./scripts/mc.sh data get entity s2bot Inventory)
  [[ "$inventory" == "$baseline" ]] && inv_ok=yes || inv_ok=NO
  ./scripts/mc.sh forceload add 0 0 >/dev/null
  block_id=$(printf 'gm:s%04d' "$slots")
  block=$(./scripts/mc.sh setblock 0 120 0 "$block_id")
  [[ "$block" == *Changed* ]] && block_ok=yes || block_ok=NO
  biome_id=$(printf 's2:b%02d' "$round")
  biome=$(./scripts/mc.sh fillbiome 0 120 0 3 123 3 "$biome_id")
  [[ "$biome" == *[0-9]* && "$biome" != *nknown* && "$biome" != *rror* ]] && biome_ok=yes || biome_ok=NO
  ./scripts/mc.sh setblock 0 120 0 minecraft:air >/dev/null

  [[ "$inv_ok$block_ok$biome_ok" == "yesyesyes" ]] || failures=$((failures + 1))
  slowest=$(python3 -c "print(max($slowest, $held))")
  echo "round $round: held ${held}s, inventory $inv_ok, new block $block_id $block_ok, new biome $biome_id $biome_ok"
done

echo "slowest hold: ${slowest}s of $rounds rounds, $failures with a failed check"
[[ "$failures" -eq 0 ]] && echo "PASS" || { echo "FAIL"; exit 1; }
