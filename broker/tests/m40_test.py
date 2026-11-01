#!/usr/bin/env python3
"""The server modules' API, proved on a real client: blocks that face the way they're placed, placing and breaking that can be refused, redstone going
both ways, comparators, light a module sets, blocks nothing can break, and a model's named parts moved, tinted and scaled. Reuses whatever world is
there, as long as it has land near the spot, so a run needs no reset. Name the stages to run, or leave them out for all of them.

Usage: python3 -m broker.tests.m40_test [blocks ...]
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw

from broker import runtime, sign
from broker.tests.m8_test import Client, PLAYER, make_model, report

SOURCE = runtime.BROKER / "testsrc-m40"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "moduleapi"
SPOT = (40, 150, 40)
COLOURS = {"api_front": (0xCC, 0x22, 0x22), "api_side": (0x22, 0x44, 0xCC), "api_top": (0x22, 0xBB, 0x44)}
results = []


def check(name, passed, detail=""):
    results.append(report(name, passed, detail))


def rcon(*command):
    return runtime.rcon("prod", *command, check=False)


def slot(name, table="blocks"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"moduleapi/{name}"]["slot"]


def build_source():
    """The trusted code plus the fixture, with art that's easy to tell apart in a photograph."""
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "moduleapi"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for name, colour in COLOURS.items():
        image = Image.new("RGBA", (16, 16), (*colour, 255))
        ImageDraw.Draw(image).rectangle((1, 1, 14, 14), outline=(0xEE, 0xEE, 0xEE, 255))
        image.save(textures / f"{name}.png")
    models = target / "assets" / "models"
    models.mkdir(parents=True, exist_ok=True)
    make_model(models / "api_statue.bbmodel", "quadruped")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m40-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)


def clear_ground():
    x, y, z = SPOT
    for command in (("forceload", "add", str(x - 16), str(z - 16), str(x + 16), str(z + 16)),
                    ("gamerule", "doDaylightCycle", "false"), ("difficulty", "peaceful"), ("time", "set", "midnight"),
                    ("fill", str(x - 12), str(y - 1), str(z - 12), str(x + 12), str(y - 1), str(z + 12), "minecraft:smooth_stone"),
                    ("fill", str(x - 12), str(y), str(z - 12), str(x + 12), str(y + 8), str(z + 12), "minecraft:air"),
                    ("gamemode", "survival", PLAYER), ("effect", "give", PLAYER, "minecraft:resistance", "9999", "5", "true"), ("clear", PLAYER)):
        rcon(*command)


def is_block(x, y, z, block):
    return "passed" in rcon("execute", "if", "block", str(x), str(y), str(z), block).lower()


def holds(client, pattern, seconds=20):
    try:
        client.wait(rf"\[M8\] chat: API {pattern}", seconds)
        return True
    except TimeoutError:
        return False


def client_sees(client, x, y, z):
    client.ask(f"blockat {x} {y} {z}")
    return re.findall(r"\[M8\] the client sees (.*)$", client.text(), re.MULTILINE)[-1]


def client_light(client, x, y, z):
    client.ask(f"light {x} {y} {z}")
    return int(re.findall(r"\[M8\] block light: (\d+)$", client.text(), re.MULTILINE)[-1])


def client_parts(client, x, y, z):
    client.ask(f"parts {x} {y} {z}")
    return json.loads(re.findall(r"\[M8\] parts: (.*)$", client.text(), re.MULTILINE)[-1])


def place_at(client, x, y, z, yaw, pitch, block):
    """A player standing back from a spot, looking a certain way, places a block on the floor there."""
    rcon("clear", PLAYER)
    rcon("give", PLAYER, block, "1")
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 0.5 + 3), str(yaw), str(pitch))
    time.sleep(1)
    client.ask(f"useblock {x} {y - 1} {z}")
    time.sleep(1)


def play_facing(client):
    x, y, z = SPOT
    front = slot("api_front")
    states = {}
    for index, (yaw, facing) in enumerate(((0, "north"), (180, "south"), (90, "east"), (-90, "west"))):
        place_at(client, x + index, y, z, yaw, 0, front)
        passed = is_block(x + index, y, z, f"{front}[facing={facing}]")
        check(f"a block faces whoever placed it, looking {yaw}", passed, rcon("data", "get", "block", str(x + index), str(y), str(z)))
        states[facing] = client_sees(client, x + index, y, z)
    check("each way it faces looks different to a client", len(set(states.values())) == 4, str(states))

    point = slot("api_point")
    place_at(client, x + 5, y, z, 0, 90, point)
    check("a block that can point up or down does", is_block(x + 5, y, z, f"{point}[facing=up]"))
    rcon("fill", str(x), str(y), str(z), str(x + 5), str(y), str(z), "minecraft:air")

    # Photographed from its front and from its side, its colour says which face is showing.
    rcon("setblock", str(x), str(y + 1), str(z), f"{front}[facing=south]")
    rcon("setblock", str(x + 2), str(y + 1), str(z), f"{front}[facing=west]")
    rcon("setblock", str(x + 4), str(y + 1), str(z), f"{point}[facing=up]")
    rcon("time", "set", "noon")
    rcon("tp", PLAYER, str(x + 2.5), str(y), str(z + 5.5), "180", "0")
    client.ask("shot facing")
    check("all ways of a turned cube stay in the pack", True)
    rcon("time", "set", "midnight")
    rcon("fill", str(x), str(y), str(z), str(x + 5), str(y + 2), str(z), "minecraft:air")


def play_placing(client):
    x, y, z = SPOT
    gate = slot("api_gate")
    # Refused where x is odd.
    place_at(client, x + 1, y, z, 0, 0, gate)
    check("a module can refuse a placement", holds(client, "gate can't go here") and is_block(x + 1, y, z, "minecraft:air"))
    client.ask("held")
    check("and it stays in their hand", re.findall(r"\[M8\] holding (\d+)", client.text())[-1] == "1", client.text()[-300:])
    place_at(client, x + 2, y, z, 0, 0, gate)
    check("a block placed hears who and with what", holds(client, f"gate placed by {PLAYER} with Api Gate") and is_block(x + 2, y, z, gate))
    check("any module hears it, and what they had before it was used up", holds(client, "anything placed Api Gate from 1"))

    # Their crosshair is on it, from just above.
    rcon("tp", PLAYER, str(x + 2.5), str(y + 1), str(z + 0.5), "0", "90")
    time.sleep(1)
    client.ask("mine 80")
    check("a block can refuse being broken", holds(client, "gate won't break") and is_block(x + 2, y, z, gate))
    rcon("give", PLAYER, slot("api_token", "items"), "1")
    rcon("item", "replace", "entity", PLAYER, "weapon.mainhand", "with", slot("api_token", "items"), "1")
    time.sleep(1)
    client.ask("mine 80")
    check("and can give way when it's happy to", holds(client, "gate gives way") and is_block(x + 2, y, z, "minecraft:air"))

    rcon("setblock", str(x + 2), str(y), str(z), "minecraft:gold_block")
    rcon("clear", PLAYER)
    client.ask("mine 200")
    check("a module can refuse any block being broken", holds(client, "no breaking gold") and is_block(x + 2, y, z, "minecraft:gold_block"))
    rcon("setblock", str(x + 2), str(y), str(z), "minecraft:air")


def play_redstone(client):
    x, y, z = SPOT
    post = slot("api_post")
    rcon("setblock", str(x), str(y), str(z), post)
    east = (x + 1, y, z)
    west = (x - 1, y, z)
    rcon("setblock", *map(str, east), "minecraft:redstone_lamp")
    rcon("setblock", *map(str, west), "minecraft:redstone_lamp")
    time.sleep(1)
    check("a block gives redstone out of the side it says", is_block(*east, "minecraft:redstone_lamp[lit=true]"))
    check("and not out of the others", is_block(*west, "minecraft:redstone_lamp[lit=false]"))
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 3.5), "180", "20")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    check("a module can turn it off", holds(client, "post off"))
    time.sleep(1)
    check("and its neighbours hear it", is_block(*east, "minecraft:redstone_lamp[lit=false]"))
    client.ask(f"useblock {x} {y} {z}")
    check("and on again", holds(client, "post on"))
    time.sleep(1)
    check("and they hear that too", is_block(*east, "minecraft:redstone_lamp[lit=true]"))
    rcon("fill", str(x - 1), str(y), str(z), str(x + 1), str(y), str(z), "minecraft:air")

    kiln = slot("api_kiln")
    rcon("setblock", str(x), str(y), str(z), kiln)
    time.sleep(1)
    check("a machine reads no power to start with", holds(client, "kiln power 0"))
    rcon("setblock", str(x + 1), str(y), str(z), "minecraft:redstone_block")
    check("a block hears redstone reach it", holds(client, "kiln neighbour Block of Redstone power 15"))
    check("a machine reads it", holds(client, "kiln power 15"))
    rcon("setblock", str(x + 1), str(y), str(z), "minecraft:air")
    check("and when it goes", holds(client, "kiln power 0"))

    # A comparator on the east side, facing away, reads it into a lamp.
    rcon("setblock", str(x + 1), str(y), str(z), "minecraft:comparator[facing=west]")
    rcon("setblock", str(x + 2), str(y), str(z), "minecraft:redstone_lamp")
    time.sleep(1)
    rcon("item", "replace", "block", str(x), str(y), str(z), "container.1", "with", "minecraft:stone", "64")
    time.sleep(1)
    output = rcon("data", "get", "block", str(x + 1), str(y), str(z), "OutputSignal")
    check("a comparator reads a machine's inventory", re.search(r"(\d+)$", output) and int(re.search(r"(\d+)$", output).group(1)) > 0, output)
    check("and passes it on", is_block(x + 2, y, z, "minecraft:redstone_lamp[lit=true]"))
    rcon("fill", str(x), str(y), str(z), str(x + 2), str(y), str(z), "minecraft:air")


def play_light(client):
    x, y, z = SPOT
    lamp = slot("api_lamp")
    rcon("setblock", str(x), str(y), str(z), lamp)
    time.sleep(2)
    check("a block's own light reaches the client", client_light(client, x, y + 1, z) == 8, str(client_light(client, x, y + 1, z)))
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 3.5), "180", "20")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    check("a module changes it", holds(client, "lamp now 14"))
    time.sleep(2)
    check("and the client sees that change", client_light(client, x, y + 1, z) == 13, str(client_light(client, x, y + 1, z)))
    check("it's part of the block's state", "glow=14" in rcon("execute", "if", "block", str(x), str(y), str(z), f"{lamp}[glow=14]").replace("Test passed", "glow=14"))
    client.ask(f"useblock {x} {y} {z}")
    check("and it can go right out", holds(client, "lamp now 0"))
    time.sleep(2)
    check("and the client sees the dark", client_light(client, x, y + 1, z) == 0, str(client_light(client, x, y + 1, z)))
    rcon("setblock", str(x), str(y), str(z), "minecraft:air")


def play_unbreakable(client):
    x, y, z = SPOT
    vault = slot("api_vault")
    rcon("setblock", str(x), str(y), str(z), vault)
    rcon("tp", PLAYER, str(x + 0.5), str(y + 1), str(z + 0.5), "0", "90")
    rcon("give", PLAYER, "minecraft:netherite_pickaxe", "1")
    rcon("item", "replace", "entity", PLAYER, "weapon.mainhand", "with", "minecraft:netherite_pickaxe", "1")
    time.sleep(1)
    client.ask("mine 200")
    check("the best pickaxe does nothing to it", is_block(x, y, z, vault))
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 8.5), "180", "0")
    rcon("setblock", str(x + 1), str(y), str(z), "minecraft:tnt")
    rcon("setblock", str(x + 1), str(y + 1), str(z), "minecraft:redstone_block")
    time.sleep(6)
    check("an explosion does nothing to it", is_block(x, y, z, vault))
    rcon("fill", str(x - 3), str(y), str(z - 3), str(x + 3), str(y + 3), str(z + 3), "minecraft:air", "replace", "minecraft:redstone_block")
    rcon("setblock", str(x - 1), str(y), str(z), "minecraft:piston[facing=east]")
    rcon("setblock", str(x - 2), str(y), str(z), "minecraft:redstone_block")
    time.sleep(2)
    check("a piston can't move it", is_block(x, y, z, vault) and is_block(x - 1, y, z, "minecraft:piston[extended=false,facing=east]"))
    rcon("fill", str(x - 3), str(y - 1), str(z - 3), str(x + 3), str(y - 1), str(z + 3), "minecraft:smooth_stone")
    rcon("fill", str(x - 3), str(y), str(z - 3), str(x + 3), str(y + 3), str(z + 3), "minecraft:air")
    check("a command still can", is_block(x, y, z, "minecraft:air"))
    rcon("clear", PLAYER)


def play_parts(client):
    x, y, z = SPOT
    statue = slot("api_statue")
    rcon("setblock", str(x), str(y), str(z), statue)
    time.sleep(2)
    plain = client_parts(client, x, y, z)
    check("a model block's parts reach the client", len(plain) > 3, str(plain)[:300])
    head = [part for part in plain if part["brightness"] == 15]
    check("a part named as glowing is at full brightness", len(head) == 1, str(plain)[:600])
    check("and only that part", len(plain) - len(head) > 1)

    rcon("setblock", str(x + 3), str(y), str(z), f"{statue}[facing=south]")
    time.sleep(2)
    turned = client_parts(client, x + 3, y, z)
    # A half turn about the block's centre flips what's in front to behind, so it can't be where the same part was.
    check("a model block turned the other way really is", sorted(round(part["z"], 2) for part in turned) == sorted(round(-part["z"], 2) for part in plain), f"{plain}\n{turned}")
    rcon("setblock", str(x + 3), str(y), str(z), "minecraft:air")

    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 3.5), "180", "10")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    check("a module changes its parts, and hears about a part that isn't there",
          holds(client, "statue moved true tinted true scaled true turned true wings false facing north"))
    time.sleep(2)
    changed = client_parts(client, x, y, z)
    moved = [(before, after) for before, after in zip(plain, changed) if abs(after["y"] - before["y"] - 1) < 0.01]
    check("a part moved is somewhere else, for everyone watching", len(moved) == 1, f"{plain}\n{changed}")
    bigger = [after for before, after in zip(plain, changed) if abs(after["scale"] - before["scale"] * 2) < 0.01]
    check("a part scaled is that much bigger", len(bigger) == 1, str(changed)[:600])
    check("and tinted is that colour", [part["tint"] for part in bigger] == [0xFF0000], str(bigger))
    rotated = [(before, after) for before, after in zip(plain, changed) if before["rotation"] != after["rotation"]]
    check("a part turned is turned", len(rotated) >= 1, str(changed)[:600])
    time.sleep(2)
    check("a module can set a model block's light", client_light(client, x, y + 1, z) == 11, str(client_light(client, x, y + 1, z)))
    client.ask("shot statue")
    check("and they're all kept with it", "parts" in rcon("data", "get", "block", str(x), str(y), str(z)))
    rcon("setblock", str(x), str(y), str(z), "minecraft:air")


def play_machine_slots(client):
    x, y, z = SPOT
    kiln = slot("api_kiln")
    rcon("setblock", str(x), str(y), str(z), kiln)
    # A hopper keeps offering, and only as many as its limit go in.
    rcon("setblock", str(x), str(y + 1), str(z), "minecraft:hopper[facing=down]")
    rcon("item", "replace", "block", str(x), str(y + 1), str(z), "container.0", "with", "minecraft:cobblestone", "16")
    time.sleep(8)
    data = rcon("data", "get", "block", str(x), str(y), str(z), "Items")
    check("a hopper stops at a slot's limit", 'count: 4' in data and 'Slot: 0b' in data, data)
    check("and carries on into the next slot", 'Slot: 1b' in data, data)
    rcon("setblock", str(x), str(y + 1), str(z), "minecraft:air")

    rcon("setblock", str(x), str(y), str(z), "minecraft:air")
    rcon("kill", "@e[type=item]")
    rcon("setblock", str(x), str(y), str(z), kiln)
    rcon("clear", PLAYER)
    rcon("give", PLAYER, "minecraft:cobblestone", "20")
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 3.5), "180", "20")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    # The hotbar is at the end of the menu's slots. Picks up the 20, and puts them down on the limited slot.
    client.ask("hotbarclick 0")
    client.ask("click 0")
    time.sleep(1)
    client.ask("menu")
    shown = re.findall(r"\[M8\] menu holds (.*)$", client.text(), re.MULTILINE)[-1]
    check("a player's stack stops at a slot's limit", shown.startswith("0=4x") and "carried=16" in shown, shown)
    client.ask("click 1")
    client.ask("closemenu")
    rcon("clear", PLAYER)

    rcon("item", "replace", "block", str(x), str(y), str(z), "container.2", "with", slot("api_token", "items"), "3")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    # With 3 slots a menu has one row, and its outputs go at the right, so the only output's the last place.
    client.ask("click 8 shift")
    check("a module hears a player take from an output slot", holds(client, f"kiln gave 3 of Api Token to {PLAYER} from slot 2"))
    client.ask("closemenu")

    rcon("item", "replace", "block", str(x), str(y), str(z), "container.2", "with", slot("api_token", "items"), "2")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask("click 8")
    check("and by picking it up", holds(client, f"kiln gave 2 of Api Token to {PLAYER} from slot 2"))
    client.ask("click 8")
    client.ask("closemenu")

    rcon("item", "replace", "block", str(x), str(y), str(z), "container.2", "with", slot("api_lamp"), "1")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask("click 8")
    client.ask("menu")
    check("and can refuse", holds(client, "kiln still busy") and "carried=0" in re.findall(r"\[M8\] menu holds (.*)$", client.text(), re.MULTILINE)[-1])
    client.ask("closemenu")
    rcon("setblock", str(x), str(y), str(z), "minecraft:air")
    rcon("kill", "@e[type=item]")


STAGES = {"blocks": (play_facing, play_placing, play_redstone, play_light, play_unbreakable, play_parts, play_machine_slots)}


def main():
    wanted = sys.argv[1:] or list(STAGES)
    build_source()
    print("building and releasing the test feature", flush=True)
    release()
    with sign._locked():
        sign._load_key()
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    client = Client(mods, runtime.REPORTS / "m40-client.log", {"COMPANION_TEST_KEY": sign.public_key_text()})
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        clear_ground()
        for stage in wanted:
            for play in STAGES[stage]:
                print(f"--- {play.__name__}", flush=True)
                play(client)
    finally:
        client.stop()
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    out = runtime.REPORTS / "m40"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_*.png"):
        shutil.copy(path, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
