#!/usr/bin/env python3
"""Dimensions on a real client. A release brings one with its own biome and type, and the player goes there and back, stands on real ground,
and finds ore, plants, ruins and mobs that belong to it and aren't in the overworld. An empty one gets a platform. A later release adds one
with no restart. Then a real rollback takes that one away with someone in it: the world still loads, they're brought back to where they
came from, and when it's released again what was built there is still there. Start with a blank world from reset-dev-world.sh and a
baseline, and reset it afterwards.

Usage: python3 -m broker.tests.m25_test
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

from PIL import Image

from broker import deploy, runtime
from broker.tests.m8_test import Client, PLAYER, SPOT, make_model
from broker.tests.m14_test import report, results

SOURCE = runtime.BROKER / "testsrc-m25"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "realms"
TEXTURES = {"realm_ore": (0x99, 0x33, 0x66), "realm_bloom": (0x66, 0x99, 0x33), "realm_key": (0x33, 0x66, 0x99)}
OVERWORLD = "minecraft:overworld"
# The flat land's layers, from the bottom of the world at -64: one of bedrock, 60 of stone, one of grass.
MOOR_GROUND_Y = -3
AMBIENT_LIGHT = 0.5
MARKER = "minecraft:diamond_block"
NEARLY = 2
GRADLE_COPY = "gradle-m25"


def own_gradle_home():
    """This releases with a client connected, and Gradle can't share its caches between two containers while one of them is running."""
    copy = runtime.RUNTIME / "cache" / GRADLE_COPY
    if not copy.exists():
        shutil.copytree(runtime.RUNTIME / "cache" / "gradle", copy, symlinks=True)
    return f"/cache/{GRADLE_COPY}"


def target():
    return SOURCE / "mods" / "genesis" / "features" / "realms"


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    if target().exists():
        shutil.rmtree(target())
    shutil.copytree(FIXTURE, target())
    textures = target() / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for name, colour in TEXTURES.items():
        Image.new("RGBA", (16, 16), (*colour, 255)).save(textures / f"{name}.png")
    models = target() / "assets" / "models"
    models.mkdir(parents=True, exist_ok=True)
    make_model(models / "realm_grazer.bbmodel", "quadruped")


def add_dell():
    """A dimension that needs nothing new from the game, so it should need no restart."""
    path = target() / "feature.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["dimensions"]["dell"] = {"display": "The Dell", "generator": {
        "type": "minecraft:noise", "settings": "minecraft:floating_islands", "biome_source": {"type": "minecraft:fixed", "biome": "minecraft:plains"}}}
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m25-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)
    return promoted


def ledger():
    return json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))


def slot(name, table="items"):
    return "gm:" + ledger()[table][f"realms/{name}"]["slot"]


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def holding(item):
    rcon("clear", PLAYER)
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", item, 1)
    time.sleep(1)


def where(client):
    """What the player's own game says about where they are."""
    client.ask("where")
    return json.loads(re.findall(r"\[M8\] where: (.*)$", client.text(), re.MULTILINE)[-1])


def go(client, item):
    holding(item)
    client.ask("use")
    time.sleep(3)
    return where(client)


def started_at():
    return runtime.inspect_state("prod")["StartedAt"]


def mobs_in(dimension, mob):
    """Saying how far away is what stops a selector looking through every dimension."""
    return rcon("execute", "in", dimension, "positioned", 0, 0, 0, "if", "entity", f"@e[type={mob},distance=0..]")


def count_blocks(regions, block):
    """Reads the world's raw files, so this can't be fooled by the mod's own idea of what it placed."""
    sys.path.insert(0, str(runtime.REPO / "broker" / "gates"))
    from world_diff import decode, read_chunks

    total = 0
    for path in regions.glob("*.mca"):
        for _, _, chunk in read_chunks(path):
            for section in chunk.get("sections", []):
                blocks, palette = decode(section)
                if block in palette:
                    total += blocks.count(palette.index(block))
    return total


def dimension_folder(dimension):
    namespace, name = dimension.split(":")
    return runtime.RUNTIME / "prod" / "world" / "dimensions" / namespace / name


def settle(seconds=60):
    """Waits for the patches to finish on what's loaded, and for it to reach the disk."""
    mark = runtime.utc_now()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(5)
        found = re.findall(r"retrogen: queued=(\d+)", runtime.logs_since("prod", mark))
        if found and found[-1] == "0":
            break
    rcon("save-all", "flush")
    time.sleep(5)


def check_moor(client):
    x, y, z = SPOT
    moor = slot("moor", "dimensions")
    here = go(client, slot("moor_key"))
    report("a door into a dimension takes the player there", here["dimension"] == moor, here)
    report("they arrive at its spawn", abs(here["x"] - 8) <= NEARLY and abs(here["z"] - 8) <= NEARLY, here)
    report("standing on its ground, not falling or buried", here["y"] == MOOR_GROUND_Y + 1 and "grass_block" in here["under"], here)
    report("the player's game has the dimension's own type", abs(here["ambient"] - AMBIENT_LIGHT) < 0.001, here)
    report("and its own biome", here["biome"].startswith("gm:b"), here)

    # Being there is what makes land for the patches, and for mobs to appear in.
    deadline = time.monotonic() + 90
    found = ""
    grazer = slot("realm_grazer", "mobs")
    while time.monotonic() < deadline and "Test passed" not in found:
        time.sleep(3)
        found = mobs_in(moor, grazer)
    report("a mob made for the dimension appears there", "Test passed" in found, found)
    found = mobs_in(OVERWORLD, grazer)
    report("and not in the overworld", "Test failed" in found, found)

    settle()
    regions = dimension_folder(moor) / "region"
    for block, name in ((slot("realm_ore", "blocks"), "ore"), (slot("realm_bloom", "blocks"), "plants"), ("minecraft:gold_block", "ruins")):
        there = count_blocks(regions, block) if regions.exists() else 0
        report(f"{name} made for the dimension are in it", there > 0, f"{there} of {block}")
    overworld = dimension_folder(OVERWORLD) / "region"
    for block, name in ((slot("realm_ore", "blocks"), "ore"), (slot("realm_bloom", "blocks"), "plants")):
        elsewhere = count_blocks(overworld, block)
        report(f"and its {name} aren't in the overworld", elsewhere == 0, elsewhere)

    home = go(client, slot("way_home"))
    report("the way back goes to the overworld", home["dimension"] == OVERWORLD, home)
    report("right where they left", abs(home["x"] - x) <= NEARLY and abs(home["y"] - y) <= NEARLY and abs(home["z"] - z) <= NEARLY, home)


def check_empty(client):
    empty = slot("void", "dimensions")
    here = go(client, slot("void_key"))
    report("in a dimension with nothing in it, the player gets somewhere to stand", here["dimension"] == empty and "stone" in here["under"], here)
    time.sleep(3)
    still = where(client)
    report("and stays there", still["y"] == here["y"], still)
    go(client, slot("way_home"))


def check_no_restart(client):
    before = started_at()
    add_dell()
    promoted = release()
    report("a dimension that needs nothing new from the game is released with no restart", promoted.get("tier") != "T3" and started_at() == before, promoted.get("tier"))
    dell = slot("dell", "dimensions")
    here = go(client, slot("dell_key"))
    report("and the player can go there, without rejoining", here["dimension"] == dell, here)
    report("a module can get at it by name", client.wait(rf"\[M8\] chat: REALMS going to {dell}", 10) is not None)
    report("its land was made by the game's own generator", here["y"] > 0, here)
    answer = rcon("execute", "in", dell, "run", "setblock", here["x"], here["y"] + 2, here["z"], MARKER)
    report("building there works", "Changed" in answer, answer)
    return dell, (here["x"], here["y"] + 2, here["z"])


def check_rollback(client, dell, marker, last_without):
    """The real thing: this is what the broker does when a release goes wrong, and it leaves someone in a dimension that's no longer declared."""
    client.stop()
    time.sleep(3)
    state = runtime.load_state()
    state["current"] = last_without
    deploy.rollback(state, "testing that a dimension can go away")
    runtime.save_state(state)
    report("the world still loads after a rollback takes a dimension away", "players online" in rcon("list"), rcon("list"))
    known = json.loads((runtime.RUNTIME / "prod" / "config" / "conduit" / "dimensions.json").read_text(encoding="utf-8"))
    report("and that dimension is no longer declared", dell not in known, sorted(known))
    report("its land is still on disk", (dimension_folder(dell) / "region").exists())
    regions = (runtime.RUNTIME / "prod" / "logs" / "latest.log").read_text(encoding="utf-8", errors="replace")
    report("and nothing was logged as wrong with it", "Can't open dimension" not in regions)


def check_back(client, dell, marker):
    x, y, z = SPOT
    client.wait(r"\[M8\] chat: The place you were in isn't there any more", 60)
    report("someone left inside it is told what happened", True)
    time.sleep(3)
    here = where(client)
    report("and brought back to where they came from", here["dimension"] == OVERWORLD and abs(here["x"] - x) <= NEARLY and abs(here["z"] - z) <= NEARLY, here)

    promoted = release()
    report("releasing it again works", promoted.get("result") == "released", promoted.get("result"))
    again = go(client, slot("dell_key"))
    report("and the door works again", again["dimension"] == dell, again)
    found = rcon("execute", "in", dell, "if", "block", *marker, MARKER)
    report("with what was built there still there", "Test passed" in found, found)


def main():
    build_source()
    print("releasing the test feature", flush=True)
    promoted = release()
    report("a dimension with its own biome or type is released with a restart", promoted.get("tier") == "T3", promoted.get("tier"))
    last_without = runtime.load_state()["current"]
    os.environ["CLIENT_TEST"] = "knowledge"
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    # A folder of its own too, for the same reason.
    mods = runtime.WORK / "mods-client"
    runtime.sync_tree(runtime.WORK / "mods", mods, "build/", ".gradle/", "run/", exact=True)
    gradle_home = own_gradle_home()
    client = Client(mods, runtime.REPORTS / "m25-client.log", gradle_home=gradle_home)
    x, y, z = SPOT
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(15)
        # Creative until there's a floor, because the fall from up here can kill a player waiting for the chunks to load.
        rcon("gamemode", "creative", PLAYER)
        rcon("tp", PLAYER, x, y + 5, z, 0, 0)
        time.sleep(3)
        for command in (("difficulty", "peaceful"), ("time", "set", "noon"),
                        ("fill", x - 4, y - 1, z - 4, x + 4, y + 3, z + 4, "minecraft:air"),
                        ("fill", x - 4, y - 1, z - 4, x + 4, y - 1, z + 4, "minecraft:smooth_stone")):
            rcon(*command)
        rcon("tp", PLAYER, x, y, z, 0, 0)
        time.sleep(1)
        rcon("gamemode", "survival", PLAYER)
        check_moor(client)
        check_empty(client)
        dell, marker = check_no_restart(client)
        check_rollback(client, dell, marker, last_without)
        client = Client(mods, runtime.REPORTS / "m25-client-2.log", gradle_home=gradle_home)
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        check_back(client, dell, marker)
    finally:
        client.stop()
        shutil.rmtree(runtime.RUNTIME / "cache" / GRADLE_COPY, ignore_errors=True)

    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
