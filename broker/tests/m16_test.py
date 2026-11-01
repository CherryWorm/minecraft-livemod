#!/usr/bin/env python3
"""What modules can hook into, proved on a real client and by reading the world's raw files. A feature plays its own sound by
name and hears about blocks broken, mobs killed, food eaten, players joining, knowledge learned and things examined. A block's
removal is noticed however it goes, and a machine can still read its data then. A mob can be fed by using an item on it, and has
its own sounds. A block's drops can be vanilla's and several at once. Ruins follow the terrain, pick between layouts, keep their
distance, set block states, give containers their own loot and look for high ground. On the client, dragging across slots with
shift held moves each one, modules can draw on inventory screens and use keys there, and what's typed into a text box never
reaches them. Start with a blank world from reset-dev-world.sh, and reset it afterwards.

Usage: python3 -m broker.tests.m16_test
"""
import base64
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageStat

from broker import runtime, sign
from broker.tests.m8_test import Client, make_model, report

SOURCE = runtime.BROKER / "testsrc-m16"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "hooks"
PLAYER = "Player0"
SPOT = (40, 120, 40)
SOUNDS = ("hook_idle", "hook_hurt", "hook_death")
TEXTURES = ("hook_block", "hook_machine", "hook_food", "hook_token")
LAND = ((-128, -128, 127, 127), (128, -128, 383, 127))
LAND_CHUNKS = 512
# A heightmap packs a height from the bottom of the world into each long, as many as fit whole.
WORLD_BOTTOM = -64
HEIGHT_BITS = 9
HEIGHT_PER_LONG = 64 // HEIGHT_BITS
# The game's own numbers for these keys, which go by where they are on the keyboard.
KEY_K, KEY_E, KEY_ESCAPE, KEY_J = 14, 8, 41, 13
OUT_OF_DATE = "out of date"
MARK_COLOUR = (0x11, 0xEE, 0x77)
# How far the average colour of a picture can be from what's expected, with a few things on it, like the hotbar, that don't change.
EFFECT_TOLERANCE = 30


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
    for name in SOUNDS:
        shutil.copyfile(target / "assets" / "sounds" / "hook_chime.ogg", target / "assets" / "sounds" / f"{name}.ogg")


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


def generate_land():
    """Ruins only turn up in chunks nobody has been in, so this happens before anyone joins. It waits for the patches to catch up.
    Any block changing counts as someone having been there, and with nobody around to stop them these chunks would tick, so grass
    spreading and leaves falling would keep ruins out of most of them, however long the patches took. So the clock stops until it's done."""
    mark = runtime.utc_now()
    runtime.rcon("prod", "tick", "freeze")
    for x1, z1, x2, z2 in LAND:
        runtime.rcon("prod", "forceload", "add", str(x1), str(z1), str(x2), str(z2))
    deadline = time.monotonic() + 600
    chunks = 0
    while time.monotonic() < deadline and chunks < LAND_CHUNKS:
        time.sleep(5)
        found = re.findall(r"retrogen: queued=\d+ chunks=(\d+)", runtime.logs_since("prod", mark))
        chunks = int(found[-1]) if found else 0
    print(f"{chunks} chunks of land patched", flush=True)
    runtime.rcon("prod", "save-all", "flush")
    time.sleep(5)
    runtime.rcon("prod", "tick", "unfreeze")


class World:
    """Reads the world's raw files, so this can't be fooled by the mod's own idea of what it placed."""

    def __init__(self):
        sys.path.insert(0, str(runtime.REPO / "broker" / "gates"))
        from world_diff import block_name, decode, read_chunks

        self.decode, self.block_name = decode, block_name
        self.sections, self.decoded, self.chunks = {}, {}, {}
        for regions in (runtime.RUNTIME / "prod" / "world").rglob("region"):
            for path in regions.glob("*.mca"):
                for x, z, chunk in read_chunks(path):
                    self.chunks[(x, z)] = chunk
                    for section in chunk.get("sections", []):
                        self.sections[(x, z, section["Y"])] = section

    def _read(self, key):
        if key not in self.decoded:
            self.decoded[key] = self.decode(self.sections[key])
        return self.decoded[key]

    def block_at(self, x, y, z):
        key = (x >> 4, z >> 4, y >> 4)
        if key not in self.sections:
            return "minecraft:air"
        blocks, palette = self._read(key)
        return palette[blocks[(y & 15) << 8 | (z & 15) << 4 | x & 15]]

    def properties_at(self, x, y, z):
        """What the block state here says, which the game only writes down when a block has any."""
        key = (x >> 4, z >> 4, y >> 4)
        blocks, _ = self._read(key)
        entry = self.sections[key]["block_states"]["palette"][blocks[(y & 15) << 8 | (z & 15) << 4 | x & 15]]
        return entry.get("properties", {})

    def loot_table_at(self, x, y, z):
        return next((str(entity.get("LootTable")) for entity in self.chunks[(x >> 4, z >> 4)].get("block_entities", [])
                     if (entity.get("x"), entity.get("y"), entity.get("z")) == (x, y, z)), None)

    def ground_at(self, x, z):
        """The same ground the game goes by: the top of the ocean floor heightmap, under any tree. None if the chunk isn't saved."""
        chunk = self.chunks.get((x >> 4, z >> 4))
        if chunk is None or "OCEAN_FLOOR" not in chunk.get("Heightmaps", {}):
            return None
        index = (x & 15) + (z & 15) * 16
        heights = chunk["Heightmaps"]["OCEAN_FLOOR"]
        stored = ((heights[index // HEIGHT_PER_LONG] & ((1 << 64) - 1)) >> (index % HEIGHT_PER_LONG * HEIGHT_BITS)) & ((1 << HEIGHT_BITS) - 1)
        y = stored + WORLD_BOTTOM - 1
        while self.block_at(x, y, z).endswith(("_leaves", "_log", "_wood", "_stem", "_hyphae")):
            y -= 1
        return y

    def find(self, block):
        """Every place this block is, as (x, y, z). It only unpacks sections whose palette mentions it."""
        found = []
        for key, section in self.sections.items():
            names = {self.block_name(entry) for entry in section.get("block_states", {}).get("palette", [])}
            if block in names:
                blocks, palette = self._read(key)
                wanted = palette.index(block)
                found += [(key[0] * 16 + (i & 15), key[2] * 16 + (i >> 8), key[1] * 16 + (i >> 4 & 15))
                          for i, value in enumerate(blocks) if value == wanted]
        return found


def check_ruins(results):
    manifest = json.loads((FIXTURE / "feature.json").read_text(encoding="utf-8"))
    ruins = manifest["ruins"]
    world = World()

    wall = ruins["bending_wall"]
    by_chunk = {}
    for x, y, z in world.find("minecraft:magenta_concrete"):
        by_chunk.setdefault((x >> 4, z >> 4), []).append((x, y, z))
    whole = sum(1 for spots in by_chunk.values() if len(spots) == len(wall["parts"]))
    results.append(report("ruins that follow the terrain were placed, whole", by_chunk and whole == len(by_chunk), f"{whole} of {len(by_chunk)}"))
    flush = [world.block_at(x, y - 1, z) in wall["on"] for spots in by_chunk.values() for x, y, z in spots]
    # Sand and gravel can hang over a cave from worldgen until something disturbs them, so now and then the ground falls away afterwards.
    results.append(report("each part sits right on the ground under it", flush and sum(flush) >= len(flush) * 0.98, f"{sum(flush)} of {len(flush)} parts"))
    rises = [max(y for _, y, _ in spots) - min(y for _, y, _ in spots) for spots in by_chunk.values()]
    results.append(report("they bend with the land", any(rises), f"heights across each: {sorted(rises)[-8:]}"))
    results.append(report("they stay within maxSlope", rises and max(rises) <= wall["maxSlope"], f"largest {max(rises, default=None)}"))

    first, second, sometimes = (world.find(f"minecraft:{name}") for name in ("lime_concrete", "orange_concrete", "target"))
    results.append(report("a ruin picks between its layouts", first and second, f"{len(first)} of one, {len(second)} of the other"))
    results.append(report("a part with a chance is only there some of the time", 0 < len(sometimes) < len(first), f"{len(sometimes)} of {len(first)}"))

    spots = {(x >> 4, z >> 4) for x, _, z in world.find("minecraft:lodestone")}
    gaps = [max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a in spots for b in spots if a != b]
    spacing = ruins["far_apart"]["spacing"]
    results.append(report("ruins with spacing keep their distance", len(spots) >= 2 and min(gaps) > spacing,
                          f"{len(spots)} placed, closest {min(gaps, default=None)} chunks, spacing {spacing}"))
    check_furnished_ruins(results, world, ruins["furnished"])
    check_high_ground(results, world, ruins["on_a_rise"])


def check_furnished_ruins(results, world, ruin):
    def at(column_x, column_z, chunks, block):
        return [(x, y, z) for x, y, z in world.find(block) if (x & 15, z & 15) == (column_x, column_z) and (x >> 4, z >> 4) in chunks]

    built = {(x >> 4, z >> 4) for x, _, z in world.find("minecraft:yellow_concrete")}
    ladders, lanterns = at(3, 2, built, "minecraft:ladder"), at(3, 3, built, "minecraft:lantern")
    results.append(report("a ruin's parts can set a block state", ladders and lanterns
                          and all(world.properties_at(*spot).get("facing") == "east" for spot in ladders)
                          and all(world.properties_at(*spot).get("hanging") == "true" for spot in lanterns),
                          f"{len(ladders)} ladders, {len(lanterns)} lanterns"))
    barrels, chests, trapped = at(5, 2, built, "minecraft:barrel"), at(6, 2, built, "minecraft:chest"), at(7, 2, built, "minecraft:trapped_chest")
    tables = [{world.loot_table_at(*spot) for spot in spots} for spots in (barrels, chests, trapped)]
    results.append(report("each container in a ruin can have its own loot, and the rest share the ruin's",
                          all(len(table) == 1 for table in tables) and len(set().union(*tables)) == 3 and all(next(iter(table)).startswith("gm:chests/") for table in tables),
                          str(tables)))


def check_high_ground(results, world, ruin):
    def rises(block):
        """How far each chunk with this block in it stands above the average of the four around it, leaving out any whose neighbours aren't saved."""
        found = []
        for x, _, z in world.find(block):
            middle_x, middle_z = (x & ~15) + 8, (z & ~15) + 8
            around = [world.ground_at(middle_x + dx, middle_z + dz) for dx, dz in ((16, 0), (-16, 0), (0, 16), (0, -16))]
            if None not in around:
                found.append(world.ground_at(middle_x, middle_z) - sum(around) / 4)
        return found

    wanted, placed, anywhere = ruin["highGround"], rises("minecraft:cyan_concrete"), rises("minecraft:lodestone") + rises("minecraft:yellow_concrete")
    # As with the ground under a part, sand and gravel can still fall away afterwards.
    high = sum(1 for rise in placed if rise >= wanted)
    results.append(report("ruins that want high ground stand above the chunks around them", placed and high >= len(placed) * 0.98,
                          f"{high} of {len(placed)} at least {wanted} above, lowest {min(placed, default=None)}"))
    low = sum(1 for rise in anywhere if rise < wanted)
    results.append(report("while others go anywhere, so that's the reason", low > 0, f"{low} of {len(anywhere)} others are lower than that"))


def slot(name, table="items"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"hooks/{name}"]["slot"]


def rcon(*command):
    return runtime.rcon("prod", *command, check=False)


def empty_hands():
    """What's lying around first, or something dropped by the last step gets picked up and goes in the main hand instead."""
    rcon("kill", "@e[type=minecraft:item]")
    rcon("clear", PLAYER)


def holds(place, item):
    return "passed" in rcon("execute", "if", "items", "entity", PLAYER, place, item)


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

    # Its own sounds, heard on the client, starting with one it makes by itself every so often.
    bindings = json.loads((runtime.RUNTIME / "prod" / "config" / "conduit" / "bindings.json").read_text(encoding="utf-8"))
    idle, hurt, death = (re.escape("gm:" + bindings[f"sound:hooks/{name}"]) for name in SOUNDS)
    client.wait(rf"\[M8\] sound: {idle}", 90)
    results.append(report("a mob definition can name its idle sound", True))
    rcon("damage", f"@e[type={mob},limit=1]", "1")
    client.wait(rf"\[M8\] sound: {hurt}", 20)
    results.append(report("and its hurt sound", True))
    time.sleep(2)

    rcon("kill", f"@e[type={mob}]")
    found = client.wait(r"\[M8\] chat: HOOK killed by (\w+)", 20)
    results.append(report("a module hears a mob die, and how", True, found.group(1)))
    client.wait(rf"\[M8\] sound: {death}", 20)
    results.append(report("and its death sound", True))

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


def play_examining(client, results):
    x, y, z = SPOT
    block, mob = slot("hook_block", "blocks"), slot("hook_mob", "mobs")
    empty_hands()
    rcon("setblock", str(x), str(y), str(z + 2), block)
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "60")
    time.sleep(1)
    client.ask("sneak")
    client.ask(f"useblock {x} {y} {z + 2}")
    client.wait(r"\[M8\] chat: HOOK examined block true", 20)
    results.append(report("a module hears a player examine a block", True))
    found = client.wait(r"\[M8\] chat: HOOK learned (\S+) called (.+)$", 20)
    results.append(report("a module hears knowledge being learned, by its name and its title", found.groups() == ("hooks/hook_lore", "Hook Lore"), str(found.groups())))
    client.ask(f"useblock {x} {y} {z + 2}")
    time.sleep(2)
    results.append(report("and only the first time, though it can be examined again",
                          chat_count(client, "learned") == 1 and chat_count(client, "examined block true") == 2))
    rcon("setblock", str(x), str(y), str(z + 2), "minecraft:air")

    rcon("summon", mob, str(x), str(y), str(z + 2), "{NoAI:1b,PersistenceRequired:1b}")
    time.sleep(2)
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "31")
    time.sleep(1)
    client.ask("rightclick")
    client.wait(r"\[M8\] chat: HOOK examined mob true", 20)
    time.sleep(2)
    results.append(report("a module hears a player examine a mob, once for each look", chat_count(client, "examined mob true") == 1))
    client.ask("unsneak")
    rcon("kill", f"@e[type={mob}]")


def play_drops(client, results):
    x, y, z = SPOT
    scrap, pile, token = slot("hook_scrap", "blocks"), slot("hook_pile", "blocks"), slot("hook_token")
    empty_hands()
    rcon("setblock", str(x), str(y), str(z + 1), pile)
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "60")
    time.sleep(1)
    client.ask("mine 60")
    # What's dropped can land out of reach from where it was mined, so go and stand on it.
    rcon("tp", PLAYER, f"{x + 0.5}", str(y), f"{z + 1.5}")
    time.sleep(2)
    glass, tokens = rcon("clear", PLAYER, "minecraft:glass_pane", "0"), rcon("clear", PLAYER, token, "0")
    results.append(report("a block can drop several things, vanilla's among them, and mining it gives them all", "Found 1" in glass and "Found 2" in tokens, f"{glass}, {tokens}"))

    # This asks for real drops, with the tools that matter, and leaves the block where it is.
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "60")
    spot = (str(x), str(y), str(z + 1))
    rcon("setblock", *spot, scrap)
    empty_hands()
    rcon("loot", "give", PLAYER, "mine", *spot, "minecraft:iron_pickaxe")
    copper = rcon("clear", PLAYER, "minecraft:copper_ingot", "0")
    results.append(report("a block's one drop can be vanilla's, in the amounts it says", "Found 2" in copper, copper))
    rcon("setblock", *spot, pile)
    empty_hands()
    rcon("loot", "give", PLAYER, "mine", *spot, 'minecraft:diamond_pickaxe[minecraft:enchantments={"minecraft:silk_touch":1}]')
    itself, first, second = rcon("clear", PLAYER, pile, "0"), rcon("clear", PLAYER, "minecraft:glass_pane", "0"), rcon("clear", PLAYER, token, "0")
    results.append(report("silk touch gives the block itself, and none of the rest", "Found 1" in itself and "Found" not in first + second, f"{itself}, {first}, {second}"))
    rcon("setblock", *spot, "minecraft:air")
    empty_hands()


def check_ruin_loot(results):
    """A loot table with a mistake in it can still load, so this opens what's really in each kind of container."""
    world = World()
    built = {(x >> 4, z >> 4) for x, _, z in world.find("minecraft:yellow_concrete")}
    token = slot("hook_token")
    for block, column, item, says in (("barrel", (5, 2), "minecraft:brick", "a barrel holds its own loot"),
                                      ("chest", (6, 2), token, "and a chest holds its own, naming this world's item"),
                                      ("trapped_chest", (7, 2), "minecraft:flint", "and one with none of its own gets the ruin's")):
        spot = next((x, y, z) for x, y, z in world.find(f"minecraft:{block}") if (x & 15, z & 15) == column and (x >> 4, z >> 4) in built)
        answer = rcon("execute", "if", "items", "block", *map(str, spot), "container.*", item)
        results.append(report(says, "passed" in answer, f"{spot}: {answer}"))


def play_inventory_hooks(client, results):
    x, y, z = SPOT
    empty_hands()
    for index, item in enumerate(("cobblestone", "dirt", "sand")):
        rcon("item", "replace", "entity", PLAYER, f"inventory.{index}", "with", f"minecraft:{item}")
    time.sleep(1)

    # What players asked for. On its own the game only moves the first slot of a drag.
    client.ask("inventory")
    client.ask("shot inventory")
    client.ask("shiftdrag 9 10 11")
    time.sleep(1)
    moved = [holds(f"hotbar.{index}", f"minecraft:{item}") for index, item in enumerate(("cobblestone", "dirt", "sand"))]
    results.append(report("holding shift and dragging moves every slot it crosses", all(moved), str(moved)))

    empty_hands()
    rcon("item", "replace", "entity", PLAYER, "inventory.0", "with", "minecraft:cobblestone")
    time.sleep(1)
    client.ask(f"press {KEY_K}")
    time.sleep(1)
    results.append(report("a module gets keys on an inventory screen, and can act on them", holds("hotbar.0", "minecraft:cobblestone")))

    # It claims every key, so E shouldn't close this, and Escape still has to.
    client.ask(f"press {KEY_E}")
    client.ask("screen")
    results.append(report("a module can claim a key from the game", re.findall(r"\[M8\] the screen is (\w+)", client.text())[-1] != "none"))
    client.ask(f"press {KEY_ESCAPE}")
    client.ask("screen")
    results.append(report("no module can stop Escape closing the screen", re.findall(r"\[M8\] the screen is (\w+)", client.text())[-1] == "none"))

    # With no screen open, and then with one that someone types into.
    empty_hands()
    rcon("item", "replace", "entity", PLAYER, "inventory.0", "with", "minecraft:cobblestone")
    time.sleep(1)
    client.ask("chat")
    client.ask(f"press {KEY_K}")
    client.ask("close")
    time.sleep(1)
    results.append(report("a key pressed in chat never reaches a module", holds("inventory.0", "minecraft:cobblestone")))
    client.ask(f"press {KEY_K}")
    time.sleep(1)
    results.append(report("a module gets keys in the world, and can use the player's own inventory", holds("hotbar.0", "minecraft:cobblestone")))

    # In an anvil, the same slot number is the seventh of the main rows. The box for its name has the keyboard as it opens.
    empty_hands()
    rcon("item", "replace", "entity", PLAYER, "inventory.6", "with", "minecraft:cobblestone")
    rcon("setblock", str(x), str(y), str(z + 1), "minecraft:anvil")
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "60")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z + 1}")
    client.ask("screen")
    opened = re.findall(r"\[M8\] the screen is (\w+)", client.text())[-1]
    client.ask(f"press {KEY_K}")
    time.sleep(1)
    results.append(report("a key typed into a text box never reaches a module", opened == "AnvilScreen" and holds("inventory.6", "minecraft:cobblestone"), opened))
    client.ask("close")
    rcon("setblock", str(x), str(y), str(z + 1), "minecraft:air")

    # A screen effect, on and off again, and then left on to see that it goes with the module.
    rcon("tp", PLAYER, str(x), str(y), str(z), "0", "-30")
    time.sleep(1)
    client.ask("shot effect_off")
    client.ask(f"press {KEY_J}")
    client.ask("shot effect_on")
    client.ask(f"press {KEY_J}")
    client.ask("shot effect_off_again")
    client.ask(f"press {KEY_J}")

    # Unloading has to take all of it away, with no help from the module.
    rcon("conduit", "module", "unload", "hooks")
    time.sleep(2)
    client.ask("shot effect_unloaded")
    time.sleep(2)
    empty_hands()
    for index, item in enumerate(("cobblestone", "dirt")):
        rcon("item", "replace", "entity", PLAYER, f"inventory.{index}", "with", f"minecraft:{item}")
    time.sleep(1)
    client.ask(f"press {KEY_K}")
    time.sleep(1)
    results.append(report("unloading a module removes its key hook", holds("inventory.0", "minecraft:cobblestone")))
    client.ask("inventory")
    client.ask("shot inventory_unloaded")
    client.ask("shiftdrag 9 10")
    time.sleep(1)
    results.append(report("unloading a module removes its inventory hooks", holds("inventory.1", "minecraft:dirt")))
    client.ask("close")


def check_mark(results, shots):
    """Whether the corner really shows what the module drew there, and stops once it's unloaded."""
    def marked(name):
        shot = next(iter(sorted(shots.glob(f"*{name}.png"))), None)
        if shot is None:
            return None
        with Image.open(shot) as image:
            return sum(1 for pixel in image.convert("RGB").crop((0, 0, 16, 16)).getdata() if pixel == MARK_COLOUR)

    drawn, gone = marked("m8_inventory"), marked("m8_inventory_unloaded")
    results.append(report("a module can draw on an inventory screen", bool(drawn), f"{drawn} pixels of its colour"))
    results.append(report("and what it drew goes when it's unloaded", gone == 0, f"{gone} pixels of its colour"))

    def looks(name):
        shot = next(iter(sorted(shots.glob(f"*{name}.png"))), None)
        if shot is None:
            return None
        with Image.open(shot) as image:
            return ImageStat.Stat(image.convert("RGB")).mean

    off, on, again, unloaded = looks("m8_effect_off"), looks("m8_effect_on"), looks("m8_effect_off_again"), looks("m8_effect_unloaded")
    if None in (off, on, again, unloaded):
        results.append(report("the screen effect was photographed", False, str(sorted(path.name for path in shots.glob("*.png")))))
        return
    near = lambda first, second: all(abs(a - b) < EFFECT_TOLERANCE for a, b in zip(first, second))
    results.append(report("a module can put a shader over the screen, from the feature's own file", near([255 - value for value in off], on), f"off {off}, on {on}"))
    results.append(report("and take it off again", near(off, again), str(again)))
    results.append(report("and it goes when the module unloads", near(off, unloaded), str(unloaded)))


def play_broken_effect(client, results):
    """A shader that passed but won't compile on someone's computer. On its own, the game would drop every pack, and with them the server."""
    for path in (runtime.RUNTIME / "prod" / "live-assets" / "assets" / "gm" / "shaders" / "post").glob("*.fsh"):
        path.write_text("#version 330\nthis is not a shader\n", encoding="utf-8")
    pack = runtime.RUNTIME / "prod" / "polymer" / "resource_pack.zip"
    before = pack.stat().st_mtime
    rcon("polymer", "generate-pack", "reload")
    # It isn't there at all for a moment, while it's being made.
    deadline = time.monotonic() + 30
    while not (pack.exists() and pack.stat().st_mtime != before) and time.monotonic() < deadline:
        time.sleep(0.25)
    # Back in with the new pack, and the module that uses it, which is unloaded by now.
    client.ask("oldcompanion", 300)
    rcon("conduit", "module", "reload")
    time.sleep(5)
    client.ask(f"press {KEY_J}")
    time.sleep(2)
    try:
        client.ask("screen", 20)
        stayed = True
    except TimeoutError:
        stayed = False
    results.append(report("the game really tried the broken effect", "Failed to load post chain" in client.text()))
    results.append(report("and a shader that won't compile doesn't take anyone off the server", stayed))


def check_old_companions(results, client):
    results.append(report("a current companion isn't told it's out of date", OUT_OF_DATE not in client.text()))
    result = subprocess.run([sys.executable, "-u", "scripts/smoketest_join.py", "--name", "nocompanion", "--stay", "6", "--watch-for", OUT_OF_DATE],
                            cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=120)
    results.append(report("and neither is someone with no companion", "JOINED" in result.stdout and f"SAW {OUT_OF_DATE}" not in result.stdout, result.stdout[-120:]))
    client.ask("oldcompanion", 300)
    found = client.wait(rf"\[M8\] chat: .*{OUT_OF_DATE}", 30)
    results.append(report("a companion from before inventory hooks is told to update", True, found.group(0)[:120]))


def main():
    build_source()
    print("building and releasing the test feature", flush=True)
    release()
    generate_land()
    results = []
    check_ruins(results)

    with sign._locked():
        sign._load_key()
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    # Generations are remembered per client, so a run after this one needs a clean slate to prove the same things.
    shutil.rmtree(mods / "companion" / "build" / "run" / "clientGameTest" / "config" / "companion", ignore_errors=True)
    client = Client(mods, runtime.REPORTS / "m16-client.log", {"COMPANION_TEST_KEY": sign.public_key_text()})
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        play_server_hooks(client, results)
        play_examining(client, results)
        play_drops(client, results)
        check_ruin_loot(results)
        play_inventory_hooks(client, results)
        check_old_companions(results, client)
        play_broken_effect(client, results)
    finally:
        client.stop()
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    out = runtime.REPORTS / "m16"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_*.png"):
        shutil.copy(path, out)
    check_mark(results, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
