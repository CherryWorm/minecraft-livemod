#!/usr/bin/env python3
"""The larger things the engine can do, proved on a real client and by reading the world's raw files. A machine has an inventory that
hoppers and players use, and recipes with several outputs and exact counts. Modules open menus and books. Crops grow in one slot, and
cables reach for their neighbours. Items have timed uses, tooltips and changing pictures. A mob can be tinted or a baby, and a gauge can
show a value. Ores can keep to where they can be seen. Start with a blank world from reset-dev-world.sh, and reset it afterwards.

Usage: python3 -m broker.tests.m17_test
"""
import json
import pathlib
import re
import shutil
import sys
import time
from statistics import mean

from PIL import Image, ImageChops

from broker import runtime
from broker.tests.m8_test import Client, make_model, report
from broker.tests.m16_test import World, generate_land

SOURCE = runtime.BROKER / "testsrc-m17"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "bigger"
PLAYER = "Player0"
SPOT = (40, 120, 40)
# Plain colours, so that what's on screen can be told apart by colour alone.
TEXTURES = {"big_block": (0x88, 0x88, 0x88), "big_item": (0x66, 0x66, 0x66), "big_flat": (0xCC, 0x88, 0x44), "big_plain": (0x11, 0xAA, 0xCC), "big_gilded": (0xAA, 0x11, 0xCC),
            "big_stage_0": (0x10, 0x40, 0x10), "big_stage_1": (0x20, 0x70, 0x20), "big_stage_2": (0x30, 0xA0, 0x30), "big_stage_3": (0x40, 0xF0, 0x40),
            "big_needle_0": (0xF0, 0x10, 0x10), "big_needle_1": (0xF0, 0x20, 0x10), "big_needle_2": (0xF0, 0x30, 0x10), "big_needle_3": (0xF0, 0x40, 0x10)}


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "bigger"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for name, colour in TEXTURES.items():
        Image.new("RGBA", (16, 16), (*colour, 255)).save(textures / f"{name}.png")
    models = target / "assets" / "models"
    models.mkdir(parents=True, exist_ok=True)
    make_model(models / "big_mob.bbmodel", "quadruped")
    make_model(models / "big_gauge.bbmodel", "quadruped")


def release():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m17-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)


def slot(name, table="items"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"bigger/{name}"]["slot"]


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def holds_in(x, y, z, item):
    return re.search(r"Count: (\d+)", rcon("execute", "if", "items", "block", x, y, z, "container.*", item))


def is_block(x, y, z, block):
    return "passed" in rcon("execute", "if", "block", x, y, z, block)


def chat_count(client, text):
    return client.text().count(f"[M8] chat: BIG {text}")


def empty_hands():
    rcon("kill", "@e[type=minecraft:item]")
    rcon("clear", PLAYER)


def last(client, pattern):
    return re.findall(pattern, client.text())[-1]


def check_ores(results):
    """Only where it can be seen, from the world's raw files. Every block of it has air next to it."""
    world = World()
    blocks = world.find(slot("big_glow", "blocks"))
    exposed = [spot for spot in blocks if any(world.block_at(spot[0] + dx, spot[1] + dy, spot[2] + dz) in ("minecraft:air", "minecraft:cave_air")
                                              for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)))]
    results.append(report("an ore can keep to where it can be seen", blocks and len(exposed) >= len(blocks) * 0.98, f"{len(exposed)} of {len(blocks)} touch air"))


def play_machines(client, results):
    x, y, z = SPOT
    kiln = slot("big_kiln", "blocks")
    made_in, a, b = slot("big_in"), slot("big_out_a"), slot("big_out_b")
    for command in (("gamemode", "survival", PLAYER), ("difficulty", "peaceful"), ("time", "set", "noon"),
                    ("fill", x - 8, y - 3, z - 8, x + 8, y + 8, z + 8, "minecraft:air"),
                    ("fill", x - 8, y - 4, z - 8, x + 8, y - 4, z + 8, "minecraft:smooth_stone"),
                    ("fill", x - 8, y - 1, z - 8, x + 8, y - 1, z + 8, "minecraft:smooth_stone")):
        rcon(*command)
    rcon("tp", PLAYER, x, y, z, 0, 60)

    # Hoppers doing all of it, with nobody there. One above for the inputs, and one below takes what's made.
    mx, my, mz = x + 4, y + 1, z
    rcon("setblock", mx, my - 1, mz, "minecraft:hopper[facing=down]")
    rcon("setblock", mx, my, mz, kiln)
    rcon("setblock", mx, my + 1, mz, "minecraft:hopper[facing=down]")
    rcon("item", "replace", "block", mx, my + 1, mz, "container.0", "with", made_in, 4)
    rcon("item", "replace", "block", mx, my + 1, mz, "container.1", "with", "minecraft:iron_ingot", 1)
    found = client.wait(r"\[M8\] chat: BIG made (\S+) taking (\d+)", 30)
    results.append(report("a machine's recipe says which it was and how much it takes", found.groups() == ("bigger/big_melt", "3"), str(found.groups())))
    time.sleep(3)
    results.append(report("hoppers fill a machine, and take what it makes, every output of it",
                          (holds_in(mx, my - 1, mz, a) or [0, 0])[1] == "2" and (holds_in(mx, my - 1, mz, b) or [0, 0])[1] == "1",
                          f"{rcon('data', 'get', 'block', mx, my - 1, mz, 'Items')[:160]}"))

    # A player uses it too, on a chest's screen.
    rcon("setblock", mx, my - 1, mz, "minecraft:air")
    rcon("setblock", mx, my + 1, mz, "minecraft:air")
    empty_hands()
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", made_in, 2)
    rcon("item", "replace", "entity", PLAYER, "hotbar.1", "with", "minecraft:dirt", 1)
    rcon("tp", PLAYER, mx, my - 1, mz - 2, 0, 0)
    time.sleep(1)
    client.ask(f"useblock {mx} {my} {mz}")
    client.ask("screen")
    results.append(report("a machine opens its inventory on a chest's screen", last(client, r"\[M8\] the screen is (\w+)") == "ContainerScreen"))
    client.ask("menu")
    shown = last(client, r"\[M8\] menu holds (.+)")
    results.append(report("what's left over from the recipe is in it, with panes between inputs and outputs", "0=1x" in shown and "glass_pane" in shown, shown[:200]))
    # Slot 9 onward is the player's: main rows, then hotbar. A chest's top has 9 here, then 27, then 9.
    hotbar_first = 9 + 27
    client.ask(f"click {hotbar_first} shift")
    time.sleep(1)
    client.ask("menu")
    # There was one left over from the recipe, and two more were in the hotbar.
    results.append(report("shift-clicking puts something in", "0=3x" in last(client, r"\[M8\] menu holds (.+)"), last(client, r"\[M8\] menu holds (.+)")[:200]))
    client.ask(f"click {hotbar_first + 1} shift")
    time.sleep(1)
    results.append(report("a module can refuse what goes in", "passed" in rcon("execute", "if", "items", "entity", PLAYER, "hotbar.1", "minecraft:dirt")))
    client.ask("closemenu")
    # It goes with the machine, as a chest's does. What's inside is the player's: nothing's lost.
    rcon("setblock", mx, my, mz, "minecraft:air", "destroy")
    time.sleep(1)
    results.append(report("what's in a machine drops when it's broken", "1" != rcon("execute", "if", "entity", f"@e[type=minecraft:item,x={mx},y={my},z={mz},distance=..3]") and "passed" in rcon("execute", "if", "entity", f"@e[type=minecraft:item,x={mx},y={my},z={mz},distance=..3]")))


def play_menus(client, results):
    x, y, z = SPOT
    button = slot("big_button", "blocks")
    empty_hands()
    rcon("setblock", x, y, z + 2, button)
    rcon("tp", PLAYER, x, y, z, 0, 60)
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z + 2}")
    client.ask("screen")
    results.append(report("a module opens a menu, with nothing on the client but the game", last(client, r"\[M8\] the screen is (\w+)") == "ContainerScreen"))
    client.ask("click 3")
    found = client.wait(r"\[M8\] chat: BIG button (\d+) right (\w+) shift (\w+)", 20)
    results.append(report("a click on it reaches the module", found.groups() == ("3", "false", "false"), found.group(0)))
    client.ask("click 5 right")
    client.wait(r"\[M8\] chat: BIG button 5 right true", 20)
    results.append(report("and it can tell a right click", True))
    time.sleep(1)
    client.ask("menu")
    shown = last(client, r"\[M8\] menu holds (.+)")
    results.append(report("what it shows can't be taken, and it redraws", "3=3xminecraft:diamond" in shown or "3=3xdiamond" in shown, shown[:120]))
    results.append(report("and nothing ends up on the cursor", "carried=0" in shown))
    results.append(report("nothing got into the player's hands", "Found" not in rcon("clear", PLAYER, "minecraft:diamond", "0")))
    client.ask("closemenu")
    found = client.wait(r"\[M8\] chat: BIG menu closed after (\d+)", 20)
    results.append(report("the module hears it close", found.group(1) == "2", found.group(0)))
    rcon("setblock", x, y, z + 2, "minecraft:air")

    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", slot("big_book"))
    time.sleep(1)
    client.ask("use")
    found = client.wait(r"\[M8\] chat: BIG book opened, natural (\w+) (\w+)", 20)
    results.append(report("a module can tell what the world made from what's been changed", found.groups() == ("true", "false"), found.group(0)))
    client.ask("screen")
    results.append(report("a module opens a book", last(client, r"\[M8\] the screen is (\w+)") == "BookViewScreen"))
    client.ask("close")

    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", slot("big_lens"))
    rcon("tp", PLAYER, x, y, z, 0, 60)
    time.sleep(1)
    client.ask(f"useblock {x} {y - 1} {z + 2}")
    client.wait(r"\[M8\] chat: .*learned .*Big Lore", 20)
    results.append(report("a module can examine something for a player, and they learn what that teaches", True))


def play_crops(client, results):
    x, y, z = SPOT
    crop, seed = slot("big_crop", "blocks"), slot("big_seed")
    empty_hands()
    # This crop grows on any random tick, which could otherwise make it one stage further on than these steps expect.
    rcon("gamerule", "random_tick_speed", 0)
    for dx, block in ((0, "minecraft:farmland"), (2, "minecraft:farmland")):
        rcon("setblock", x + dx, y - 1, z + 2, block)
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", seed, 2)
    rcon("tp", PLAYER, x, y, z, 0, 60)
    time.sleep(1)
    client.ask(f"useblock {x} {y - 1} {z + 2}")
    time.sleep(1)
    results.append(report("a seed plants a crop at its first stage", is_block(x, y, z + 2, f"{crop}[age=0]"), rcon("data", "get", "block", x, y, z + 2)[:100]))
    client.ask(f"blockat {x} {y} {z + 2}")
    results.append(report("a client sees a stage of its own that has no collision", "tripwire" in last(client, r"\[M8\] the client sees (.+)"), last(client, r"\[M8\] the client sees (.+)")))

    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", "minecraft:bone_meal", 4)
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z + 2}")
    time.sleep(1)
    results.append(report("bone meal grows it a stage", is_block(x, y, z + 2, f"{crop}[age=1]")))

    spot = (x, y, z + 2)
    empty_hands()
    rcon("loot", "give", PLAYER, "mine", *spot, "minecraft:air")
    young = rcon("clear", PLAYER, seed, "0"), rcon("clear", PLAYER, slot("big_fruit"), "0")
    results.append(report("before it's ripe it gives what it says for that", "Found 1" in young[0] and "Found" not in young[1], str(young)))

    # Quickly, then, with the game's clock for it turned up. Farmland with nothing on it dries out and goes to dirt, and this one shouldn't.
    rcon("gamerule", "random_tick_speed", 4000)
    time.sleep(6)
    rcon("gamerule", "random_tick_speed", 3)
    results.append(report("left alone it grows up", is_block(x, y, z + 2, f"{crop}[age=3]"), rcon("data", "get", "block", x, y, z + 2)[:80]))
    results.append(report("and it keeps the farmland under it from drying out", is_block(x, y - 1, z + 2, "minecraft:farmland") and is_block(x + 2, y - 1, z + 2, "minecraft:dirt")))
    empty_hands()
    rcon("loot", "give", PLAYER, "mine", *spot, "minecraft:air")
    ripe = rcon("clear", PLAYER, slot("big_fruit"), "0"), rcon("clear", PLAYER, seed, "0")
    results.append(report("ripe, it gives everything it says", "Found 2" in ripe[0] and "Found 1" in ripe[1], str(ripe)))
    rcon("setblock", x, y - 1, z + 2, "minecraft:dirt")
    time.sleep(1)
    results.append(report("with nothing to stand on it goes", is_block(x, y, z + 2, "minecraft:air")))
    rcon("fill", x - 2, y - 1, z, x + 4, y - 1, z + 4, "minecraft:smooth_stone")
    rcon("fill", x - 2, y, z, x + 4, y, z + 4, "minecraft:air")


def play_cables(client, results):
    x, y, z = SPOT
    cable, kiln = slot("big_cable", "blocks"), slot("big_kiln", "blocks")
    empty_hands()
    rcon("setblock", x, y, z + 2, cable)
    rcon("setblock", x + 1, y, z + 2, cable)
    rcon("setblock", x - 1, y, z + 2, kiln)
    rcon("setblock", x, y + 1, z + 2, "minecraft:hopper")
    time.sleep(1)
    results.append(report("a connected block reaches for its own kind, machines and what it's told to",
                          is_block(x, y, z + 2, f"{cable}[east=true,west=true,up=true,north=false,south=false,down=false]") and is_block(x + 1, y, z + 2, f"{cable}[west=true]")))
    client.ask(f"blockat {x} {y} {z + 2}")
    results.append(report("a client sees a shape of its own, half a block high", "sculk_sensor" in last(client, r"\[M8\] the client sees (.+)"), last(client, r"\[M8\] the client sees (.+)")))
    rcon("setblock", x + 1, y, z + 2, "minecraft:air")
    time.sleep(1)
    results.append(report("and lets go when it's gone", is_block(x, y, z + 2, f"{cable}[east=false,west=true]")))
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", cable, 1)
    rcon("tp", PLAYER, x + 3, y, z + 2, 90, 30)
    time.sleep(1)
    client.ask(f"useblock {x + 1} {y - 1} {z + 2}")
    time.sleep(1)
    results.append(report("one placed by a player connects at once", is_block(x + 1, y, z + 2, f"{cable}[west=true]"), rcon("data", "get", "block", x + 1, y, z + 2)[:80]))
    rcon("fill", x - 2, y, z + 1, x + 2, y + 1, z + 3, "minecraft:air")


def play_blocks(client, results):
    x, y, z = SPOT
    soft, glow = slot("big_soft", "blocks"), slot("big_glow", "blocks")
    empty_hands()
    rcon("setblock", x, y, z + 1, soft)
    rcon("tp", PLAYER, x, y, z, 0, 60)
    time.sleep(1)
    client.ask("mine 2")
    time.sleep(1)
    results.append(report("a stone-family block with hardness 0 breaks at once", is_block(x, y, z + 1, "minecraft:air")))
    results.append(report("and drops nothing", "passed" not in rcon("execute", "if", "entity", "@e[type=minecraft:item]")))
    rcon("setblock", x, y, z + 1, soft)
    rcon("loot", "give", PLAYER, "mine", x, y, z + 1, 'minecraft:diamond_pickaxe[minecraft:enchantments={"minecraft:silk_touch":1}]')
    results.append(report("not even with silk touch", "Found" not in rcon("clear", PLAYER, soft, "0")))
    rcon("setblock", x, y, z + 1, "minecraft:air")

    rcon("setblock", x + 2, y + 1, z + 2, glow)
    time.sleep(2)
    client.ask(f"light {x + 2} {y + 2} {z + 2}")
    light = int(last(client, r"\[M8\] block light: (\d+)"))
    results.append(report("a glowing ore lights its surroundings on the client", light >= 2, f"block light {light}"))
    rcon("setblock", x + 2, y + 1, z + 2, "minecraft:air")

    # In a sealed box at night, so there's no light for anything to be seen by except its own.
    rcon("time", "set", "midnight")
    rcon("fill", x - 2, y - 1, z - 2, x + 2, y + 3, z + 4, "minecraft:black_concrete", "hollow")
    rcon("tp", PLAYER, x, y, z, 0, 0)
    for name in ("big_dull", "big_bright"):
        rcon("setblock", x, y + 1, z + 2, slot(name, "blocks"))
        time.sleep(2)
        client.ask(f"shot {name}")
    rcon("fill", x - 2, y - 1, z - 2, x + 2, y + 3, z + 4, "minecraft:air")
    rcon("fill", x - 2, y - 1, z - 2, x + 2, y - 1, z + 4, "minecraft:smooth_stone")
    rcon("time", "set", "noon")


def check_emissive(results, shots):
    dull, bright = (next(iter(sorted(shots.glob(f"*m8_{name}.png"))), None) for name in ("big_dull", "big_bright"))
    if not dull or not bright:
        results.append(report("the emissive block was photographed", False))
        return
    low, high = sum(mean_colour(dull)), sum(mean_colour(bright))
    results.append(report("an emissive block shows up in the dark, and a plain one doesn't", high > low * 2 and high > 150, f"brightness {low:.0f} and {high:.0f}"))


def play_items(client, results, shots):
    x, y, z = SPOT
    tool, art, needle = slot("big_tool"), slot("big_art"), slot("big_needle")
    empty_hands()
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", tool)
    rcon("tp", PLAYER, x, y, z, 0, -60)
    time.sleep(1)
    client.ask("held")
    results.append(report("an item can have a fixed line in its tooltip", "Points somewhere" in last(client, r"\[M8\] holding (.+)"), last(client, r"\[M8\] holding (.+)")[:160]))
    client.ask("hold 30")
    found = client.wait(r"\[M8\] chat: BIG finished using (\d+)", 20)
    results.append(report("a timed use runs its length and reaches the module", found.group(1) == "1", found.group(0)))
    client.wait(r"\[M8\] chat: BIG heard 1", 20)
    results.append(report("a module hears what another publishes, as this one heard itself", True))
    time.sleep(1)
    results.append(report("the item isn't used up", "Found 1" in rcon("clear", PLAYER, tool, "0")))
    client.ask("held")
    results.append(report("and the client doesn't think it was either", last(client, r"\[M8\] holding (\d+)") == "1", last(client, r"\[M8\] holding (.+)")[:60]))

    # What's drawn, read off the inventory screen. Plain colours keep it simple, as a slot draws an item at full brightness.
    empty_hands()
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", f'{art}[minecraft:custom_model_data={{strings:["gilded"]}}]')
    rcon("item", "replace", "entity", PLAYER, "hotbar.1", "with", art)
    rcon("item", "replace", "entity", PLAYER, "hotbar.2", "with", f'{needle}[minecraft:lodestone_tracker={{target:{{dimension:"minecraft:overworld",pos:[0,64,0]}},tracked:false}}]')
    time.sleep(1)
    client.ask("held")
    results.append(report("a client is told which variant a stack is", "data true" in last(client, r"\[M8\] holding (.+)"), last(client, r"\[M8\] holding (.+)")[:120]))
    client.ask("inventory")
    client.ask("shot items")
    client.ask("close")
    time.sleep(1)
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", f'{needle}[minecraft:lodestone_tracker={{target:{{dimension:"minecraft:overworld",pos:[0,64,0]}},tracked:false}}]')
    time.sleep(1)
    client.ask("held")
    results.append(report("a client is told where a compass points", "tracker true" in last(client, r"\[M8\] holding (.+)"), last(client, r"\[M8\] holding (.+)")[:120]))


def check_items_drawn(results, shots):
    def count(image, colour):
        return sum(1 for pixel in image.getdata() if pixel == colour)

    shot = next(iter(sorted(shots.glob("*m8_items.png"))), None)
    if shot is None:
        results.append(report("the inventory was photographed", False))
        return
    with Image.open(shot) as raw:
        image = raw.convert("RGB")
    gilded, plain = count(image, TEXTURES["big_gilded"]), count(image, TEXTURES["big_plain"])
    results.append(report("a stack with a variant draws that variant, and one without doesn't", gilded > 0 and plain > 0, f"{gilded} pixels of one, {plain} of the other"))
    frames = sum(count(image, TEXTURES[f"big_needle_{index}"]) for index in range(4))
    results.append(report("an item can draw like a compass, by where it points", frames > 0, f"{frames} pixels of its frames"))


def difference(first, second):
    """How many pixels differ by more than a little, which is what something being there or not comes to."""
    with Image.open(first) as a, Image.open(second) as b:
        changed = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
        return sum(1 for value in changed.getdata() if value > 12)


def mean_colour(path):
    with Image.open(path) as image:
        width, height = image.size
        middle = image.convert("RGB").crop((width // 3, height // 3, width * 2 // 3, height * 2 // 3))
        pixels = list(middle.getdata())
    return tuple(mean(pixel[channel] for pixel in pixels) for channel in range(3))


def play_mobs(client, results):
    x, y, z = SPOT
    mob, paint, shrink = slot("big_mob", "mobs"), slot("big_paint"), slot("big_shrink")
    empty_hands()
    rcon("fill", x - 3, y, z - 3, x + 3, y + 6, z + 5, "minecraft:air")
    rcon("tp", PLAYER, x, y, z, 0, 31)
    # Holding what it'll be holding later, so that's no difference between the pictures.
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", shrink)
    time.sleep(1)
    client.ask("shot mob_none")
    empty_hands()
    rcon("summon", mob, x, y, z + 2, "{NoAI:1b,PersistenceRequired:1b}")
    time.sleep(3)
    client.ask("shot mob_plain")
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", paint)
    time.sleep(1)
    client.ask("rightclick")
    found = client.wait(r"\[M8\] chat: BIG painted (\w+)", 20)
    results.append(report("a module can tint one mob", found.group(1) == "ff0000", found.group(0)))
    time.sleep(2)
    client.ask("shot mob_red")
    empty_hands()
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", shrink)
    time.sleep(1)
    client.ask("rightclick")
    found = client.wait(r"\[M8\] chat: BIG shrunk baby (\w+) height ([\d.]+)", 20)
    results.append(report("a module can make one a baby, half the size", found.group(1) == "true" and abs(float(found.group(2)) - 0.4) < 0.01, found.group(0)))
    time.sleep(1)
    client.ask("shot mob_baby")
    time.sleep(7)
    client.ask("shot mob_grown")
    rcon("kill", f"@e[type={mob}]")


def check_mobs_drawn(results, shots):
    def path(name):
        return next(iter(sorted(shots.glob(f"*m8_{name}.png"))), None)

    if not all(path(name) for name in ("mob_none", "mob_plain", "mob_red", "mob_baby", "mob_grown")):
        results.append(report("the mob was photographed", False, str(sorted(item.name for item in shots.glob('*.png')))))
        return
    plain, red = mean_colour(path("mob_plain")), mean_colour(path("mob_red"))
    results.append(report("the tint shows on a client", red[0] - red[2] > plain[0] - plain[2] + 3, f"red minus blue went from {plain[0] - plain[2]:.1f} to {red[0] - red[2]:.1f}"))
    baby, adult = difference(path("mob_none"), path("mob_baby")), difference(path("mob_none"), path("mob_grown"))
    results.append(report("a baby is drawn smaller, and grows up", 0 < baby < adult * 0.75, f"{baby} pixels as a baby, {adult} grown"))


def play_gauge(client, results):
    x, y, z = SPOT
    gauge = slot("big_gauge", "blocks")
    empty_hands()
    rcon("setblock", x, y, z + 3, gauge)
    rcon("tp", PLAYER, x, y + 1, z, 0, 20)
    time.sleep(2)
    for name, value in (("gauge_low", 0.1), ("gauge_high", 0.6)):
        rcon("data", "modify", "block", x, y, z + 3, "machine.value", "set", "value", f"{value}f")
        time.sleep(2)
        client.ask(f"shot {name}")
    rcon("setblock", x, y, z + 3, "minecraft:air")


def check_gauge_drawn(results, shots):
    low, high = (next(iter(sorted(shots.glob(f"*m8_{name}.png"))), None) for name in ("gauge_low", "gauge_high"))
    moved = difference(low, high) if low and high else 0
    results.append(report("a model block can show a value along an animation", moved > 0, f"{moved} pixels moved"))


def main():
    build_source()
    print("building and releasing the test feature", flush=True)
    release()
    generate_land()
    results = []
    check_ores(results)

    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    client = Client(mods, runtime.REPORTS / "m17-client.log")
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        play_machines(client, results)
        play_menus(client, results)
        play_crops(client, results)
        play_cables(client, results)
        play_blocks(client, results)
        play_items(client, results, shots)
        play_mobs(client, results)
        play_gauge(client, results)
    finally:
        client.stop()
    out = runtime.REPORTS / "m17"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_*.png"):
        shutil.copy(path, out)
    check_items_drawn(results, out)
    check_mobs_drawn(results, out)
    check_gauge_drawn(results, out)
    check_emissive(results, out)
    errors = [line for line in pathlib.Path(runtime.REPORTS / "m17-client.log").read_text(encoding="utf-8", errors="replace").splitlines()
              if re.search(r"(Unable to load|Couldn't load|Failed to load|Missing).*\bgm:", line)]
    results.append(report("the client found nothing wrong with any of the art", not errors, str(errors[:3])[:400]))
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
