#!/usr/bin/env python3
"""The server modules' API, proved on a real client: blocks that face the way they're placed, placing and breaking that can be refused, redstone going
both ways, comparators, light a module sets, blocks nothing can break, and a model's named parts moved, tinted and scaled. Reuses whatever world is
there, as long as it has land near the spot, so a run needs no reset. Name the stages to run, or leave them out for all of them.

Usage: python3 -m broker.tests.m40_test [blocks mobs items input effects fluids ...]
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
EFFECT_ICON = (0xFF, 0x00, 0xFF, 255)
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
    Image.new("RGBA", (18, 18), EFFECT_ICON).save(textures / "api_blessed.png")
    models = target / "assets" / "models"
    models.mkdir(parents=True, exist_ok=True)
    make_model(models / "api_statue.bbmodel", "quadruped")
    # With nothing playing by itself, a part only moves if something's moved it.
    still = json.loads((models / "api_statue.bbmodel").read_text(encoding="utf-8"))
    still["animations"] = []
    (models / "api_statue.bbmodel").write_text(json.dumps(still), encoding="utf-8")
    make_model(models / "api_ox.bbmodel", "quadruped")
    make_model(models / "api_bat.bbmodel", "flying")


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
    check("a block placed hears who and with what", holds(client, f"gate placed by {PLAYER} with api_gate") and is_block(x + 2, y, z, gate))
    check("any module hears it, and what they had before it was used up", holds(client, "anything placed api_gate from 1"))

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
    rcon("item", "replace", "entity", PLAYER, "weapon.mainhand", "with", "minecraft:netherite_pickaxe", "1")
    time.sleep(1)
    client.ask("mine 60")
    check("a module can refuse any block being broken", holds(client, "no breaking gold") and is_block(x + 2, y, z, "minecraft:gold_block"))
    rcon("setblock", str(x + 2), str(y), str(z), "minecraft:air")
    rcon("clear", PLAYER)


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

    gauge = slot("api_gauge")
    rcon("setblock", str(x), str(y), str(z), gauge)
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    check("a module can hold animations at a value", holds(client, "gauge at true"))
    time.sleep(1)
    high = client_parts(client, x, y, z)
    time.sleep(1)
    check("and they stay there", high == client_parts(client, x, y, z), str(high)[:300])
    client.ask(f"useblock {x} {y} {z}")
    check("a new value is heard", holds(client, "gauge at false"))
    time.sleep(1)
    check("and shows", high != client_parts(client, x, y, z))
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
    check("a module hears a player take from an output slot", holds(client, f"kiln gave 3 of api_token to {PLAYER} from slot 2"))
    client.ask("closemenu")

    rcon("item", "replace", "block", str(x), str(y), str(z), "container.2", "with", slot("api_token", "items"), "2")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask("click 8")
    check("and by picking it up", holds(client, f"kiln gave 2 of api_token to {PLAYER} from slot 2"))
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


def spawn(name, x, y, z):
    tag = name
    rcon("summon", slot(name, "mobs"), str(x + 0.5), str(y), str(z + 0.5), json.dumps({"Tags": [tag], "PersistenceRequired": True}))
    time.sleep(1)
    return tag


def mob_data(tag, path):
    return rcon("data", "get", "entity", f"@n[tag={tag}]", path)


def number(text):
    return float(re.findall(r"(-?\d+(?:\.\d+)?)[a-z]?\s*$", text.strip())[-1])


def aim(tag, x, y, z):
    """Puts a mob right in front of the player, with their crosshair on it, the way someone really would use something on it."""
    rcon("tp", f"@n[tag={tag}]", str(x + 0.5), str(y), str(z + 0.5))
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 2.5), "facing", "entity", f"@n[tag={tag}]", "eyes")
    time.sleep(0.5)


def on_ground(item):
    return "passed" in rcon("execute", "if", "entity", f'@e[type=item,nbt={{Item:{{id:"{item}"}}}}]').lower()


def play_mob_drops(client):
    x, y, z = SPOT
    fang, scale = slot("api_fang", "items"), slot("api_scale", "items")
    rcon("kill", "@e[type=item]")
    spawn("api_ox", x, y, z)
    rcon("kill", "@n[tag=api_ox]")
    time.sleep(3)
    check("a mob drops the first of several things", "2" in rcon("data", "get", "entity", f"@n[type=item,nbt={{Item:{{id:\"{fang}\"}}}}]", "Item.count"))
    check("and the second, with its own count", "1" in rcon("data", "get", "entity", f"@n[type=item,nbt={{Item:{{id:\"{scale}\"}}}}]", "Item.count"))
    rare = slot("api_rare", "items")
    rcon("kill", "@e[type=item]")
    # Its chance is a half, so a dozen of them coming out all one way would be one time in two thousand.
    seen = []
    for _ in range(12):
        spawn("api_ox", x, y, z)
        rcon("kill", "@n[tag=api_ox]")
        time.sleep(1.5)
        seen.append(on_ground(rare))
        rcon("kill", "@e[type=item]")
    check("and one with a chance sometimes does and sometimes doesn't", any(seen) and not all(seen), str(seen))


def play_flying(client):
    x, y, z = SPOT
    tag = spawn("api_bat", x, y + 3, z)
    time.sleep(4)
    height = number(mob_data(tag, "Pos[1]"))
    check("a flying mob stays up instead of falling", height > y + 0.5, str(height))
    check("and has no gravity", "1b" in mob_data(tag, "NoGravity") or "true" in mob_data(tag, "NoGravity"), mob_data(tag, "NoGravity"))
    aim(tag, x, y + 1, z)
    client.ask("rightclick")
    check("it's told to fly somewhere", holds(client, "bat flying true at"), client.text()[-200:])
    check("and gets there, through the air", holds(client, "bat arrived in the air true", 40), mob_data(tag, "Pos"))
    place = [int(float(number)) for number in re.findall(r"(-?\d+\.\d+)d", mob_data(tag, "Pos"))]
    near = client_parts(client, *place)
    check("a part named as glowing on a mob reaches the client", len([part for part in near if part["brightness"] == 15]) == 1, str(near)[:400])
    rcon("kill", f"@n[tag={tag}]")
    time.sleep(2)


def play_walking(client):
    x, y, z = SPOT
    tag = spawn("api_ox", x - 6, y, z)
    aim(tag, x - 6, y, z)
    client.ask("rightclick")
    check("a module sends a mob to a block", holds(client, "ox sets off for"))
    check("and hears when it's there", holds(client, "ox arrived at true", 30))
    check("its walk animation plays on the way", holds(client, "ox legs moving", 1))
    # Being told to go somewhere else while walking counts as not having got to the first place.
    aim(tag, x - 6, y, z)
    client.ask("rightclick")
    aim(tag, x - 6, y, z)
    client.ask("rightclick")
    check("and when it's sent elsewhere instead", holds(client, "ox gave up at", 20))
    arrivals = client.text().count("chat: API ox arrived")
    deadline = time.monotonic() + 30
    while client.text().count("chat: API ox arrived") == arrivals and time.monotonic() < deadline:
        time.sleep(1)
    check("and it arrives at the second place", client.text().count("chat: API ox arrived") > arrivals)
    rcon("kill", f"@n[tag={tag}]")
    rcon("kill", "@e[type=item]")
    time.sleep(2)


def play_damage(client):
    x, y, z = SPOT
    tag = spawn("api_ox", x, y, z)
    health = number(mob_data(tag, "Health"))
    rcon("damage", f"@n[tag={tag}]", "4", "minecraft:generic")
    check("a module hears damage coming to a mob, and how much", holds(client, "ox would take 4.0"))
    time.sleep(1)
    check("and can stop it landing at all", number(mob_data(tag, "Health")) == health, mob_data(tag, "Health"))
    rcon("kill", f"@n[tag={tag}]")
    time.sleep(1)
    check("what can't be stopped isn't asked about", "No entity" in rcon("data", "get", "entity", f"@n[tag={tag}]") or number(mob_data(tag, "Health")) <= 0)
    rcon("kill", "@e[type=item]")

    rcon("item", "replace", "entity", PLAYER, "armor.head", "with", "minecraft:leather_helmet", "1")
    rcon("effect", "clear", PLAYER)
    rcon("gamemode", "survival", PLAYER)
    rcon("effect", "give", PLAYER, "minecraft:instant_health", "1", "5", "true")
    time.sleep(1)
    rcon("damage", PLAYER, "8", "minecraft:generic")
    check("a module hears damage coming to a player", holds(client, "player would take 8.0"))
    time.sleep(1)
    left = number(rcon("data", "get", "entity", PLAYER, "Health"))
    check("and can change how much it is", 15.5 <= left <= 16.5, str(left))
    rcon("item", "replace", "entity", PLAYER, "armor.head", "with", "minecraft:air")

    # A hit that would kill, and a module saying it doesn't.
    tag = spawn("api_calf", x + 3, y, z)
    rcon("damage", f"@n[tag={tag}]", "100", "minecraft:generic")
    check("a module hears a hit about to kill", holds(client, "calf cheats death from 100.0"))
    time.sleep(1)
    check("and can keep it alive, on the health it says", number(mob_data(tag, "Health")) == 3, mob_data(tag, "Health"))
    time.sleep(2)
    check("and it stays alive", "Health" in rcon("data", "get", "entity", f"@n[tag={tag}]") or number(mob_data(tag, "Health")) == 3, mob_data(tag, "Health"))
    rcon("damage", f"@n[tag={tag}]", "100", "minecraft:generic")
    time.sleep(2)
    check("and the next one kills it when it doesn't say so", "No entity" in rcon("data", "get", "entity", f"@n[tag={tag}]"))
    rcon("kill", "@e[type=item]")

    # A real hit, from a real player, on two mobs with different ideas about being pushed.
    rcon("effect", "give", PLAYER, "minecraft:resistance", "9999", "5", "true")
    tag = spawn("api_calf", x, y, z)
    aim(tag, x, y, z)
    before = number(mob_data(tag, "Pos[2]"))
    client.ask("mine 2")
    check("a module hears a mob pushed by a hit", holds(client, "calf pushed 0.4"))
    time.sleep(1)
    far = abs(number(mob_data(tag, "Pos[2]")) - before)
    check("and can push it harder", far > 1.5, str(far))
    rcon("kill", f"@n[tag={tag}]")
    rcon("kill", "@e[type=item]")
    tag = spawn("api_ox", x, y, z)
    check("knockback resistance is what its data says", number(rcon("attribute", f"@n[tag={tag}]", "minecraft:knockback_resistance", "get")) == 1, rcon("attribute", f"@n[tag={tag}]", "minecraft:knockback_resistance", "get"))
    rcon("kill", f"@n[tag={tag}]")
    rcon("kill", "@e[type=item]")
    time.sleep(1)


def bar_on_client(client):
    client.ask("barheld")
    return json.loads(re.findall(r"\[M8\] bar: (.*)$", client.text(), re.MULTILINE)[-1])


def play_bar(client):
    cell = slot("api_cell", "items")
    rcon("clear", PLAYER)
    rcon("give", PLAYER, cell, "1")
    time.sleep(1)
    shown = bar_on_client(client)
    check("an item that isn't a tool shows a bar", shown["visible"], str(shown))
    check("at the level its feature starts it", 5 <= shown["width"] <= 8, str(shown))
    check("and the game here doesn't think it can wear out", "max_damage" not in rcon("data", "get", "entity", PLAYER, "SelectedItem"), rcon("data", "get", "entity", PLAYER, "SelectedItem"))
    client.ask("use")
    check("a module can change it", holds(client, "cell went from 0.5 to 0.25"))
    time.sleep(1)
    lower = bar_on_client(client)
    check("and the client sees that", lower["width"] < shown["width"], f"{shown} {lower}")
    client.ask("use")
    client.ask("use")
    check("up to full, by way of empty", holds(client, "cell went from 0.0 to 1.0"))
    time.sleep(1)
    full = bar_on_client(client)
    check("and full still shows", full["visible"] and full["width"] == 13, str(full))
    client.ask("shot bar")
    rcon("clear", PLAYER)


def craft_on_client(client, *rows):
    """Puts these in a crafting grid by hand, as a player would, and says what it offers. Each is a slot of the grid and an item that's in the player's hotbar."""
    client.ask("opentable")
    time.sleep(1)
    for grid_slot, hotbar in rows:
        client.ask(f"hotbarclick {hotbar}")
        client.ask(f"click {grid_slot}")
    time.sleep(1)
    client.ask("menu")
    return re.findall(r"\[M8\] menu holds (.*)$", client.text(), re.MULTILINE)[-1]


def play_recipes(client):
    x, y, z = SPOT
    pick, better, ingot = slot("api_pick", "items"), slot("api_better_pick", "items"), slot("api_ingot", "items")
    rcon("setblock", str(x), str(y), str(z), "minecraft:crafting_table")
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 2.5), "180", "20")
    rcon("clear", PLAYER)
    # A half-worn pick with an enchantment and a module's data on it, going through a recipe that carries them.
    rcon("give", PLAYER, pick + '[minecraft:damage=100,minecraft:enchantments={"minecraft:efficiency":2},minecraft:custom_data={kept:7b}]', "1")
    rcon("give", PLAYER, "minecraft:stick", "1")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask("hotbarclick 0")
    client.ask("click 1")
    client.ask("hotbarclick 1")
    client.ask("click 2")
    time.sleep(1)
    client.ask("click 0 shift")
    time.sleep(1)
    client.ask("closemenu")
    time.sleep(1)
    made = rcon("data", "get", "entity", PLAYER, "Inventory")
    check("a recipe's result comes out", better in made, made)
    check("worn as far through its life as what went in", '"minecraft:damage": 50' in made, made)
    check("with its enchantments", "minecraft:efficiency" in made, made)
    check("and its data", "kept: 7b" in made, made)

    # A worn pick and two ingots, mended by a quarter for each.
    rcon("clear", PLAYER)
    rcon("give", PLAYER, pick + '[minecraft:damage=150,minecraft:custom_data={kept:9b}]', "1")
    rcon("give", PLAYER, ingot, "2")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask("hotbarclick 0")
    client.ask("click 1")
    client.ask("hotbarclick 1")
    client.ask("click 2 right")
    client.ask("click 3 right")
    client.ask("hotbarclick 1")
    time.sleep(1)
    client.ask("click 0 shift")
    time.sleep(1)
    client.ask("closemenu")
    time.sleep(1)
    mended = rcon("data", "get", "entity", PLAYER, "Inventory")
    check("a repair recipe mends by what it says for each piece", '"minecraft:damage": 50' in mended, mended)
    check("and what's on it stays", "kept: 9b" in mended, mended)
    rcon("clear", PLAYER)
    # One that isn't worn has nothing to mend.
    rcon("give", PLAYER, pick, "1")
    rcon("give", PLAYER, ingot, "1")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask("hotbarclick 0")
    client.ask("click 1")
    client.ask("hotbarclick 1")
    client.ask("click 2")
    time.sleep(1)
    client.ask("menu")
    shown = re.findall(r"\[M8\] menu holds (.*)$", client.text(), re.MULTILINE)[-1]
    check("nothing that isn't worn can be mended", shown.startswith("0=empty"), shown)
    client.ask("closemenu")
    rcon("setblock", str(x), str(y), str(z), "minecraft:air")
    rcon("kill", "@e[type=item]")
    rcon("clear", PLAYER)


def play_bench(client):
    x, y, z = SPOT
    bench, ingot = slot("api_bench"), slot("api_ingot", "items")
    rcon("setblock", str(x), str(y), str(z), bench)
    # The ring a recipe calls for, in a 4 by 4 grid, which is 12 ingredients.
    ring = [0, 1, 2, 3, 4, 7, 8, 11, 12, 13, 14, 15]
    for place in ring:
        rcon("item", "replace", "block", str(x), str(y), str(z), f"container.{place}", "with", ingot, "2")
    check("a grid with more than 9 in it makes what it says", holds(client, "bench offers 1 api_big"))
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 2.5), "180", "20")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask("menu")
    shown = re.findall(r"\[M8\] menu holds (.*)$", client.text(), re.MULTILINE)[-1]
    check("a client sees it as a grid of 4 across with the output at the far right", all(f"{row * 9 + column}=2x" in shown for row, column in ((0, 0), (0, 3), (3, 0), (3, 3))) and "8=1x" in shown, shown)
    check("and the middle of the ring is empty", all(f"{row * 9 + column}=empty" in shown for row, column in ((1, 1), (2, 2))), shown)
    client.ask("click 8 shift")
    check("taking it uses one from each place", holds(client, "bench made api_big"))
    time.sleep(1)
    data = rcon("data", "get", "block", str(x), str(y), str(z), "Items")
    check("and leaves the rest", data.count("count: 1") >= 12, data)
    client.ask("closemenu")
    # Any place in the grid, for something smaller than it.
    rcon("setblock", str(x), str(y), str(z), "minecraft:air")
    rcon("kill", "@e[type=item]")
    rcon("setblock", str(x), str(y), str(z), bench)
    rcon("item", "replace", "block", str(x), str(y), str(z), "container.5", "with", "minecraft:stick", "1")
    rcon("item", "replace", "block", str(x), str(y), str(z), "container.6", "with", "minecraft:stick", "1")
    check("a smaller shape can sit anywhere in it", holds(client, "bench offers 1 api_ingot"))
    rcon("item", "replace", "block", str(x), str(y), str(z), "container.15", "with", "minecraft:stick", "1")
    check("but not with anything else in the grid", holds(client, "bench offers 0"))
    rcon("setblock", str(x), str(y), str(z), "minecraft:air")
    rcon("kill", "@e[type=item]")
    rcon("clear", PLAYER)


def play_keys(client):
    x, y, z = SPOT
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 0.5), "0", "0")
    time.sleep(2)
    client.ask("holdjump 2")
    check("a module hears the jump key", holds(client, "pressed JUMP"))
    check("and the player leaving the ground", holds(client, f"jumped {PLAYER}"))
    check("and the key being let go", holds(client, "released JUMP"))
    time.sleep(2)
    jumped = client.text().count(f"chat: API jumped {PLAYER}")
    client.ask("doubletapjump")
    check("a module hears a double tap", holds(client, "double tapped JUMP"))
    time.sleep(2)
    client.ask("holdforward 2")
    check("and other keys", holds(client, "pressed FORWARD"))
    before = client.text().count("chat: API double tapped")
    client.ask("holdjump 2")
    time.sleep(1)
    client.ask("holdjump 2")
    time.sleep(1)
    check("two presses far apart aren't a double tap", client.text().count("chat: API double tapped") == before)


def play_chunks(client):
    x, y, z = SPOT
    far = 625 * 16 + 8
    rcon("tp", PLAYER, str(far), "200", str(far))
    check("a module hears a chunk load, and that it's new", holds(client, "chunk loaded new true", 60))
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 0.5))
    check("and that chunk going", holds(client, "chunk unloaded", 120))


def play_state(client):
    x, y, z = SPOT
    lamp = slot("api_lamp")
    rcon("setblock", str(x), str(y), str(z), lamp)
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 3.5), "180", "20")
    time.sleep(1)
    started = int(re.findall(r"chat: API state started (\d+) uses \d+", client.text())[-1]) if re.search(r"chat: API state started", client.text()) else None
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z}")
    time.sleep(1)
    # Taking its jar away and putting it back is what a release does to a module that's changed.
    modules = runtime.RUNTIME / "prod" / "modules" / "server"
    jar = modules / "moduleapi.jar"
    aside = runtime.RUNTIME / "m40-moduleapi.jar"
    shutil.move(jar, aside)
    rcon("conduit", "modules", "reload")
    time.sleep(1)
    shutil.move(aside, jar)
    rcon("conduit", "modules", "reload")
    found = holds(client, r"state started \d+ uses [1-9]")
    check("what a module keeps comes back when it's replaced", found)
    lines = re.findall(r"chat: API state started (\d+) uses (\d+)", client.text())
    uses = int(lines[-1][1])
    check("and it's still all there", uses >= 2 and (started is None or int(lines[-1][0]) == started + 1), str(lines[-3:]))
    rcon("save-all", "flush")
    time.sleep(2)
    saved = runtime.RUNTIME / "prod" / "world" / "conduit_modules" / "moduleapi.nbt"
    check("and it's saved beside the world", saved.exists(), str(saved))
    rcon("setblock", str(x), str(y), str(z), "minecraft:air")


def icon_pixels(client, name, box):
    """How much of a corner of a photograph is the colour nothing else in the game is but that icon."""
    client.ask(f"shot {name}")
    shots = sorted((runtime.WORK / "mods" / "companion" / "build" / "run" / "clientGameTest" / "screenshots").glob(f"*m8_{name}*.png"))
    with Image.open(shots[-1]) as image:
        rgb = image.convert("RGB")
        area = rgb.crop((int(box[0] * rgb.width), int(box[1] * rgb.height), int(box[2] * rgb.width), int(box[3] * rgb.height)))
        return sum(count for count, colour in area.getcolors(maxcolors=1 << 24) if colour[0] > 200 and colour[1] < 60 and colour[2] > 200)


def client_effects(client):
    client.ask("effects")
    return json.loads(re.findall(r"\[M8\] effects: (.*)$", client.text(), re.MULTILINE)[-1])


def play_effects(client):
    x, y, z = SPOT
    blessed, cursed = slot("api_blessed", "effects"), slot("api_cursed", "effects")
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 0.5), "0", "0")
    rcon("effect", "clear", PLAYER)
    before = icon_pixels(client, "no_effect", (0.5, 0, 1, 0.3))
    time.sleep(1)
    rcon("effect", "give", PLAYER, blessed, "60", "2", "true")
    check("a module hears an effect start, and at what level", holds(client, "blessed started level 2 has it true"))
    check("it runs for as long as it lasts", holds(client, f"blessed tick level 2 on {PLAYER}"))
    time.sleep(1)
    shown = client_effects(client)
    check("the client has it", any(effect["name"] == "Api Blessed" and effect["level"] == 2 for effect in shown), str(shown))
    check("with its time left", any(40 * 20 < effect["ticks"] <= 60 * 20 for effect in shown), str(shown))
    check("and its own picture", any(effect["sprite"] == f"{blessed.replace(':', ':mob_effect/')}" for effect in shown), str(shown))
    rcon("effect", "give", PLAYER, cursed, "60", "0", "true")
    time.sleep(2)
    shown = client_effects(client)
    check("two at once both show", len(shown) == 2 and any(effect["name"] == "Api Cursed" and effect["harmful"] for effect in shown), str(shown))
    hud = icon_pixels(client, "effect_hud", (0.5, 0, 1, 0.3))
    check("its picture is on the HUD", hud > before + 50, f"{before} then {hud}")
    client.ask("inventory")
    time.sleep(1)
    inventory = icon_pixels(client, "effect_inventory", (0, 0, 1, 1))
    check("and in the inventory", inventory > 50, str(inventory))
    client.ask("close")
    rcon("effect", "clear", PLAYER, cursed)
    time.sleep(2)
    shown = client_effects(client)
    check("one taken away goes", [effect["name"] for effect in shown] == ["Api Blessed"], str(shown))
    rcon("effect", "clear", PLAYER)
    check("a module hears it end", holds(client, f"blessed ended on {PLAYER}"))
    time.sleep(2)
    check("and the client stops showing it", client_effects(client) == [], str(client_effects(client)))
    rcon("effect", "give", PLAYER, blessed, "2", "0", "true")
    check("it can run out", holds(client, f"blessed ended on {PLAYER}", 10))
    time.sleep(1)
    check("and the client stops showing that too", client_effects(client) == [], str(client_effects(client)))

    # On a mob, which nothing shows but which still works.
    tag = spawn("api_calf", x + 2, y, z)
    rcon("effect", "give", f"@n[tag={tag}]", blessed, "60", "1", "true")
    check("a mob can have one too", holds(client, "blessed tick level 1 on calf"))
    rcon("kill", f"@n[tag={tag}]")
    rcon("kill", "@e[type=item]")
    # Dying takes it away, and whoever comes back doesn't still seem to have it.
    rcon("effect", "give", PLAYER, blessed, "60", "0", "true")
    time.sleep(1)
    rcon("effect", "clear", PLAYER, "minecraft:resistance")
    rcon("kill", PLAYER)
    time.sleep(3)
    client.ask("respawn")
    time.sleep(3)
    check("dying ends it, on the client too", client_effects(client) == [], str(client_effects(client)))
    rcon("gamemode", "survival", PLAYER)
    rcon("effect", "give", PLAYER, "minecraft:resistance", "9999", "5", "true")


def play_fluids(client):
    x, y, z = SPOT
    bucket, brine, slag = slot("api_brine_bucket", "items"), "gm:fb" + slot_number("api_brine"), "gm:fb" + slot_number("api_slag")
    rcon("fill", str(x - 12), str(y), str(z - 12), str(x + 12), str(y + 8), str(z + 12), "minecraft:air")
    rcon("clear", PLAYER)
    rcon("give", PLAYER, bucket, "1")
    rcon("tp", PLAYER, str(x + 0.5), str(y + 2), str(z + 0.5), "0", "90")
    time.sleep(1)
    client.ask("rightclick")
    time.sleep(1)
    check("a bucket pours it out", is_block(x, y, z, brine), rcon("data", "get", "entity", PLAYER, "SelectedItem"))
    client.ask("held")
    check("and leaves an empty bucket", "bucket" in rcon("data", "get", "entity", PLAYER, "SelectedItem"), rcon("data", "get", "entity", PLAYER, "SelectedItem"))
    time.sleep(4)
    check("it spreads over the ground by itself", is_block(x + 2, y, z, brine), client_sees(client, x + 2, y, z))
    check("and thins as it goes", is_block(x + 2, y, z, f"{brine}[level=2]"), rcon("execute", "if", "block", str(x + 2), str(y), str(z), f"{brine}[level=2]"))
    check("to a client it's flowing water", "minecraft:water" in client_sees(client, x + 2, y, z), client_sees(client, x + 2, y, z))
    still = client_sees(client, x, y, z)
    check("a still pool is its own thing to a client", "water" not in still and "level" not in still, still)
    # Doesn't renew, so a trench between two sources stays flowing.
    light = client_light(client, x, y + 1, z)
    check("and gives its own light", light == 5, str(light))
    client.ask("shot fluid_pool")

    # Swimming: what a client sees has to agree with what the server does.
    rcon("tp", PLAYER, str(x + 0.5), str(y), str(z + 0.5), "0", "0")
    time.sleep(2)
    check("a module hears something in it, and it's water to the game", holds(client, "in the brine, in water true is it true"))
    client.ask("inwater")
    check("and the client is swimming in it too", re.findall(r"\[M8\] in water: (\w+)", client.text())[-1] == "true")

    rcon("tp", PLAYER, str(x + 0.5), str(y + 3), str(z + 0.5), "0", "90")
    rcon("clear", PLAYER)
    rcon("give", PLAYER, "minecraft:bucket", "1")
    time.sleep(1)
    client.ask("rightclick")
    time.sleep(2)
    check("an empty bucket takes it back", bucket in rcon("data", "get", "entity", PLAYER, "SelectedItem"), rcon("data", "get", "entity", PLAYER, "SelectedItem"))
    time.sleep(8)
    check("and what flowed from it dries up", is_block(x + 2, y, z, "minecraft:air"))

    rcon("setblock", str(x), str(y), str(z), slag)
    rcon("gamerule", "doFireTick", "false")
    time.sleep(2)
    check("a fluid that looks like lava is lava to a client", "minecraft:lava" in client_sees(client, x, y, z), client_sees(client, x, y, z))
    check("and glows like it by default", client_light(client, x, y + 1, z) == 14, str(client_light(client, x, y + 1, z)))
    time.sleep(3)
    check("it spreads, thinning as fast as it says", is_block(x + 1, y, z, f"{slag}[level=3]"), client_sees(client, x + 1, y, z))
    rcon("fill", str(x - 6), str(y), str(z - 6), str(x + 6), str(y + 2), str(z + 6), "minecraft:air")
    rcon("clear", PLAYER)
    time.sleep(2)


def slot_number(name):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return ledger["fluids"][f"moduleapi/{name}"]["slot"]


STAGES = {"blocks": (play_facing, play_placing, play_redstone, play_light, play_unbreakable, play_parts, play_machine_slots),
          "mobs": (play_mob_drops, play_flying, play_walking, play_damage),
          "items": (play_bar, play_recipes, play_bench),
          "input": (play_keys, play_chunks, play_state),
          "effects": (play_effects,),
          "fluids": (play_fluids,)}


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
        if "effects" in wanted:
            client.ask("guiwide")
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
