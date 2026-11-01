#!/usr/bin/env python3
"""What modules can hook into, proved on a real client and by reading the world's raw files. A feature plays its own sound by
name and hears about blocks broken, mobs killed, food eaten and players joining. A block's removal is noticed however it goes,
and a machine can still read its data then. A mob can be fed by using an item on it. Start with a blank world from
reset-dev-world.sh, and reset it afterwards.

Usage: python3 -m broker.tests.m16_test
"""
import base64
import json
import pathlib
import shutil
import subprocess
import sys
import time

from broker import runtime
from broker.tests.m8_test import Client, make_model, report

SOURCE = runtime.BROKER / "testsrc-m16"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "hooks"
PLAYER = "Player0"
SPOT = (40, 120, 40)
TEXTURES = ("hook_block", "hook_machine", "hook_food", "hook_token")


def make_sound(path):
    """The agent's container has what assetkit needs, and hands the file back through stdout."""
    script = ("import sys, base64; sys.path.insert(0, '/reference/assetkit'); import sounds; "
              "sounds.save(sounds.item_pickup(seed=1), '/tmp/s.ogg'); print(base64.b64encode(open('/tmp/s.ogg', 'rb').read()).decode())")
    result = runtime.run(["./scripts/stack.sh", "--profile", "agent", "run", "--rm", "-T", "agent", "python3", "-c", script], timeout=120)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(result.stdout.strip().splitlines()[-1]))


def build_source():
    """The trusted code plus the fixture, with art made the way a builder would make it."""
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "hooks"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(TEXTURES):
        data = subprocess.run([sys.executable, "assetkit/proof_texture.py", str(index + 1)], cwd=runtime.REPO,
                              stdout=subprocess.PIPE, check=True).stdout
        (textures / f"{name}.png").write_bytes(data)
    models = target / "assets" / "models"
    models.mkdir(parents=True, exist_ok=True)
    make_model(models / "hook_mob.bbmodel", "quadruped")
    make_sound(target / "assets" / "sounds" / "hook_chime.ogg")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m16-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)


def slot(name, table="items"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"hooks/{name}"]["slot"]


def rcon(*command):
    return runtime.rcon("prod", *command, check=False)


def empty_hands():
    """What's lying around first, or something dropped by the last step gets picked up and goes in the main hand instead."""
    rcon("kill", "@e[type=minecraft:item]")
    rcon("clear", PLAYER)


def chat_count(client, text):
    return client.text().count(f"[M8] chat: HOOK {text}")


def play_server_hooks(client, results):
    x, y, z = SPOT
    block, machine = slot("hook_block", "blocks"), slot("hook_machine", "blocks")
    food, token, mob = slot("hook_food"), slot("hook_token"), slot("hook_mob", "mobs")
    for command in (("gamemode", "survival", PLAYER), ("difficulty", "peaceful"), ("time", "set", "noon"),
                    ("fill", str(x - 6), str(y - 1), str(z - 6), str(x + 6), str(y - 1), str(z + 6), "minecraft:smooth_stone"),
                    ("fill", str(x - 6), str(y), str(z - 6), str(x + 6), str(y + 6), str(z + 6), "minecraft:air"),
                    ("clear", PLAYER)):
        rcon(*command)

    client.wait(rf"\[M8\] chat: HOOK joined {PLAYER}$", 60)
    results.append(report("a module hears a player join", True))

    # Its own sound, by name, heard on the client. The game drops any sound its pack doesn't have before this log line.
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "60")
    rcon("setblock", str(x), str(y), str(z + 2), block)
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z + 2}")
    client.wait(r"\[M8\] chat: HOOK chimed", 20)
    bindings = json.loads((runtime.RUNTIME / "prod" / "config" / "conduit" / "bindings.json").read_text(encoding="utf-8"))
    sound = "gm:" + bindings["sound:hooks/hook_chime"]
    results.append(report("a module plays its own sound by name, and the client has it", f"[M8] sound: {sound}" in client.text(), sound))
    rcon("setblock", str(x), str(y), str(z + 2), "minecraft:air")
    client.wait(r"\[M8\] chat: HOOK removed true", 20)

    # Really mining it, in survival, with an item whose module wants to know.
    removed_before = chat_count(client, "removed true")
    rcon("give", PLAYER, token, "1")
    rcon("setblock", str(x), str(y), str(z + 1), block)
    time.sleep(1)
    client.ask("mine 60")
    client.wait(r"\[M8\] chat: HOOK broke it, and the spot now holds Air", 20)
    results.append(report("a module hears a block broken, once it's gone", True))
    client.wait(r"\[M8\] chat: HOOK token mined true", 20)
    results.append(report("an item's module hears what it mined", True))
    time.sleep(2)
    results.append(report("a block's module hears it removed", chat_count(client, "removed true") == removed_before + 1))

    # With nobody breaking it, only its removal gets noticed.
    broken = chat_count(client, "broke it")
    removed = chat_count(client, "removed true")
    rcon("setblock", str(x), str(y), str(z + 1), block)
    rcon("setblock", str(x), str(y), str(z + 1), "minecraft:air")
    time.sleep(2)
    results.append(report("removal is noticed when a command does it, and that isn't a player breaking it",
                          chat_count(client, "removed true") == removed + 1 and chat_count(client, "broke it") == broken))

    rcon("setblock", str(x), str(y), str(z + 2), machine)
    time.sleep(2)
    rcon("setblock", str(x), str(y), str(z + 2), "minecraft:air", "destroy")
    client.wait(r"\[M8\] chat: HOOK machine held 7", 20)
    results.append(report("a machine can still read its data as it goes", True))

    # Feeding, then an item the mob's own module leaves alone, so the item's module gets it.
    empty_hands()
    rcon("give", PLAYER, food, "2")
    rcon("summon", mob, str(x), str(y), str(z + 2), "{NoAI:1b,PersistenceRequired:1b}")
    time.sleep(2)
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "31")
    time.sleep(1)
    client.ask("rightclick")
    client.wait(r"\[M8\] chat: HOOK fed", 20)
    left = rcon("clear", PLAYER, food, "0")
    results.append(report("a mob can be fed by using an item on it, and takes the item", "Found 1" in left, left))
    empty_hands()
    rcon("give", PLAYER, token, "1")
    time.sleep(1)
    client.ask("rightclick")
    client.wait(r"\[M8\] chat: HOOK token used on true", 20)
    results.append(report("an item's module hears it used on a mob", True))

    rcon("kill", f"@e[type={mob}]")
    found = client.wait(r"\[M8\] chat: HOOK killed by (\w+)", 20)
    results.append(report("a module hears a mob die, and how", True, found.group(1)))

    # Hungry first, because nobody can eat when full, and it has to be long enough to use up a full bar of saturation.
    empty_hands()
    rcon("give", PLAYER, food, "2")
    rcon("difficulty", "easy")
    rcon("effect", "give", PLAYER, "minecraft:hunger", "6", "255")
    time.sleep(7)
    client.ask("eat")
    rcon("difficulty", "peaceful")
    found = client.wait(r"\[M8\] chat: HOOK ate (\d+) of ours (\w+)", 20)
    results.append(report("a module hears something eaten, with what it was", found.group(1) == "2" and found.group(2) == "true", found.group(0)))


def main():
    build_source()
    print("building and releasing the test feature", flush=True)
    release()
    results = []
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    client = Client(runtime.WORK / "mods", runtime.REPORTS / "m16-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        play_server_hooks(client, results)
    finally:
        client.stop()
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
