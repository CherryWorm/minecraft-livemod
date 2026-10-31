#!/usr/bin/env python3
"""What happens to what players ask for, on the real agent with the real models: a server rule changes on the spot, a
small ask gets its own small builder and reaches the game, a big one goes to the director, and the player hears about
all of it. No big builders run, so it costs a few usage units. Start with a blank world from reset-dev-world.sh.

Usage: python3 -m broker.tests.m15_test
"""
import collections
import json
import os
import sys
import time

from broker import runtime
from broker.tests.m14_test import Player, STATE, agent_up, rcon, report, results

CHARACTER = "§d"
RULE = "players_sleeping_percentage"


def state():
    return json.loads((STATE / "opening.json").read_text(encoding="utf-8"))


def log(name):
    path = STATE / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def status(number):
    return state()["requests"].get(str(number), {}).get("status")


def number_of(words):
    for entry in log("intents.jsonl"):
        if words in entry["wants"].lower():
            return entry["number"]
    return None


def wait_until(check, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(2)
    return check()


def test_big_request(dana):
    report("a request from before the restart reaches the director", wait_until(lambda: any(entry["role"] == "director" for entry in log("llm.jsonl")), 420), [entry["role"] for entry in log("llm.jsonl")])
    report("who decides what to do with it", wait_until(lambda: status(1), 30), state()["requests"])
    line = dana.wait_for(CHARACTER, 60)
    report("and the player hears what became of it", line, line)


def test_rule(dana):
    start = len(dana.heard)
    began = time.monotonic()
    dana.dm("Could we skip the night when only half of the players are sleeping?")
    report("a /dm gets a reply", dana.wait_for(CHARACTER, 60, start), dana.heard[start:])

    def changed():
        return "50" in rcon("gamerule", RULE) or "33" in rcon("gamerule", RULE)
    report("a server rule changes on the spot", wait_until(changed, 180), rcon("gamerule", RULE))
    print(f"the rule took {time.monotonic() - began:.0f}s", flush=True)
    number = wait_until(lambda: number_of("sleep") or number_of("night"), 30)
    report("the request is marked as done", wait_until(lambda: status(number) == "done", 60), state()["requests"].get(str(number)))
    time.sleep(10)
    report("and the player hears that", sum(CHARACTER in line for line in dana.heard[start:]) >= 2, dana.heard[start:])


def test_small_request(dana):
    start = len(dana.heard)
    began = time.monotonic()
    dana.dm("Could there be a simple crafting recipe that turns two gravel into one flint?")
    number = wait_until(lambda: number_of("flint"), 60)
    report("a small ask is recorded", number, log("intents.jsonl")[-1:])
    report("and given its own small builder", wait_until(lambda: status(number) == "building", 180), state()["requests"].get(str(number)))
    feature = state()["requests"].get(str(number), {}).get("feature")
    print(f"a small job called {feature} after {time.monotonic() - began:.0f}s", flush=True)

    def said():
        return [line for line in dana.heard[start:] if CHARACTER in line]
    report("the player gets a reply, then hears it's being built", wait_until(lambda: len(said()) >= 2, 60), said())
    shipped = wait_until(lambda: any(entry["feature"] == feature for entry in log("features.jsonl")), 900)
    report("it reaches the game", shipped, [entry["feature"] for entry in log("features.jsonl")])
    seconds = time.monotonic() - began
    print(f"from asking to in the game: {seconds:.0f}s", flush=True)
    report("in under 10 minutes", seconds < 600, seconds)
    report("using the small builder, not the big one", {entry["role"] for entry in log("llm.jsonl")} >= {"small_builder"} and not any(entry["role"] == "builder" for entry in log("llm.jsonl")),
           collections.Counter(entry["role"] for entry in log("llm.jsonl")))
    manifest = runtime.RUNTIME / "agent-workspace/repo/mods/genesis/features" / str(feature) / "feature.json"
    report("what it built does what was asked", manifest.exists() and "flint" in manifest.read_text(encoding="utf-8"), manifest)
    report("the request is done", wait_until(lambda: status(number) == "done", 30), state()["requests"].get(str(number)))
    report("and the player's told it's there, in a third message", wait_until(lambda: len(said()) >= 3, 60) and "flint" in said()[-1].lower(), said())


def test_asking_about_it(dana):
    time.sleep(10)  # So that nothing still on its way can be taken for the answer.
    start = len(dana.heard)
    before = len(log("intents.jsonl"))
    dana.dm("What happened to my request for a new dimension with rockets?")
    line = dana.wait_for(CHARACTER, 60, start)
    report("/dm can say what became of a request", line and "dimension" in line.lower(), line)
    time.sleep(3)
    report("asking about one doesn't count as a new request", len(log("intents.jsonl")) == before, log("intents.jsonl")[before:])
    start = len(dana.heard)
    dana.dm("Are you building anything right now? How many things?")
    line = dana.wait_for(CHARACTER, 60, start)
    report("and whether anything's being built", line, line)
    report("without naming what's still to come", line and not any(feature["id"].split("_")[0] in line.lower() for feature in state()["queue"]), state()["queue"][:1])


def test_restart(dana):
    # With no big builders running, what the director chose is still waiting.
    queued = [feature["id"] for feature in state()["queue"]]
    report("what's waiting to be built is saved", queued, queued)
    calls = sum(entry["role"] == "director" for entry in log("llm.jsonl"))
    agent_up()
    time.sleep(40)
    report("and survives a restart", [feature["id"] for feature in state()["queue"]] == queued, state()["queue"])
    report("without asking the director again", sum(entry["role"] == "director" for entry in log("llm.jsonl")) == calls)


def main():
    runtime.run(["./scripts/agent-down.sh"], check=False)
    runtime.run(["./scripts/prepare-workspace.sh"])
    runtime.run(["./scripts/stack.sh", "--profile", "agent", "run", "--rm", "-T", "agent", "python3", "/spikes/m15_seed.py"], timeout=180)
    os.environ.update({"AGENT_MAX_BUILDERS": "0", "AGENT_SMALL_BUILDERS": "1"})
    dana = Player("Dana")
    agent_up()
    test_big_request(dana)
    test_rule(dana)
    test_small_request(dana)
    test_asking_about_it(dana)
    test_restart(dana)
    print("=== everything the player heard", flush=True)
    for line in dana.heard:
        print("  " + line[:400], flush=True)
    dana.leave()
    runtime.run(["./scripts/agent-down.sh"], check=False)

    totals = collections.defaultdict(lambda: [0, 0.0])
    for entry in log("llm.jsonl"):
        totals[entry["role"]][0] += 1
        totals[entry["role"]][1] += entry.get("estimate") or 0
    print({role: (calls, round(usage, 3)) for role, (calls, usage) in totals.items()}, flush=True)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
