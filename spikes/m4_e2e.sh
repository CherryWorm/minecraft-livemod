#!/bin/bash
# M4's exit test: in a blank world, the agent interviews two test players privately, chooses a direction,
# teases it in role, ships one tested feature with no human help, and speaks up once unprompted.
# It stops after one release, so what it spends is bounded. Start with a blank world from reset-dev-world.sh.
# Usage: m4_e2e.sh [features to ship, default 1]
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

work="$RUNTIME_DIR/e2e"
state="$RUNTIME_DIR/agent-workspace/state"
rm -rf "$work"; mkdir -p "$work"
started=$(date +%s)
elapsed() { echo "$(( $(date +%s) - started ))s"; }

cat >"$work/aria.json" <<'JSON'
{"answers": [
  "I want exploring to feel dangerous, and to keep finding strange things. I'm so tired of grinding. quokkamarker",
  "Maybe sunken ruins or a drowned world? Machines that run on the tides would be cool.",
  "Create, because you can watch machines move. Thaumcraft, because you figure things out by studying them.",
  "I hate when progress is just bigger numbers. That's about all from me.",
  "Thanks, I'm happy to start playing now."],
 "public": ["could we find something that glows in the caves?"]}
JSON
cat >"$work/bram.json" <<'JSON'
{"answers": [
  "I like building factories and tuning them until they hum. wombatmarker",
  "Clockwork gods or living fungus, either would be a neat theme.",
  "Botania for the puzzles, and Applied Energistics for how satisfying the logistics feel.",
  "Too many inventory screens annoy me. That's everything, go ahead.",
  "Done, thanks!"],
 "public": []}
JSON

echo "=== baseline release, so the first feature doesn't need a restart ($(elapsed))"
python3 -m broker.promote --source "$(pwd)" --release-id baseline 2>&1 | tail -14 | cut -c1-120
printf 'Aria\nBram\n' >"$RUNTIME_DIR/control/roster.txt"

echo "=== starting the agent ($(elapsed))"
wanted=${1:-1}
export AGENT_DAILY_USAGE_LIMIT=$((wanted * 3 + 16)) AGENT_STOP_AFTER_RELEASES=$wanted AGENT_MAX_BUILDERS=$(( wanted > 1 ? 2 : 1 ))
./scripts/agent-up.sh --no-build

python3 scripts/playtest_bot.py --name Aria --script "$work/aria.json" --log "$work/aria.jsonl" --never-see wombatmarker --seconds 7200 \
  >"$work/aria.out" 2>&1 </dev/null &
aria=$!
python3 scripts/playtest_bot.py --name Bram --script "$work/bram.json" --log "$work/bram.jsonl" --never-see quokkamarker --seconds 7200 \
  >"$work/bram.out" 2>&1 </dev/null &
bram=$!
trap 'kill "$aria" "$bram" 2>/dev/null; ./scripts/agent-down.sh >/dev/null 2>&1' EXIT

wait_for() {
  local description=$1 seconds=$2 condition=$3
  for _ in $(seq 1 $((seconds / 5))); do
    if eval "$condition" >/dev/null 2>&1; then
      echo "$description after $(elapsed)"
      return 0
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' livingmod-agent-1 2>/dev/null)" != "true" ]]; then
      echo "FAIL: the agent stopped while waiting for: $description"
      return 1
    fi
    sleep 5
  done
  echo "FAIL: timed out waiting for: $description"
  return 1
}

failed=0
wait_for "the direction was chosen" 1500 "grep -q '\"direction_chosen\": true' '$state/opening.json'" || failed=1

if [[ $failed == 0 ]]; then
  # Silence is an allowed answer for the watcher, so give it a few chances to speak up.
  for round in 1 2 3 4; do
    for _ in 1 2 3; do
      ./scripts/mc.sh kill Bram >/dev/null
      sleep 12
    done
    sleep 30
    if docker exec livingmod-agent-1 grep -q '"role": "watcher"' /workspace/state/llm.jsonl </dev/null \
      && grep '"kind": "died"' -A40 "$work/bram.jsonl" | grep '"heard"' | grep -q $'§d'; then
      echo "the watcher spoke up after round $round ($(elapsed))"
      break
    fi
  done
  # If a feature can't be finished the agent moves on to the next, so three of those means something is really wrong.
  wait_for "$wanted feature(s) finished" 5400 "[ \$(cat '$state/features.jsonl' 2>/dev/null | wc -l) -ge $wanted ] || [ \$(docker logs livingmod-agent-1 2>&1 | grep -c 'giving up after') -ge 3 ]" || failed=1
fi
sleep 60

if [[ $failed == 0 ]]; then
  echo; echo "=== the tuner, and a mid-game machine from a real builder ($(elapsed))"
  ./scripts/stack.sh --profile agent run --rm -T agent python3 /spikes/m4_tools.py </dev/null 2>&1 | grep -v 'Container livingmod' | grep -v 'Permission mode forced' | cut -c1-700
  [[ ${PIPESTATUS[0]} == 0 ]] || failed=1
fi

echo; echo "=== the kill switch"
./scripts/mc.sh agentstop
python3 -c "from broker import runtime; print('broker sees it on:', runtime.agent_disabled())"
sleep 12
python3 scripts/playtest_bot.py --name Cara --script "$work/bram.json" --log "$work/cara.jsonl" --seconds 25 >/dev/null 2>&1 </dev/null || true
if grep '"heard"' "$work/cara.jsonl" 2>/dev/null | grep -qv 'multiplayer\.'; then
  echo "FAIL: the agent spoke to a new player with the kill switch on"
  failed=1
else
  echo "a new player heard nothing with the kill switch on"
fi
./scripts/mc.sh agentstart

echo; echo "=== what the agent logged"
docker logs livingmod-agent-1 2>&1 | grep -v 'Permission mode forced' | tail -60 | cut -c1-220
echo; echo "=== broker requests"
tail -30 "$RUNTIME_DIR/broker/daemon.log" | cut -c1-200
for name in aria bram; do
  echo; echo "=== transcript: $name"
  python3 - "$work/$name.jsonl" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    entry = json.loads(line)
    if entry["kind"] in ("heard", "said"):
        print(("  <- " if entry["kind"] == "heard" else "  -> ") + entry["text"][:260])
    elif entry["kind"] not in ("player_chat",):
        print("  [" + entry["kind"] + "] " + str(entry.get("reason", entry.get("word", "")))[:160])
PY
done
echo; echo "=== direction"
cat "$RUNTIME_DIR/agent-workspace/repo/bible/theme.md" 2>/dev/null | head -30 | cut -c1-300
echo; echo "=== progression"
python3 - "$RUNTIME_DIR/agent-workspace/repo/bible/progression.json" <<'PY'
import json, sys
graph = json.load(open(sys.argv[1], encoding="utf-8"))
print("goal:", graph["goal"][:300])
for name, node in graph["nodes"].items():
    print(f"  {node['stage']:5} {name}: needs {node['requires']}, opens with: {node['opens_with'][:90]}")
PY
echo; echo "=== discovery plan"
cat "$RUNTIME_DIR/agent-workspace/repo/bible/discovery.md" 2>/dev/null | head -20 | cut -c1-300
echo; echo "=== shipped"
cat "$state/features.jsonl" 2>/dev/null | cut -c1-900
cat "$RUNTIME_DIR/broker/state.json"
ls "$RUNTIME_DIR/agent-workspace/repo/mods/genesis/features/" 2>/dev/null
echo; echo "=== usage by role"
python3 - "$state/llm.jsonl" <<'PY'
import collections, json, sys
totals = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
for line in open(sys.argv[1], encoding="utf-8"):
    entry = json.loads(line)
    total = totals[entry["role"]]
    total[0] += 1; total[1] += entry.get("seconds") or 0; total[2] += entry.get("estimate") or 0; total[3] += 1 if entry.get("error") else 0
for role, (calls, seconds, estimate, errors) in sorted(totals.items()):
    print(f"{role}: {calls} calls, {seconds:.0f}s, estimate {estimate:.2f}, errors {errors}")
PY

echo; echo "=== research"
ls "$RUNTIME_DIR/agent-workspace/research" 2>/dev/null | cut -c1-120
docker logs livingmod-web-1 2>/dev/null </dev/null | grep CONNECT | awk '{print $7}' | sort | uniq -c | sort -rn | head -20

echo; echo "=== which tools the builders used"
docker logs livingmod-agent-1 2>&1 | grep -E ': used ' | sed -E 's/^[^:]+: used //' | sort | uniq -c | sort -rn

echo; echo "=== checks"
if [[ -s "$RUNTIME_DIR/velocity/server-icon.png" ]]; then echo "the server icon was installed"; else echo "FAIL: no server icon"; failed=1; fi
leaks=$(cat "$work"/aria.jsonl "$work"/bram.jsonl | grep -c '"kind": "leak"')
echo "private words seen by the wrong player: $leaks"
[[ "$leaks" == 0 ]] || failed=1
for name in aria bram; do
  grep -q '"kind": "said"' "$work/$name.jsonl" || { echo "FAIL: $name never answered"; failed=1; }
  grep '"heard"' "$work/$name.jsonl" | grep -q $'§d' || { echo "FAIL: $name never heard the character"; failed=1; }
done
[[ -s "$state/features.jsonl" ]] || { echo "FAIL: nothing shipped"; failed=1; }
if cat "$work"/aria.jsonl "$work"/bram.jsonl | grep -q outsideBorder; then echo "FAIL: a player was killed by the opening border"; failed=1; fi
grep -q '"role": "watcher"' "$state/llm.jsonl" || echo "note: the watcher never ran"
echo "total time: $(elapsed)"
[[ $failed == 0 ]] && echo "M4 PASS" || echo "M4 FAILED"
exit $failed
