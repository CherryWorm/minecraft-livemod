#!/bin/bash
# Spike S4: can a real client load and unload Java modules while it plays, through the proxy, with
# Polymer on the server? Starts a headless client, then swaps a module many times from the server.
# Usage: s4_modules.sh [cycles]
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

cycles=${1:-100}
export S4_CYCLES=$cycles
work="$RUNTIME_DIR/s4"
log="$work/client.log"
modules="$RUNTIME_DIR/prod/modules"
mkdir -p "$work" "$modules"
: >"$log"

jar=$(find mods/sample-module/build/libs -name 'sample-module-*.jar' ! -name '*-sources.jar' | head -1)
[[ -n "$jar" ]] || { echo "FAIL: sample module isn't built"; exit 1; }
cp "$jar" "$modules/sample.jar"

wait_log() {
  local pattern=$1 seconds=$2
  for _ in $(seq 1 $((seconds * 4))); do
    grep -qE "$pattern" "$log" && return 0
    kill -0 "$client" 2>/dev/null || { echo "FAIL: client exited waiting for: $pattern"; tail -25 "$log" | cut -c1-200; return 1; }
    # The game can hang rather than exit on these, so there's no point waiting out the timeout.
    if grep -qE 'Failed to create backend Vulkan|Game crashed|BUILD FAILED|\.java:[0-9]+: error:' "$log"; then
      echo "FAIL: client hit a fatal error waiting for: $pattern"; grep -E 'Failed to create|\.java:[0-9]+: error:|BUILD FAILED|Game crashed' "$log" | head -8 | cut -c1-200; return 1
    fi
    sleep 0.25
  done
  echo "FAIL: timed out waiting for: $pattern"
  tail -25 "$log" | cut -c1-200
  return 1
}

./scripts/stack.sh --profile tools build testclient >/dev/null 2>&1 </dev/null

started=$(date +%s)
docker rm -f livingmod-s4-client >/dev/null 2>&1
./scripts/stack.sh --profile tools run --rm -T --name livingmod-s4-client testclient \
  ./gradlew --no-daemon --console=plain :companion:runClientGameTest \
  >"$log" 2>&1 </dev/null &
client=$!
trap 'docker rm -f livingmod-s4-client >/dev/null 2>&1; kill "$client" 2>/dev/null' EXIT

wait_log '\[S4\] joined as [A-Za-z0-9_]+$' 600 || exit 1
echo "client joined after $(( $(date +%s) - started ))s: $(grep -m1 -oE '\[S4\] joined as [A-Za-z0-9_]+$' "$log")"
sleep 8
./scripts/mc.sh list

./scripts/mc.sh conduit module push sample s4 1
wait_log 'module s4 generation 1 enabled' 60 || exit 1
wait_log '\[S4\] module visible' 120 || exit 1

cycle_started=$(date +%s.%N)
for generation in $(seq 2 $((cycles + 1))); do
  ./scripts/mc.sh conduit module unload s4 >/dev/null
  ./scripts/mc.sh conduit module push sample s4 "$generation" >/dev/null
  wait_log "module s4 generation $generation enabled" 60 || exit 1
done
./scripts/mc.sh conduit module unload s4
python3 -c "import time; print('%d swaps took %.1fs' % ($cycles, time.time() - $cycle_started))"

wait_log '\[S4\] finished' 300 || exit 1
wait "$client"
code=$?
trap - EXIT

echo "=== memory as cycles go by"
grep -oE 'cycle=[0-9]+ heap_mb=[0-9]+ classes_loaded=[0-9]+ classes_unloaded=[0-9]+' "$log"
echo "=== result"
grep -oE '\[S4\] finished.*' "$log"
grep -cE 'module s4 generation [0-9]+ enabled' "$log" | sed 's/^/modules enabled: /'
grep -cE 'module s4 disabled after repeated errors' "$log" | sed 's/^/modules switched off for errors: /'
grep -E 'FATAL|Game crashed|Crash report|Registry|registry sync|mismatch' "$log" | cut -c1-180 | head -8
echo "client exit=$code"
mkdir -p "$work/screenshots"
find mods/companion/build/run/clientGameTest/screenshots -name '*s4_*.png' -exec cp {} "$work/screenshots/" \; 2>/dev/null
ls "$work/screenshots"
exit "$code"
