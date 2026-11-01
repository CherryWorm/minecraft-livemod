#!/usr/bin/env python3
"""A bug reported with /bug, on the real agent with the real models. A feature with a real bug planted in it goes out, a player reports
it, an agent finds the cause and tells them, a fix goes through the real gates and out to the real server, and they hear that too. No
builders are allowed at all, so anything that gets built can only have come from outside the job queue. Something that isn't a bug
gets an explanation and nothing is built. Costs a few usage units. Start with a blank world from reset-dev-world.sh.

Usage: python3 -m broker.tests.m24_test
"""
import collections
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

from PIL import Image

from broker import daemon, runtime
from broker.tests.m14_test import Player, STATE, agent_up, rcon, report, results
from broker.tests.m15_test import log, state, wait_until

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "tonic"
WORKSPACE = runtime.RUNTIME / "agent-workspace"
INCOMING = WORKSPACE / "incoming_feature"
REPO = WORKSPACE / "repo"
BROKEN = "HUNGER_AFTER_DRINKING = 0"


def in_agent(*command):
    return runtime.run(["./scripts/stack.sh", "--profile", "agent", "run", "--rm", "-T", "--no-deps", "agent", *command], timeout=180, check=False)


def agent_git(*args):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(REPO), *args], capture_output=True, text=True, check=False).stdout


def seed():
    if INCOMING.exists():
        shutil.rmtree(INCOMING)
    shutil.copytree(FIXTURE, INCOMING)
    (INCOMING / "assets" / "textures").mkdir(parents=True)
    Image.new("RGBA", (16, 16), (0x88, 0x44, 0x22, 255)).save(INCOMING / "assets" / "textures" / "hearty_tonic.png")
    os.chmod(INCOMING, 0o777)
    seeded = in_agent("python3", "/spikes/m24_seed.py")
    if "seeded" not in seeded.stdout:
        print(seeded.stdout[-1500:], seeded.stderr[-1500:], flush=True)
        sys.exit(1)
    answer = daemon.promote("main", "seed")
    print(json.dumps({key: answer.get(key) for key in ("result", "gate", "reason", "tier")})[:800], flush=True)
    if answer.get("result") != "released":
        sys.exit(1)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and "players" not in rcon("list").lower():
        time.sleep(3)


def bugs():
    return state().get("bugs", {})


def status(number):
    return bugs().get(str(number), {}).get("status")


def command(player, text):
    player.conn.send(player_bot().TO_PLAY_COMMAND, player_client().string(text))


def player_bot():
    from broker.tests import m14_test
    return m14_test.bot


def player_client():
    from broker.tests import m14_test
    return m14_test.client


def test_command(dana):
    start = len(dana.heard)
    command(dana, "bug")
    report("/bug on its own says how to use it", dana.wait_for("a space, then what went wrong", 15, start))


def test_what_it_can_see(dana):
    rcon("clear", "Dana")
    rcon("give", "Dana", item_id(), "3")
    time.sleep(1)
    probed = in_agent("python3", "/spikes/m24_probe.py", "Dana", "Nobody")
    lines = [json.loads(line) for line in probed.stdout.splitlines() if line.startswith("{")]
    found = next((line.get("found") for line in lines if line["asked"] == "Dana"), None) or {}
    report("an investigator can see what a player has, by the name the game shows", any(item["name"] == "Hearty Tonic" and item["count"] == 3 for item in found.get("carrying", [])), str(found)[:400])
    report("and where they are", {"dimension", "x", "y", "z", "game_mode", "health", "food"} <= set(found), str(sorted(found)))
    report("someone who isn't online is an error, not a crash", any("isn't online" in line.get("error", "") for line in lines if line["asked"] == "Nobody"), str(lines)[-200:])


def item_id():
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger["items"]["tonic/hearty_tonic"]["slot"]


def test_real_bug(dana):
    start = len(dana.heard)
    began = time.monotonic()
    command(dana, "bug the Hearty Tonic in my hand says it fills my hunger, but when I drink it my hunger goes all the way down to nothing")
    report("the player sees their report go in", dana.wait_for("Your bug report", 15, start))
    report("and hears straight away that it's being looked at", dana.wait_for("looking into that now", 20, start))
    report("it's recorded", wait_until(lambda: status(1), 20), str(bugs())[:300])
    found = dana.wait_for("fixing it now", 420, start)
    report("the agent finds the real cause and tells the player", found, found)
    print(f"found in {round(time.monotonic() - began)}s: {found}", flush=True)
    if not found:
        return False
    entry = bugs()["1"]
    report("it names the right feature", entry.get("feature") == "tonic", str(entry)[:400])
    report("nobody's told an id", not any(word in found for word in ("gm:", "HUNGER_AFTER", ".java")), found)
    now = state()
    report("the job queue has nothing to do with it", now["queue"] == [] and now["in_flight"] == {}, str((now["queue"], now["in_flight"]))[:300])
    report("the director wasn't asked", not any(entry["role"] == "director" for entry in log("llm.jsonl")))
    # What it found can say "fixed" too, so this has to be the line that says it's done.
    done = dana.wait_for("and it's live now|on the list of", 1200, start + 1)
    print(f"finished in {round(time.monotonic() - began)}s: {done}", flush=True)
    report("the player hears when it's live", done and "live now" in done, done)
    report("it's marked as fixed", status(1) == "fixed", str(status(1)))
    source = agent_git("show", "main:mods/genesis/features/tonic/server/src/main/java/gm/feature/tonic/TonicModule.java")
    report("the bug is gone from what's out", source and BROKEN not in source, source[source.find("HUNGER"):][:120])
    live = runtime.HISTORY / str(runtime.load_state().get("current")) / "content" / "modules"
    report("what's live really is a new release, not the one with the bug", str(runtime.load_state().get("current", "")).startswith("tonic-") and live.exists(), str(runtime.load_state().get("current")))
    report("its folder is cleaned up", not (WORKSPACE / "trees" / "bug_1").exists())
    report("and its branch", "fix/bug_1" not in agent_git("branch"))
    report("a fix isn't counted as the feature being finished, for anything asked of it", not state()["requests"], str(state()["requests"])[:200])
    return True


def test_not_a_bug(dana):
    start = len(dana.heard)
    command(dana, "bug cows don't drop diamonds when I kill them")
    answered = dana.wait_for(r"\[Bug\].*(?<!looking into that now, ahead of everything else, and I'll tell you what I find\.)$", 240, start + 2)
    report("something that isn't a bug gets an answer", wait_until(lambda: status(2) in ("not_a_bug", "cant_confirm"), 240), f"{status(2)}: {answered}")
    print("heard:", dana.heard[start:], flush=True)
    report("and nothing's built for it", not (WORKSPACE / "trees" / "bug_2").exists() and bugs()["2"].get("feature") is None)


def main():
    runtime.run(["./scripts/agent-down.sh"], check=False)
    runtime.run(["./scripts/prepare-workspace.sh"])
    seed()
    # Nothing's allowed to come from the queue at all, so a fix that gets built can only have come from outside it.
    os.environ.update({"AGENT_MAX_BUILDERS": "0", "AGENT_SMALL_BUILDERS": "0"})
    dana = Player("Dana")
    agent_up()
    time.sleep(5)
    test_command(dana)
    test_what_it_can_see(dana)
    if test_real_bug(dana):
        test_not_a_bug(dana)
    print("=== everything the player heard", flush=True)
    for line in dana.heard:
        print("  " + line[:400], flush=True)
    dana.leave()
    print("=== the record", flush=True)
    for entry in log("bugs.jsonl"):
        print("  " + json.dumps(entry)[:700], flush=True)
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
