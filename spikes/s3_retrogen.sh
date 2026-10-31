#!/bin/bash
# Spike S3: can ore be added to a played world, surviving a crash, without touching player progress?
# Builds a base on the shadow server, snapshots it, adds an ore with a kill -9 in the middle, then has
# world_diff.py read the raw files. Then runs again to prove a second pass changes nothing.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

dir="$RUNTIME_DIR/shadow"
work="$RUNTIME_DIR/s3"
stack() { ./scripts/stack.sh --profile shadow "$@" </dev/null; }
mc() { ./scripts/mc.sh --server shadow "$@"; }

wait_ready() {
  for _ in $(seq 1 240); do
    mc list >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  echo "FAIL: shadow server didn't start"; stack logs --no-log-prefix --tail 30 shadow | cut -c1-200; exit 1
}

# Loads a square of chunks around the origin and keeps it loaded.
forceload_area() {
  for x in -128 -64 0 64; do
    for z in -128 -64 0 64; do
      mc forceload add "$x" "$z" "$((x + 63))" "$((z + 63))" >/dev/null
    done
  done
}

find_regions() { find "$dir/world" -type d -name region | grep -E 'overworld|world/region' | head -1; }

latest_status() { stack logs --no-log-prefix --since 30s shadow 2>&1 | grep 'retrogen: queued=' | tail -1; }

wait_queue_empty() {
  for _ in $(seq 1 240); do
    line=$(latest_status)
    if [[ "$line" == *"queued=0 "* ]]; then echo "$line" | cut -c1-120; return 0; fi
    sleep 2
  done
  echo "FAIL: patch queue never emptied"; latest_status; exit 1
}

echo "=== fresh shadow world"
stack rm -sf shadow >/dev/null 2>&1
rm -rf "$dir" "$work"
mkdir -p "$dir/config/conduit" "$work"
stack up -d shadow >/dev/null 2>&1
wait_ready

# Random ticks would add natural changes to the diff, so they're off for a clean reading.
mc gamerule random_tick_speed 0 >/dev/null || mc gamerule randomTickSpeed 0 >/dev/null
forceload_area
sleep 20

echo "=== building a base"
# A stone room dug into the ground, with a chest and furnace, and a tunnel.
mc fill 8 40 8 24 50 24 minecraft:stone
mc fill 10 42 10 22 48 22 minecraft:air
mc setblock 12 42 12 minecraft:chest
mc item replace block 12 42 12 container.0 with minecraft:diamond 5
mc setblock 13 42 12 minecraft:furnace
mc fill 23 44 16 60 45 17 minecraft:air
mc fill -40 30 -40 -30 34 -30 minecraft:deepslate
# Placed stone inside a natural cliff: looks exactly like natural stone, but was built.
mc fill -60 55 -60 -50 60 -50 minecraft:stone
mc save-all flush
sleep 6
stack stop shadow >/dev/null 2>&1

regions=$(find_regions)
[[ -n "$regions" ]] || { echo "FAIL: can't find region files"; exit 1; }
cp -r "$regions" "$work/before"
echo "snapshot taken: $(ls "$work/before" | wc -l) region files"

echo "=== adding the ore"
cat >"$dir/config/conduit/ore_patches.json" <<'EOF'
[{"id": "s3_test_ore", "block": "gm:s1001",
  "replaces": ["minecraft:stone", "minecraft:deepslate", "minecraft:tuff", "minecraft:granite", "minecraft:diorite", "minecraft:andesite"],
  "veinsPerChunk": 8, "veinSize": 9, "minY": -60, "maxY": 80}]
EOF
# Patching normally takes seconds, so it's slowed right down to make sure the crash lands mid-run.
echo 50 >"$dir/config/conduit/retrogen_budget_micros"
stack up -d shadow >/dev/null 2>&1
wait_ready
mc gamerule random_tick_speed 0 >/dev/null 2>&1

echo "=== crashing mid-run with kill -9"
# The save in between means some chunks reach disk patched and others don't, which is the case a crash
# really has to survive.
sleep 3
mc save-all >/dev/null
sleep 1
docker kill --signal=KILL livingmod-shadow-1 >/dev/null
sleep 2
rm -f "$dir/config/conduit/retrogen_budget_micros"
stack up -d shadow >/dev/null 2>&1
wait_ready
after_crash=$(wait_queue_empty)
echo "$after_crash"
after_crash_chunks=$(echo "$after_crash" | grep -oE 'chunks=[0-9]+' | cut -d= -f2)
echo "chunks still needing the patch after the crash: $after_crash_chunks"
# 324 chunks load in this area. Anything else at either end means the crash didn't test a partial save.
if [[ "${after_crash_chunks:-0}" -le 0 || "${after_crash_chunks:-0}" -ge 324 ]]; then
  echo "S3 FAIL: the crash didn't land mid-run, so this run proves nothing"
  exit 1
fi
mc save-all flush
sleep 6
stack stop shadow >/dev/null 2>&1
cp -r "$regions" "$work/after1"

echo "=== checking the raw files against the snapshot"
protect=(--protect 8 40 8 24 50 24 --protect 23 44 16 60 45 17 --protect -40 30 -40 -30 34 -30 --protect -60 55 -60 -50 60 -50)
python3 broker/gates/world_diff.py "$work/before" "$work/after1" --ore gm:s1001 \
  --allow minecraft:stone minecraft:deepslate minecraft:tuff minecraft:granite minecraft:diorite minecraft:andesite "${protect[@]}"
first=$?

echo "=== second pass: starting again with the same patch must change nothing"
stack up -d shadow >/dev/null 2>&1
wait_ready
sleep 25
reprocessed=$(wait_queue_empty | grep -oE 'chunks=[0-9]+' | cut -d= -f2)
echo "chunks processed again on this boot: $reprocessed (must be 0)"
mc save-all flush
sleep 6
stack stop shadow >/dev/null 2>&1
cp -r "$regions" "$work/after2"
python3 broker/gates/world_diff.py "$work/after1" "$work/after2" --ore gm:s1001 --allow none
second=$?
[[ "${reprocessed:-1}" -eq 0 ]] || second=1

echo "=== worst tick cost seen"
stack logs --no-log-prefix shadow 2>&1 | grep -oE 'tick_ms_p99=[0-9.]+ tick_ms_max=[0-9.]+' | sort -t= -k2 -n | tail -2

[[ "$first" -eq 0 && "$second" -eq 0 ]] && echo "S3 PASS" || { echo "S3 FAIL"; exit 1; }
