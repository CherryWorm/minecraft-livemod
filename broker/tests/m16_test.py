#!/usr/bin/env python3
"""What modules can hook into, proved on a real client and by reading the world's raw files. A feature plays its own sound by
name and hears about blocks broken, mobs killed, food eaten, players joining, knowledge learned and things examined. A block's
removal is noticed however it goes, and a machine can still read its data then. A mob can be fed by using an item on it, and has
its own sounds. A block's drops can be vanilla's and several at once. Ruins follow the terrain, pick between layouts, keep their
distance, set block states, give containers their own loot and look for high ground. Start with a blank world from
reset-dev-world.sh, and reset it afterwards.

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

from broker import runtime
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


def main():
    build_source()
    print("building and releasing the test feature", flush=True)
    release()
    generate_land()
    results = []
    check_ruins(results)

    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    client = Client(runtime.WORK / "mods", runtime.REPORTS / "m16-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        play_server_hooks(client, results)
        play_examining(client, results)
        play_drops(client, results)
        check_ruin_loot(results)
    finally:
        client.stop()
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
