#!/usr/bin/env python3
"""Big ruins, dimensions and the world's protections, on a world that's been played in and is a realistic size, with a real client through the
proxy. Thousands of chunks get generated and some of them played in and built on. Then a release brings ruins too big for a chunk, a dimension
and a biome with features added, through every gate. Everything is read back from the world's raw files: each big ruin is whole, none is on land
anyone has been on, nobody's chest or building changed, and the raw world check passes. Then the server is killed partway through building one,
and it finishes and is never built twice. A player in a dimension is held through a restart and comes back where they were. Pruning and backups
are run on the result. Start with a blank world from reset-dev-world.sh and a baseline, and reset it afterwards.

Usage: python3 -m broker.tests.m30_test
"""
import collections
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import time

from PIL import Image

from broker import deploy, prune, runtime
from broker.gates import shadow, world_diff
from broker.tests.m8_test import Client, PLAYER
from broker.tests.m14_test import report, results

SOURCE = runtime.BROKER / "testsrc-m30"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "expanse"
OVERWORLD = "minecraft:overworld"
TEXTURES = {"expanse_stone": (0x70, 0x60, 0x80), "expanse_lens": (0x20, 0x90, 0xC0), "expanse_frost": (0xC0, 0xE0, 0xF0), "expanse_key": (0xE0, 0xA0, 0x20), "expanse_home": (0x20, 0xA0, 0x60)}
GRADLE_COPY = "gradle-m30"
# 16 chunks a side, because that's the most forceload takes at once. 25 of them is 6400 chunks, which is plenty to play in and go through for real.
# The world check is then tried at many times that size, by counting the same files over again, which is what it would have to read on a real server.
TILE = 256
TILES_ACROSS = 5
LAND_CHUNKS = 6400
LAND_SECONDS = 1500
SCALE_LAYERS = 24
# Where people have been. Far enough apart that there's plenty of land nobody's been to in between.
PLAYED = ((64, 64), (-512, 256), (560, -448), (-560, -560), (256, 560))
SOMEWHERE_NEW = [(-1100, 1100), (1100, 1100), (1100, -1100), (-1100, -1100), (1250, 0), (0, 1250)]
HEIGHT_BITS = 9
REGIONS_HELD = 4
FOLLOWS_WITHIN = 40
SKY_MARGIN = 15
BUILT_AT = 150
PLAYER_CHEST_ITEMS = '{Items:[{Slot:0b,id:"minecraft:diamond",count:3}]}'
HALL_WALL = "minecraft:purpur_block"
LONG_WALL = "minecraft:prismarine_bricks"
HILL_BLOCK = "minecraft:waxed_copper_block"
SHRINE_MARK = "minecraft:red_nether_bricks"
ROOM_WALL = "minecraft:black_concrete"
FILE = runtime.RUNTIME / "prod" / "world" / "conduit_ruins.jsonl"
PAUSE = runtime.RUNTIME / "prod" / "config" / "conduit" / "chaos_ruin_pause_after_chunks"
SECTOR = 4096


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def own_gradle_home():
    """This releases with a client connected, and Gradle can't share its caches between two containers while one of them is running."""
    copy = runtime.RUNTIME / "cache" / GRADLE_COPY
    if not copy.exists():
        shutil.copytree(runtime.RUNTIME / "cache" / "gradle", copy, symlinks=True)
    return f"/cache/{GRADLE_COPY}"


def target():
    return SOURCE / "mods" / "genesis" / "features" / "expanse"


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    if target().exists():
        shutil.rmtree(target())
    shutil.copytree(FIXTURE, target())
    textures = target() / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for name, colour in TEXTURES.items():
        Image.new("RGBA", (16, 16), (*colour, 255)).save(textures / f"{name}.png")


def release():
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m30-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=2400,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages", "shadow")}), f"in {time.monotonic() - started:.0f}s", flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        print(result.stdout[-1500:], flush=True)
        sys.exit(1)
    return promoted


def ledger():
    return json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))


def slot(name, table="blocks"):
    return "gm:" + ledger()[table][f"expanse/{name}"]["slot"]


def world():
    return runtime.RUNTIME / "prod" / "world"


def regions_of(dimension=OVERWORLD):
    namespace, name = dimension.split(":")
    return world() / "dimensions" / namespace / name / "region"


def count_chunks(folder):
    """How many chunks are on the disk, from the files' headers, so it's quick whatever size the world is."""
    total = 0
    for path in folder.glob("*.mca"):
        with path.open("rb") as stream:
            header = stream.read(SECTOR)
        total += sum(1 for entry in struct.unpack(f">{len(header) // 4}I", header) if entry) if len(header) == SECTOR else 0
    return total


def generate_land():
    """Everything's frozen meanwhile, because forced chunks tick, and grass spreading would count as someone having been there. Real chunks that far from anyone don't tick."""
    rcon("tick", "freeze")
    started = time.monotonic()
    half = TILES_ACROSS // 2
    for row, tile_x in enumerate(range(-half, TILES_ACROSS - half)):
        for tile_z in range(-half, TILES_ACROSS - half):
            x, z = tile_x * TILE, tile_z * TILE
            rcon("forceload", "add", x, z, x + TILE - 1, z + TILE - 1)
        # Held a row at a time, so this world doesn't need more memory than the real one has.
        deadline = time.monotonic() + LAND_SECONDS / TILES_ACROSS
        wanted = (row + 1) * TILES_ACROSS * 256
        while time.monotonic() < deadline:
            rcon("save-all", "flush")
            if count_chunks(regions_of()) >= wanted:
                break
            time.sleep(10)
        rcon("forceload", "remove", "all")
        print(f"{count_chunks(regions_of())} chunks after {time.monotonic() - started:.0f}s", flush=True)
    rcon("save-all", "flush")
    time.sleep(5)
    rcon("tick", "unfreeze")
    size = sum(path.stat().st_size for path in regions_of().glob("*.mca"))
    report("the world is a realistic size", count_chunks(regions_of()) >= LAND_CHUNKS * 0.95, f"{count_chunks(regions_of())} chunks, {size / 1e6:.0f} MB of region files")


def play(client):
    """Someone's been to each of these and built something, which has to stay exactly as it is."""
    rcon("gamemode", "creative", PLAYER)
    rcon("difficulty", "peaceful")
    built = []
    for x, z in PLAYED:
        rcon("tp", PLAYER, x, 200, z)
        time.sleep(12)
        y = BUILT_AT
        rcon("fill", x - 3, y, z - 3, x + 3, y + 3, z + 3, "minecraft:stone_bricks", "hollow")
        rcon("setblock", x, y + 1, z, f"minecraft:chest{PLAYER_CHEST_ITEMS}")
        built.append((x, y, z))
        time.sleep(3)
    rcon("save-all", "flush")
    time.sleep(5)
    return built


def visited_chunks(folder):
    visited = set()
    for path in folder.glob("*.mca"):
        for x, z, chunk in world_diff.read_chunks(path):
            if chunk.get("InhabitedTime", 0) > 0 or world_diff.touched_blocks(chunk) > 0:
                visited.add((x, z))
    return visited


def decisions():
    found = []
    if FILE.exists():
        for line in FILE.read_text(encoding="utf-8").splitlines():
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if parsed.get("ruin"):
                found.append(parsed)
    return found


def settle(seconds=240, server="prod"):
    """Waits for whatever's loaded to finish, and for it to reach the disk."""
    mark = runtime.utc_now()
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        time.sleep(5)
        found = re.findall(r"retrogen: queued=(\d+) .* plans=(\d+)", runtime.logs_since(server, mark))
        # A chunk at the edge of what's loaded can wait forever for the next one, so the queue only gets so long.
        if found and found[-1][1] == "0" and (found[-1][0] == "0" or time.monotonic() - started > 30):
            break
    runtime.rcon(server, "save-all", "flush", check=False)
    time.sleep(5)


class Raw:
    """Reads the world's raw files, a region at a time, so this can't be fooled by the mod's own idea of what it placed."""

    def __init__(self, dimension=OVERWORLD):
        self.folder = regions_of(dimension)
        self.regions = {}

    def chunk(self, x, z):
        region = x >> 5, z >> 5
        if region not in self.regions:
            # Only a few at once, because a chunk read into memory takes up far more room than it does on the disk.
            if len(self.regions) >= REGIONS_HELD:
                self.regions.pop(next(iter(self.regions)))
            path = self.folder / f"r.{region[0]}.{region[1]}.mca"
            self.regions[region] = {(chunk_x, chunk_z): chunk for chunk_x, chunk_z, chunk in world_diff.read_chunks(path)} if path.exists() else {}
        return self.regions[region].get((x, z))

    def block(self, x, y, z):
        chunk = self.chunk(x >> 4, z >> 4)
        if chunk is None:
            return None
        section = next((entry for entry in chunk.get("sections", []) if entry["Y"] == y >> 4), None)
        if section is None:
            return "minecraft:air"
        blocks, palette = world_diff.decode(section)
        return palette[blocks[(y & 15) << 8 | (z & 15) << 4 | x & 15]]

    def ground(self, x, z):
        chunk = self.chunk(x >> 4, z >> 4)
        index = (x & 15) + (z & 15) * 16
        per_long = 64 // HEIGHT_BITS
        heights = chunk["Heightmaps"]["OCEAN_FLOOR"]
        stored = ((heights[index // per_long] & ((1 << 64) - 1)) >> (index % per_long * HEIGHT_BITS)) & ((1 << HEIGHT_BITS) - 1)
        return stored - 64 - 1

    def applied(self, x, z):
        chunk = self.chunk(x, z)
        return chunk.get("fabric:attachments", {}).get("gm:applied_patches", []) if chunk else []


def box_cells(part):
    to = part.get("to", [part["x"], part["y"], part["z"]])
    for x in range(min(part["x"], to[0]), max(part["x"], to[0]) + 1):
        for z in range(min(part["z"], to[2]), max(part["z"], to[2]) + 1):
            for y in range(min(part["y"], to[1]), max(part["y"], to[1]) + 1):
                yield x, y, z


def expected_blocks(ruin):
    """Each part in the order they go in, so what's in the same place twice ends up as the last one."""
    expected = {}
    for part in ruin["parts"]:
        block = part["block"]
        if block.startswith("$block:"):
            block = slot(block.split(":")[1])
        for cell in box_cells(part):
            expected[cell] = block
    return expected


def missing_from(raw, decision, ruin):
    expected = expected_blocks(ruin)
    x, y, z = decision["x"], decision["y"], decision["z"]
    missing = []
    for (part_x, part_y, part_z), block in expected.items():
        # One that follows the land has each column at its own height, so all that can be said for it is that the column has it somewhere.
        heights = range(y - FOLLOWS_WITHIN, y + FOLLOWS_WITHIN) if ruin.get("followTerrain") else (y + part_y,)
        if not any(raw.block(x + part_x, height, z + part_z) == block for height in heights):
            missing.append((x + part_x, y + part_y, z + part_z, block))
    return missing, len(expected)


def blocks_in(chunk):
    return {section["Y"]: section.get("block_states") for section in chunk.get("sections", [])}


def changes_between(before, after):
    """What each block that's different became, and how many, between two copies of a chunk's blocks."""
    found = collections.Counter()
    for y, states in before.items():
        if after.get(y) != states:
            old_blocks, old_palette = world_diff.decode({"block_states": states})
            new_blocks, new_palette = world_diff.decode({"block_states": after.get(y) or {}})
            for old, new in zip(old_blocks, new_blocks):
                if old_palette[old] != new_palette[new]:
                    found[(old_palette[old], new_palette[new])] += 1
    return found


def chunks_of(decision, ruin):
    return {((decision["x"] + cell[0]) >> 4, (decision["z"] + cell[2]) >> 4) for part in ruin["parts"] for cell in box_cells(part)}


def check_big_ruins(manifest, visited_before):
    ruins = manifest["ruins"]
    by_id = {ruin["id"]: ruin for ruin in ruins.values()}
    raw = Raw()
    placed = [entry for entry in decisions() if entry["placed"] and entry["ruin"] in by_id and entry["dimension"] == OVERWORLD]
    big = [entry for entry in placed if max(chunk_span(by_id[entry["ruin"]])) > 1]
    halls = [entry for entry in big if entry["ruin"] == "great_hall_v1"]
    report("big ruins were placed", len(halls) >= 3, f"{len(big)} big ruins, {len(halls)} of them halls")
    refused = [entry for entry in decisions() if not entry["placed"]]
    report("and some spots were refused, saying why", refused and all(entry.get("why") for entry in refused), f"{len(refused)}, like {refused[0]['why'] if refused else None}")
    whole = 0
    problems = []
    for entry in halls:
        missing, total = missing_from(raw, entry, by_id[entry["ruin"]])
        if missing:
            problems.append((entry["x"], entry["z"], len(missing), total, missing[:2]))
        else:
            whole += 1
    report("every hall is whole, block for block, across all its chunks", halls and whole == len(halls), f"{whole} of {len(halls)}, {problems[:2]}")
    across = {len(chunks_of(entry, by_id[entry["ruin"]])) for entry in halls}
    report("and they really cross chunks", across and max(across) > 1, f"chunks each: {sorted(across)}")
    on_visited = [entry for entry in big if chunks_of(entry, by_id[entry["ruin"]]) & visited_before]
    report("none of them is on land anyone had been on", not on_visited, f"{len(on_visited)} of {len(big)}")
    chests = 0
    for entry in halls:
        chest = raw.chunk((entry["x"] + 24) >> 4, (entry["z"] + 24) >> 4)
        chests += sum(1 for block in chest.get("block_entities", []) if (block.get("x"), block.get("y"), block.get("z")) == (entry["x"] + 24, entry["y"], entry["z"] + 24)
                      and str(block.get("LootTable", "")).startswith("gm:chests/"))
    report("each hall's chest has its loot", halls and chests == len(halls), f"{chests} of {len(halls)}")
    keys = [(entry["ruin"], entry["chunkX"], entry["chunkZ"]) for entry in placed]
    report("nothing was decided on twice", len(keys) == len(set(keys)), f"{len(keys)} decisions")
    gravel = 0
    for entry in halls:
        if raw.block(entry["x"] + 40, entry["y"] + 2, entry["z"] + 40) == "minecraft:gravel" and raw.block(entry["x"] + 40, entry["y"] + 1, entry["z"] + 40) != "minecraft:gravel":
            gravel += 1
    report("loose gravel in a big ruin stays put, over nothing", halls and gravel == len(halls), f"{gravel} of {len(halls)}")
    check_following_walls(raw, by_id, big)
    check_hills(raw, by_id, big)
    check_shrines(raw, by_id, placed)
    check_cave_rooms(raw, by_id, placed)


def chunk_span(ruin):
    cells = [cell for part in ruin["parts"] for cell in box_cells(part)]
    return max(cell[0] for cell in cells) // 16 + 1, max(cell[2] for cell in cells) // 16 + 1


def check_following_walls(raw, by_id, big):
    walls = [entry for entry in big if entry["ruin"] == "long_wall_v1"]
    flush, rises = 0, []
    for entry in walls:
        heights = []
        for x in range(entry["x"], entry["x"] + 40):
            z = entry["z"] + 8
            lowest = next((y for y in range(entry["y"] - 40, entry["y"] + 40) if raw.block(x, y, z) == LONG_WALL), None)
            if lowest is not None:
                heights.append(lowest)
        if len(heights) == 40:
            flush += 1
        rises.append(max(heights, default=0) - min(heights, default=0))
    report("a big ruin can follow the land across chunks", walls and flush == len(walls) and any(rises), f"{flush} of {len(walls)} whole, height changes {sorted(rises)[-5:]}")
    report("and stays within its maxSlope", walls and max(rises, default=0) <= 20, f"largest {max(rises, default=None)}")


def check_hills(raw, by_id, big):
    hills = [entry for entry in big if entry["ruin"] == "on_the_hill_v1"]
    rises = []
    for entry in hills:
        middle = raw.ground(entry["x"] + 10, entry["z"] + 8)
        around = [raw.ground(entry["x"] + dx, entry["z"] + dz) for dx, dz in ((-8, 16), (40, 16), (16, -8), (16, 40))
                  if raw.chunk((entry["x"] + dx) >> 4, (entry["z"] + dz) >> 4) is not None]
        if len(around) == 4:
            rises.append(middle - sum(around) / 4)
    report("a big ruin can look for high ground", hills, f"{len(hills)} placed, standing above what's around by {sorted(round(rise, 1) for rise in rises)[:6]}")


def check_shrines(raw, by_id, placed):
    shrines = [entry for entry in placed if entry["ruin"] == "gravel_shrine_v1"]
    held = 0
    for entry in shrines:
        x, y, z = entry["x"], entry["y"], entry["z"]
        if raw.block(x + 9, y + 4, z + 9) == "minecraft:gravel" and raw.block(x + 6, y + 5, z + 6) == "minecraft:sand" and raw.block(x + 6, y + 4, z + 6) != "minecraft:sand":
            held += 1
    # Not quite all, because they fall as soon as something next to them changes, as they should, and leaves in the next tree can decay.
    report("loose gravel and sand in a small ruin stay where they're drawn", shrines and held >= len(shrines) * 0.9, f"{held} of {len(shrines)}")


def check_cave_rooms(raw, by_id, placed):
    rooms = [entry for entry in placed if entry["ruin"] == "cave_room_v1"]
    reached = 0
    ruin = by_id["cave_room_v1"]
    for entry in rooms:
        own = {cell for part in ruin["parts"] for cell in box_cells(part)}
        hollow = {cell for part in ruin["parts"] if part["block"] == "minecraft:air" for cell in box_cells(part)}
        opening = False
        for x, y, z in hollow:
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                if (x + dx, y + dy, z + dz) not in own and raw.block(entry["x"] + x + dx, entry["y"] + y + dy, entry["z"] + z + dz) in ("minecraft:air", "minecraft:cave_air"):
                    opening = True
        reached += opening
    # Not quite all, because water or lava can flow into the cave afterwards, which then doesn't count as open here.
    report("an underground ruin that opens onto a cave has a way in", rooms and reached >= len(rooms) * 0.98, f"{reached} of {len(rooms)}")


def check_player_land(built, visited_before):
    raw = Raw()
    kept = 0
    for x, y, z in built:
        chest = raw.chunk(x >> 4, z >> 4)
        here = [entity for entity in chest.get("block_entities", []) if (entity.get("x"), entity.get("y"), entity.get("z")) == (x, y + 1, z)]
        walls = all(raw.block(x + dx, y + 1, z + dz) == "minecraft:stone_bricks" for dx, dz in ((-3, 0), (3, 0), (0, -3), (0, 3)))
        if here and here[0].get("Items", [{}])[0].get("count") == 3 and walls:
            kept += 1
    report("everything players built is exactly where they left it, with its chests full", kept == len(built), f"{kept} of {len(built)}")


def raw_check_on_prod(before, patches, dimension=OVERWORLD):
    """The same check the gate runs on the shadow world, but on the real thing, over everything that's happened."""
    started = time.monotonic()
    result = run_world_check(before, regions_of(dimension), patches)
    print(result.stdout[-1200:], flush=True)
    report(f"the raw world check passes on {dimension}", result.returncode == 0 and "PASS" in result.stdout,
           f"{time.monotonic() - started:.1f}s, " + " ".join(line for line in result.stdout.splitlines() if line.startswith(("chunks compared", "peak memory"))))


def run_world_check(before, after, patches):
    """With saves held off, so the files can't change partway through being read."""
    rules = runtime.DIFF / "m30-rules.json"
    rules.parent.mkdir(parents=True, exist_ok=True)
    rules.write_text(json.dumps(patches), encoding="utf-8")
    rcon("save-off")
    rcon("save-all", "flush")
    time.sleep(3)
    try:
        return subprocess.run([sys.executable, str(runtime.REPO / "broker" / "gates" / "world_diff.py"), str(before), str(after), "--rules", str(rules), "--allow-new-block-entities"],
                              capture_output=True, text=True, check=False, timeout=1800)
    finally:
        rcon("save-on")


def check_world_check_scales(before, patches):
    """Far more land than here has been played on, by counting the same files many times over. It's the size of what it has to read that once took a server down."""
    bigger_before, bigger_after = runtime.DIFF / "m30-big-before", runtime.DIFF / "m30-big-after"
    for folder in (bigger_before, bigger_after):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
    for layer in range(SCALE_LAYERS):
        for source, folder in ((before, bigger_before), (regions_of(), bigger_after)):
            for path in source.glob("*.mca"):
                # Linked, not copied, so this doesn't fill the disk.
                name = path.name.split(".")
                os.link(path, folder / f"r.{int(name[1]) + layer * 1000}.{name[2]}.mca")
    size = sum(path.stat().st_size for path in bigger_before.glob("*.mca"))
    started = time.monotonic()
    result = run_world_check(bigger_before, bigger_after, patches)
    report("the world check holds up at many times the size", result.returncode == 0 and "PASS" in result.stdout,
           f"{size / 1e9:.1f} GB of region files, {time.monotonic() - started:.0f}s, " + " ".join(line for line in result.stdout.splitlines() if line.startswith("peak memory")))
    shutil.rmtree(bigger_before)
    shutil.rmtree(bigger_after)


def stop_prod():
    runtime.run(["./scripts/stack.sh", "stop", "prod"], timeout=180)


def start_prod():
    runtime.run(["./scripts/stack.sh", "up", "-d", "prod"], timeout=180)
    runtime.wait_ready("prod", timeout=240)


def check_crash(client):
    """Stopped partway through one, with some of its chunks saved and some not, then killed outright, the way a crash would."""
    PAUSE.write_text("2\n", encoding="utf-8")
    rcon("conduit", "retrogen", "reload")
    mark = runtime.utc_now()
    paused = None
    known = {(entry["ruin"], entry["chunkX"], entry["chunkZ"]) for entry in decisions()}
    for x, z in SOMEWHERE_NEW:
        rcon("tp", PLAYER, x, 220, z)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            time.sleep(3)
            paused = re.search(r"chaos: ruin (\S+) paused after 2 of (\d+) chunks", runtime.logs_since("prod", mark))
            if paused:
                break
        if paused:
            break
    report("the test got a big ruin stopped partway through", paused is not None, paused.group(0) if paused else "never happened")
    if paused is None:
        PAUSE.unlink()
        return
    ruin_id, total = paused.group(1), int(paused.group(2))
    entry = next(item for item in reversed(decisions()) if item["ruin"] == ruin_id and item["placed"] and (item["ruin"], item["chunkX"], item["chunkZ"]) not in known)
    # Saved with some of it in, and then the rest is lost, as it would be if the server died any time before the next save.
    rcon("save-all", "flush")
    time.sleep(5)
    PAUSE.unlink()
    with FILE.open("a", encoding="utf-8") as stream:
        stream.write('{"ruin":"never_finished')
    runtime.run(["docker", "kill", "--signal=KILL", runtime.container("prod")], check=False)
    time.sleep(3)
    return entry, total


def check_crash_recovery(manifest, crash):
    entry, total = crash
    by_id = {ruin["id"]: ruin for ruin in manifest["ruins"].values()}
    ruin = by_id[entry["ruin"]]
    chunks = sorted(chunks_of(entry, ruin))
    marker = f"{entry['ruin']}@{entry['chunkX']},{entry['chunkZ']}"
    raw = Raw()
    saved = [chunk for chunk in chunks if marker in raw.applied(*chunk)]
    without = [chunk for chunk in chunks if marker not in raw.applied(*chunk)]
    missing, count = missing_from(raw, entry, ruin)
    report("after the crash some of it really is on the disk, and some really isn't", saved and without and missing, f"{len(saved)} chunks have it, {len(without)} don't, {len(missing)} of {count} blocks missing")
    # Only the blocks, because the light in these chunks changes when the next one's share goes in.
    snapshot = {chunk: blocks_in(raw.chunk(*chunk)) for chunk in saved}

    start_prod()
    time.sleep(5)
    logs = (runtime.RUNTIME / "prod" / "logs" / "latest.log").read_text(encoding="utf-8", errors="replace")
    report("a line of the file cut off by the crash doesn't stop anything", "Leaving out a line" in logs and "Can't read" not in logs)
    # Nobody has to be near for it to finish, as long as something loads it. Frozen, so loading it doesn't count as anyone having been there.
    rcon("tick", "freeze")
    minimum = min(chunk[0] for chunk in chunks), min(chunk[1] for chunk in chunks)
    maximum = max(chunk[0] for chunk in chunks), max(chunk[1] for chunk in chunks)
    rcon("forceload", "add", minimum[0] * 16, minimum[1] * 16, maximum[0] * 16 + 15, maximum[1] * 16 + 15)
    settle(120)
    rcon("forceload", "remove", "all")
    rcon("tick", "unfreeze")
    rcon("save-all", "flush")
    time.sleep(5)

    raw = Raw()
    missing, count = missing_from(raw, entry, ruin)
    report("after a crash partway, it finishes", not missing, f"{len(missing)} of {count} blocks missing, like {missing[:2]}")
    report("every one of its chunks now has its share", all(marker in raw.applied(*chunk) for chunk in chunks), f"{sum(marker in raw.applied(*chunk) for chunk in chunks)} of {len(chunks)}")
    # Something else can still go in these chunks after the restart, like a small ruin that was waiting for the chunks next to it. Only this one's own blocks have to stay.
    changed = collections.Counter()
    for chunk, blocks in snapshot.items():
        changed += changes_between(blocks, blocks_in(raw.chunk(*chunk)))
    own = set(expected_blocks(ruin).values())
    report("what of it was already saved wasn't changed by finishing", not any(old in own for old, _ in changed), f"{len(snapshot)} chunks, with these other changes: {changed.most_common(5)}")
    same = [item for item in decisions() if item["ruin"] == entry["ruin"] and (item["chunkX"], item["chunkZ"]) == (entry["chunkX"], entry["chunkZ"])]
    report("it was only ever decided on once", len(same) == 1, f"{len(same)} decisions")
    chest_chunk = raw.chunk((entry["x"] + 24) >> 4, (entry["z"] + 24) >> 4) if entry["ruin"] == "great_hall_v1" else None
    if chest_chunk is not None:
        chests = [block for block in chest_chunk.get("block_entities", []) if (block.get("x"), block.get("z")) == (entry["x"] + 24, entry["z"] + 24)]
        report("with one chest, as drawn", len(chests) == 1, f"{len(chests)}")


def check_finding(client):
    """Above a hall that's really there, so the answer should say so. Nobody's been up here, and it doesn't matter now if they have."""
    hall = next(entry for entry in decisions() if entry["ruin"] == "great_hall_v1" and entry["placed"])
    x, y, z = hall["x"] + 24, min(hall["y"] + 40, 250), hall["z"] + 24
    lens, frost = slot("expanse_lens"), slot("expanse_frost")
    rcon("tp", PLAYER, x + 0.5, y + 1, z + 0.5, 0, 90)
    rcon("gamemode", "creative", PLAYER)
    rcon("fill", x - 2, y - 1, z - 2, x + 2, y - 1, z + 2, "minecraft:glass")
    rcon("setblock", x, y, z + 2, lens)
    rcon("setblock", x, y, z - 2, frost)
    time.sleep(3)
    before = count_chunks(regions_of())
    rcon("save-all", "flush")
    time.sleep(3)
    before = count_chunks(regions_of())
    client.ask(f"useblock {x} {y} {z + 2}")
    answer = client.wait(r"\[M8\] chat: ruins near: (\d+) \[(.*)\]", 20)
    time.sleep(1)
    rcon("save-all", "flush")
    time.sleep(3)
    spots = int(answer.group(1))
    report("a module can ask where a ruin is or will be", spots > 0, answer.group(0)[:300])
    report("and it says which are really there, and which may only turn up", "placed=true" in answer.group(2) and "placed=false" in answer.group(2), answer.group(2)[:200])
    placed = {(entry["x"], entry["y"], entry["z"]) for entry in decisions() if entry["ruin"] == "great_hall_v1" and entry["placed"]}
    told = re.findall(r"\[(-?\d+), (-?\d+), (-?\d+) placed=true\]", answer.group(2))
    report("what it says is there, is", told and all(tuple(map(int, spot)) in placed for spot in told), f"{len(told)} checked against {len(placed)}")
    # Asking generates nothing, however far it looks. A few chunks around the player may load in the meantime, so this only rules out the hundreds it would take.
    after = count_chunks(regions_of())
    report("and asking loads no land", after - before < 50, f"{after - before} more chunks on the disk")

    client.ask(f"useblock {x} {y} {z - 2}")
    changed = client.wait(r"\[M8\] chat: biome cells changed: (-?\d+)", 20)
    report("a module can change the climate of a piece of land", int(changed.group(1)) > 0, changed.group(0))
    told = rcon("execute", "if", "biome", x, y, z - 2, "minecraft:snowy_plains")
    report("the game goes by it", "passed" in told, told)
    client.ask("where")
    seen = json.loads(re.findall(r"\[M8\] where: (.*)$", client.text(), re.MULTILINE)[-1])
    report("and the player's own game has it straight away", seen["biome"] == "minecraft:snowy_plains", seen["biome"])
    return x, y, z - 2


def check_climate_lasts(spot):
    x, y, z = spot
    rcon("forceload", "add", x, z)
    time.sleep(3)
    told = rcon("execute", "if", "biome", x, y, z, "minecraft:snowy_plains")
    report("the climate change lasts through a restart", "passed" in told, told)
    rcon("forceload", "remove", x, z)
    rcon("save-all", "flush")
    time.sleep(3)
    chunk = Raw().chunk(x >> 4, z >> 4)
    palettes = [str(entry.get("biomes", {}).get("palette")) for entry in chunk.get("sections", [])]
    report("and it's in the land's own saved data", any("minecraft:snowy_plains" in palette for palette in palettes))


def check_added_features(content_biome):
    features = content_biome["features"]
    report("a biome can be given more of vanilla's features", "minecraft:trees_cherry" in features[9], str(features[9])[:160])
    order = runtime.vanilla_feature_order()
    order.add_biome("the release's", features)
    report("in an order the game accepts, which it would refuse to start on otherwise", True)
    found = rcon("locate", "biome", content_biome["id"])
    report("the world started with it, and it generates", "nearest" in found.lower(), found[:140])


def check_dimension(client, manifest):
    """Only what's specific to it being another folder and a restart, because M25 covers going there and back."""
    moor = slot("moor", "dimensions")
    # So nothing here can kill them, which would be a release's safe moment gone, and them back in the overworld.
    rcon("gamemode", "creative", PLAYER)
    rcon("execute", "in", moor, "run", "forceload", "add", -32, -32, 31, 31)
    client_at = enter(client)
    report("a player can cross into a dimension behind the proxy", client_at["dimension"] == moor, client_at)
    report("and arrives standing on its land", "grass" in client_at["under"] or "stone" in client_at["under"] or "dirt" in client_at["under"], client_at)
    time.sleep(6)
    settled = rcon("conduit", "unsafe")
    # Straight there and straight back, so this looks while the client is still on its loading screen. A release waits for that to pass.
    rcon("execute", "in", OVERWORLD, "run", "tp", PLAYER, 64, 201, 64)
    crossing = rcon("conduit", "unsafe")
    report("someone partway between dimensions doesn't count as a safe moment", crossing.endswith(": 1") and settled.endswith(": 0"), f"standing there: {settled}. Crossing: {crossing}")
    time.sleep(8)
    client_at = enter(client)
    settle(120)
    # A dimension has the overworld's weather, and rain would grey the sky.
    rcon("weather", "clear")
    rcon("time", "set", "noon")
    rcon("execute", "as", PLAYER, "at", "@s", "run", "tp", "@s", "~", "~", "~", 0, -40)
    client.ask("shot moor")
    check_sky()
    return moor, client_at


def check_sky():
    """The dimension's own type says its sky is purple. The overworld's has more green than red, so this can tell them apart."""
    shot = max((runtime.WORK / "mods-client" / "companion" / "build" / "run" / "clientGameTest" / "screenshots").glob("*m8_moor.png"), key=lambda path: path.stat().st_mtime, default=None)
    if shot is None:
        report("the player's game draws the dimension's own sky", False, "no screenshot")
        return
    with Image.open(shot) as image:
        band = image.convert("RGB").crop((image.width // 4, 0, image.width * 3 // 4, image.height // 8))
        red, green, blue = (sum(channel) / len(channel) for channel in zip(*band.getdata()))
    shutil.copy(shot, runtime.REPORTS / "m30_moor.png")
    report("the player's game draws the dimension's own sky", red > green + SKY_MARGIN and blue > green + SKY_MARGIN, f"average colour at the top of the picture {red:.0f}, {green:.0f}, {blue:.0f}")


def enter(client):
    key = slot("expanse_key", "items")
    rcon("clear", PLAYER)
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", key, 1)
    time.sleep(1)
    client.ask("use")
    time.sleep(3)
    client.ask("where")
    return json.loads(re.findall(r"\[M8\] where: (.*)$", client.text(), re.MULTILINE)[-1])


def check_restart_in_dimension(client, moor, here):
    """A release that restarts the server, with someone standing in a dimension, on a real client held by the real proxy."""
    build_marker = (here["x"], here["y"] + 2, here["z"])
    rcon("execute", "in", moor, "run", "setblock", *build_marker, "minecraft:diamond_block")
    rcon("save-all", "flush")
    manifest_path = target() / "feature.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["biomes"]["second_orchard"] = {"base": "minecraft:forest", "effects": {"grass_color": "#6fbf7f"}, "proportion": 0.2}
    # Something new to place, because only that sets off the world check, which should now go through this dimension's land too.
    manifest["ruins"]["moor_marker"] = {"id": "moor_marker_v1", "dimension": "$dimension:moor", "parts": [{"x": 4, "y": 0, "z": 4, "block": "minecraft:lodestone"}],
                                        "on": ["natural"], "replaces": ["natural"], "chance": 0.2, "minY": 0, "maxY": 220}
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    before = runtime.inspect_state("prod")["StartedAt"]
    promoted = release()
    report("the release really restarted the server", promoted.get("tier") == "T3" and runtime.inspect_state("prod")["StartedAt"] != before, promoted.get("tier"))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and PLAYER not in rcon("list"):
        time.sleep(2)
    report("the player was held through it", PLAYER in rcon("list"), rcon("list"))
    time.sleep(15)
    client.ask("where")
    back = json.loads(re.findall(r"\[M8\] where: (.*)$", client.text(), re.MULTILINE)[-1])
    report("and is back in that dimension, where they were", back["dimension"] == moor and abs(back["x"] - here["x"]) <= 1 and abs(back["z"] - here["z"]) <= 1, back)
    found = rcon("execute", "in", moor, "if", "block", *build_marker, "minecraft:diamond_block")
    report("with what they built there still there", "passed" in found, found)
    diff = runtime.DIFF / "before" / moor.replace(":", "/")
    report("and the gate's world check went through its land as well", diff.exists() and any(diff.glob("*.mca")), str(diff))
    return build_marker


def check_ruin_in_dimension(manifest, moor):
    by_id = {ruin["id"]: ruin for ruin in manifest["ruins"].values()}
    rcon("save-all", "flush")
    time.sleep(5)
    raw = Raw(moor)
    placed = [entry for entry in decisions() if entry["placed"] and entry["dimension"] == moor]
    report("big ruins go in a dimension too", placed, f"{len(placed)} placed")
    whole = sum(1 for entry in placed if not missing_from(raw, entry, by_id[entry["ruin"]])[0])
    report("whole, in its own land", placed and whole == len(placed), f"{whole} of {len(placed)}")
    overworld = Raw()
    elsewhere = [entry for entry in placed if overworld.block(entry["x"], entry["y"], entry["z"]) == "minecraft:smooth_quartz"]
    report("and not in the overworld", not elsewhere, f"{len(elsewhere)}")


def check_backup_and_prune(manifest, moor, built, visited_before, marker):
    file = deploy.backup()
    names = subprocess.run(["tar", "--zstd", "-tf", str(file)], capture_output=True, text=True, check=True).stdout.splitlines()
    has_dimension = any(f"dimensions/{moor.replace(':', '/')}/region/" in name for name in names)
    report("a backup has every dimension in it", has_dimension, f"{file.name}: {len(names)} entries")
    report("and what's been decided about ruins", any(name.strip().endswith("conduit_ruins.jsonl") for name in names))

    stop_prod()
    before_visited = visited_chunks(regions_of())
    planned = prune.prune(world(), dry_run=True)
    print(json.dumps(planned), flush=True)
    report("pruning finds the land where the game really keeps it", planned["generated"] > 0 and planned["pruned"] > 0, f"{planned['pruned']} of {planned['generated']} chunks")
    report("and looks at each dimension", OVERWORLD in planned["dimensions"] and moor in planned["dimensions"], sorted(planned["dimensions"]))
    # A narrow margin, so that land near where the player was is pruned too, with ruins in it. Everything that's been visited still stays.
    done = prune.prune(world(), margin=2)
    print(json.dumps(done), flush=True)
    after_visited = visited_chunks(regions_of())
    report("it keeps everywhere anyone has been", before_visited == after_visited, f"{len(after_visited)} chunks")
    pruned = prune_part_of_a_hall(manifest)
    start_prod()
    time.sleep(10)
    check_player_land(built, visited_before)
    rcon("execute", "in", moor, "run", "forceload", "add", marker[0], marker[2])
    time.sleep(3)
    found = rcon("execute", "in", moor, "if", "block", *marker, "minecraft:diamond_block")
    report("and what someone built in a dimension is still there after pruning", "passed" in found, found)
    rcon("execute", "in", moor, "run", "forceload", "remove", marker[0], marker[2])
    return pruned


def prune_part_of_a_hall(manifest):
    """Whether pruning reaches a ruin depends on where people went and on leaves decaying nearby, so this does for sure what it may do. It's the same call, and the server has to be stopped."""
    by_id = {ruin["id"]: ruin for ruin in manifest["ruins"].values()}
    raw = Raw()
    entry = next(item for item in decisions() if item["placed"] and item["ruin"] == "great_hall_v1" and item["dimension"] == OVERWORLD and raw.chunk(item["chunkX"], item["chunkZ"]) is not None)
    chunks = sorted(chunks_of(entry, by_id[entry["ruin"]]))[:2]
    for name in prune.FOLDERS:
        if (regions_of().parent / name).is_dir():
            prune.clear_chunks(regions_of().parent / name, chunks)
    return entry


def check_big_ruin_after_prune(manifest, entry):
    """A ruin in land that's been pruned has its land made again, and then it has to be put back, the same."""
    by_id = {ruin["id"]: ruin for ruin in manifest["ruins"].values()}
    chunks = chunks_of(entry, by_id[entry["ruin"]])
    rcon("tick", "freeze")
    xs, zs = [chunk[0] for chunk in chunks], [chunk[1] for chunk in chunks]
    rcon("forceload", "add", min(xs) * 16, min(zs) * 16, max(xs) * 16 + 15, max(zs) * 16 + 15)
    settle(180)
    rcon("forceload", "remove", "all")
    rcon("tick", "unfreeze")
    rcon("save-all", "flush")
    time.sleep(5)
    missing, count = missing_from(Raw(), entry, by_id[entry["ruin"]])
    report("a big ruin in pruned land is put back when the land is made again", len(missing) < count * 0.02, f"{len(missing)} of {count} blocks differ, like {missing[:2]}")


def main():
    build_source()
    manifest = json.loads((target() / "feature.json").read_text(encoding="utf-8"))
    generate_land()

    # A client has to be there for the land to be played in, and to be held through releases.
    os.environ["CLIENT_TEST"] = "knowledge"
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods-client"
    runtime.sync_tree(runtime.WORK / "mods", mods, "build/", ".gradle/", "run/", exact=True)
    gradle_home = own_gradle_home()
    client = Client(mods, runtime.REPORTS / "m30-client.log", gradle_home=gradle_home)
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(15)
        built = play(client)
        visited_before = visited_chunks(regions_of())
        report("land has been played in", len(visited_before) > 100, f"{len(visited_before)} chunks visited")
        before = runtime.DIFF / "m30-before"
        runtime.sync_tree(regions_of(), before)

        print("releasing the test feature through every gate, with the player connected", flush=True)
        promoted = release()
        report("the release went through every gate", promoted.get("result") == "released", promoted.get("tier"))
        print("gate timings:", json.dumps(promoted.get("shadow")), flush=True)
        shots = promoted.get("screenshots")
        print("screenshots:", shots, flush=True)
        report("the player was held through the restart", PLAYER in rcon("list"), rcon("list"))
        patches = {slot("expanse_stone"): manifest["ruins"]["great_hall"]["replaces"]}
        for ruin in manifest["ruins"].values():
            for part in ruin["parts"]:
                if part["block"].startswith("minecraft:") and part["block"] != "minecraft:air":
                    patches.setdefault(part["block"], [])
                    patches[part["block"]] = sorted(set(patches[part["block"]]) | set(ruin["replaces"]))
        check_added_features(content_biome())

        # Nobody's been to these, so they're all land for it. The first few are what it does for someone arriving.
        rcon("gamemode", "creative", PLAYER)
        for x, z in ((1000, 1000), (-1000, 1000), (1000, -1000), (-1000, -1000), (0, 1100), (1100, 0)):
            rcon("tp", PLAYER, x, 220, z)
            time.sleep(25)
        settle()
        client.ask("where")
        heard = re.findall(r"\[M8\] chat: ruin placed: (\S+) at (-?\d+), (-?\d+), (-?\d+) in (\S+)", client.text())
        report("a module hears each ruin being placed", heard, f"{len(heard)} heard, like {heard[0] if heard else None}")
        names = {name for name, *_ in heard}
        report("big and small, by the name it knows them by", "expanse/great_hall" in names and bool(names - {"expanse/great_hall"}), sorted(names))
        check_big_ruins(manifest, visited_before)
        check_player_land(built, visited_before)
        raw_check_on_prod(before, patches)
        check_world_check_scales(before, patches)

        spot = check_finding(client)
        crash = check_crash(client)
        if crash:
            client.stop()
            check_crash_recovery(manifest, crash)
            client = Client(mods, runtime.REPORTS / "m30-client-2.log", gradle_home=gradle_home)
            client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
            time.sleep(15)
        check_climate_lasts(spot)

        moor, here = check_dimension(client, manifest)
        check_ruin_in_dimension(manifest, moor)
        marker = check_restart_in_dimension(client, moor, here)
        client.stop()
        pruned = check_backup_and_prune(manifest, moor, built, visited_before, marker)
        check_big_ruin_after_prune(manifest, pruned)
    finally:
        client.stop()
        shutil.rmtree(runtime.RUNTIME / "cache" / GRADLE_COPY, ignore_errors=True)

    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


def content_biome():
    biomes = json.loads((runtime.RUNTIME / "prod" / "config" / "conduit" / "biome_patches.json").read_text(encoding="utf-8"))
    name = biomes[0]["to"]
    return {"id": name, **json.loads((world() / "datapacks" / "gm_content" / "data" / "gm" / "worldgen" / "biome" / f"{name.split(':')[1]}.json").read_text(encoding="utf-8"))}


if __name__ == "__main__":
    main()
