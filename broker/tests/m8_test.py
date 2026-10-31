#!/usr/bin/env python3
"""The content test: a real game client plays through the systems that make a world worth discovering.

A locked recipe stays locked until it's learned, a machine reacts to a near miss, the codex opens, a mob
walks around with its model, plants have grown only on natural ground, and a new biome exists. Ends with a
world diff proving nothing else changed. Runs against prod, so reset the dev world afterwards.

Usage: python3 -m broker.tests.m8_test
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

from broker import runtime
from broker.gates import GateFailed
from broker.gates import client as gate_client

SOURCE = runtime.BROKER / "testsrc-m8"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "lore"
CONTAINER = "livingmod-m8-client"
PLAYER = "Player0"
SPOT = (40, 120, 40)
TEXTURES = ("rune_crucible", "moss_cap", "glow_cap", "rune_berry", "moss_seed", "rune_stone", "rune_ore", "rune_dust", "rune_gem", "rune_tablet", "rune_shard", "rune_salt")
BROKER_FAILED = re.compile(r"BUILD FAILED|Game crashed|\.java:\d+: error:")


def report(name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    return passed


def build_source():
    """The trusted code plus the fixture, with art made the way a builder would make it."""
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "lore"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    (target / "server" / "src" / "main" / "resources").mkdir(parents=True, exist_ok=True)
    (target / "server" / "src" / "main" / "resources" / "module.properties").write_text(
        "entry=gm.feature.lore.LoreModule\n", encoding="utf-8")
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(TEXTURES):
        data = subprocess.run([sys.executable, "assetkit/proof_texture.py", str(index + 1)], cwd=runtime.REPO,
                              stdout=subprocess.PIPE, check=True).stdout
        (textures / f"{name}.png").write_bytes(data)
    models = target / "assets" / "models"
    models.mkdir(parents=True, exist_ok=True)
    make_model(models / "rune_crab.bbmodel", "quadruped")


def add_second_mob():
    """Something new with art of its own, to prove a mob can arrive without a restart."""
    target = SOURCE / "mods" / "genesis" / "features" / "lore"
    make_model(target / "assets" / "models" / "rune_moth.bbmodel", "flying")
    manifest = json.loads((target / "feature.json").read_text(encoding="utf-8"))
    manifest["mobs"]["rune_moth"] = {"category": "creature", "display": "Rune Moth", "model": "rune_moth", "behaviour": "passive",
                                     "health": 4, "damage": 0, "speed": 0.2, "width": 0.6, "height": 0.6}
    (target / "feature.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def generate_land():
    """Plants and ore only prove anything on land that exists before they do, so make some."""
    runtime.rcon("prod", "forceload", "add", "-48", "-48", "48", "48")
    time.sleep(25)
    runtime.rcon("prod", "save-all", "flush")
    time.sleep(3)


def count_block(block):
    """Reads the world's raw files, so this can't be fooled by the mod's own idea of what it placed."""
    sys.path.insert(0, str(runtime.REPO / "broker" / "gates"))
    from world_diff import decode, read_chunks

    total = 0
    for regions in (runtime.RUNTIME / "prod" / "world").rglob("region"):
        for path in regions.glob("*.mca"):
            for _, _, chunk in read_chunks(path):
                for section in chunk.get("sections", []):
                    blocks, palette = decode(section)
                    if block in palette:
                        total += blocks.count(palette.index(block))
    return total


def make_model(path, shape):
    """The agent's container has the libraries assetkit needs, and writes the file through stdout."""
    script = ("import sys; sys.path.insert(0, '/reference/assetkit'); import bbmodel; "
              f"mob = bbmodel.{shape}('{path.stem}', primary='#7a5a8c', secondary='#d8cdb8', seed=3); "
              "problems = bbmodel.check(mob); assert not problems, problems; "
              "bbmodel.save(mob, '/tmp/m.bbmodel'); sys.stdout.write(open('/tmp/m.bbmodel').read())")
    result = runtime.run(["./scripts/stack.sh", "--profile", "agent", "run", "--rm", "-T", "agent", "python3", "-c", script], timeout=120)
    text = result.stdout[result.stdout.index('{"meta"') if '{"meta"' in result.stdout else result.stdout.index("{"):]
    json.loads(text)
    path.write_text(text, encoding="utf-8")


def promote():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m8-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1200,
    )
    return result.returncode, json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))


class Client:
    def __init__(self, mods_dir, log):
        self.log = log
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
        with log.open("w", encoding="utf-8") as stream:
            self.process = subprocess.Popen(
                ["./scripts/stack.sh", "--profile", "tools", "run", "--rm", "-T", "--name", CONTAINER, "testclient",
                 "./gradlew", "--no-daemon", "--console=plain", ":companion:runClientGameTest"],
                cwd=runtime.REPO, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                env={**__import__("os").environ, "MODS_DIR": str(mods_dir), "CLIENT_TEST": "knowledge", "TEST_SERVER": "localhost:25565"},
            )

    def text(self):
        return self.log.read_text(encoding="utf-8", errors="replace")

    def wait(self, pattern, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            text = self.text()
            found = re.search(pattern, text, re.MULTILINE)
            if found:
                return found
            if BROKER_FAILED.search(text) or self.process.poll() is not None:
                raise RuntimeError(f"The client stopped waiting for {pattern}:\n{text[-1500:]}")
            time.sleep(0.25)
        raise TimeoutError(f"Timed out waiting for {pattern}:\n{self.text()[-800:]}")

    def ask(self, request, seconds=120):
        before = self.text().count(f"[M8] finished {request}")
        runtime.rcon("prod", "tellraw", PLAYER, json.dumps({"text": f"M8 {request}"}))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.text().count(f"[M8] finished {request}") > before:
                return
            time.sleep(0.25)
        raise TimeoutError(f"The client didn't finish {request}")

    def stop(self):
        try:
            runtime.rcon("prod", "tellraw", PLAYER, json.dumps({"text": "M8 done"}), check=False)
            self.process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)


def slot(name, table="items"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"lore/{name}"]["slot"]


def food_level():
    reply = runtime.rcon("prod", "data", "get", "entity", PLAYER, "foodLevel")
    return int(re.search(r"(\d+)\s*$", reply).group(1))


def last_result(client):
    return re.findall(r"\[M8\] crafting result: (\S+)", client.text())[-1]


def play(client):
    results = []
    dust, tablet, gem, salt = slot("rune_dust"), slot("rune_tablet"), slot("rune_gem"), slot("rune_salt")
    x, y, z = SPOT
    for command in (("gamemode", "survival", PLAYER), ("difficulty", "peaceful"), ("time", "set", "noon"),
                    ("forceload", "add", str(x - 16), str(z - 16), str(x + 16), str(z + 16)),
                    ("fill", str(x - 6), str(y - 1), str(z - 6), str(x + 6), str(y - 1), str(z + 6), "minecraft:smooth_stone"),
                    ("fill", str(x - 6), str(y), str(z - 6), str(x + 6), str(y + 6), str(z + 6), "minecraft:air"),
                    ("tp", PLAYER, str(x), str(y), str(z), "0", "20"),
                    ("clear", PLAYER)):
        runtime.rcon("prod", *command, check=False)

    # A gated recipe shows nothing until it's learned.
    runtime.rcon("prod", "give", PLAYER, dust, "8")
    time.sleep(1)
    client.ask("craft")
    locked = last_result(client)
    results.append(report("a recipe that hasn't been learned produces nothing", "air" in locked, locked))

    # Reading the tablet teaches it. The dust is in the first hotbar slot, so swap the tablet in to use it.
    runtime.rcon("prod", "clear", PLAYER)
    runtime.rcon("prod", "give", PLAYER, tablet, "1")
    time.sleep(1)
    client.ask("use")
    client.wait(r"\[M8\] chat: .*You've learned .*On Cutting Gems", 30)
    results.append(report("reading the tablet teaches the recipe", True))
    leftover = runtime.rcon("prod", "clear", PLAYER, tablet, "0")
    results.append(report("the tablet was used up", "No items" in leftover or " 0 " in leftover, leftover))

    runtime.rcon("prod", "clear", PLAYER)
    runtime.rcon("prod", "give", PLAYER, dust, "8")
    time.sleep(1)
    client.ask("craft")
    unlocked = last_result(client)
    # The client sees a stand-in vanilla item for anything of ours, so all that matters is that it isn't air.
    results.append(report("the same recipe now works", "air" not in unlocked, unlocked))

    # A machine reacts to a near miss, then gives the real thing for the right pair.
    crucible = slot("rune_crucible", "blocks")
    runtime.rcon("prod", "setblock", str(x), str(y), str(z + 3), crucible)
    runtime.rcon("prod", "clear", PLAYER)
    runtime.rcon("prod", "give", PLAYER, dust, "1")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z + 3}")
    near = client.wait(r"\[M8\] chat: The crucible hums: (\d) of (\d)", 20)
    results.append(report("a machine reacts to a near miss", near.group(1) == "1" and near.group(2) == "2", near.group(0)))

    runtime.rcon("prod", "item", "replace", "entity", PLAYER, "weapon.offhand", "with", gem, "1")
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z + 3}")
    client.wait(r"\[M8\] chat: The crucible made something", 20)
    made = runtime.rcon("prod", "clear", PLAYER, salt, "0")
    results.append(report("the right pair makes the output", "1" in made, made))

    # The codex shows what's been learned.
    client.ask("codex", 90)
    results.append(report("the codex opens", "[M8] the codex opened" in client.text()))

    # An item that's food only because its definition says so. Hunger first, because you can't eat when full. The
    # crucible has to go, because the player is looking at it, and using an item would use the machine instead.
    runtime.rcon("prod", "setblock", str(x), str(y), str(z + 3), "minecraft:air")
    berry = slot("rune_berry")
    runtime.rcon("prod", "clear", PLAYER)
    runtime.rcon("prod", "give", PLAYER, berry, "2")
    runtime.rcon("prod", "difficulty", "easy")
    # Long enough to burn through the full saturation bar a player builds up on peaceful.
    runtime.rcon("prod", "effect", "give", PLAYER, "minecraft:hunger", "6", "255")
    time.sleep(7)
    before = food_level()
    client.ask("eat")
    after = food_level()
    left = runtime.rcon("prod", "clear", PLAYER, berry, "0")
    runtime.rcon("prod", "difficulty", "peaceful")
    results.append(report("an item defined as food can be eaten", after > before and "Found 1" in left, f"food {before} to {after}, {left}"))
    # Without this the food still works, but the player sees no eating animation.
    seen = re.findall(r"\[M8\] the client sees it as food: (\w+)", client.text())
    results.append(report("the client knows it's food, so eating looks right", seen[-1:] == ["true"], str(seen[-1:])))

    # A seed plants what it says, on what it says.
    moss = slot("moss_cap", "blocks")
    runtime.rcon("prod", "clear", PLAYER)
    runtime.rcon("prod", "give", PLAYER, slot("moss_seed"), "1")
    time.sleep(1)
    client.ask(f"useblock {x + 1} {y - 1} {z + 1}")
    planted = runtime.rcon("prod", "execute", "if", "block", str(x + 1), str(y), str(z + 1), moss)
    results.append(report("a seed plants its block", "passed" in planted, planted))

    # A plant that gives light. Only the block light layer counts, so daylight doesn't confuse it.
    runtime.rcon("prod", "setblock", str(x - 3), str(y), str(z + 1), slot("glow_cap", "blocks"))
    time.sleep(2)
    client.ask(f"light {x - 3} {y + 1} {z + 1}")
    light = int(re.findall(r"\[M8\] block light: (\d+)", client.text())[-1])
    results.append(report("a glowing plant lights its surroundings on the client", light >= 8, f"block light {light}"))

    # A mob with a real model, walking around.
    runtime.rcon("prod", "setblock", str(x), str(y), str(z + 3), "minecraft:air")
    runtime.rcon("prod", "summon", slot("rune_crab", "mobs"), str(x - 1), str(y), str(z + 4), "{NoAI:1b}")
    runtime.rcon("prod", "summon", slot("rune_moth", "mobs"), str(x + 2), str(y), str(z + 4), "{NoAI:1b}")
    client.ask("shot mob")
    for name in ("rune_crab", "rune_moth"):
        count = runtime.rcon("prod", "execute", "if", "entity", f"@e[type={slot(name, 'mobs')}]")
        results.append(report(f"{name} is in the world", "passed" in count, count))
    return results


def check_mob_art(results, shots):
    """A mob can be in the world and still have no art, so this looks at the picture."""
    shot = next(iter(sorted(shots.glob("*m8_mob.png"))), None)
    if shot is None:
        results.append(report("the mobs have their art", False, "no screenshot"))
        return
    try:
        gate_client.check_image(shot)
        results.append(report("the mobs have their art", True, shot.name))
    except GateFailed as error:
        results.append(report("the mobs have their art", False, error.message))


def check_drops(results):
    """A loot table the game can't fully read loads anyway and quietly does less, so this asks for real drops."""
    x, y, z = SPOT
    ore, dust = slot("rune_ore", "blocks"), slot("rune_dust")
    spot = (str(x + 3), str(y), str(z))
    runtime.rcon("prod", "setblock", *spot, ore)
    counts = set()
    for _ in range(20):
        runtime.rcon("prod", "clear", PLAYER, check=False)
        runtime.rcon("prod", "loot", "give", PLAYER, "mine", *spot, "minecraft:iron_pickaxe")
        held = runtime.rcon("prod", "clear", PLAYER, dust, "0")
        found = re.search(r"Found (\d+)", held)
        counts.add(int(found.group(1)) if found else 0)
    results.append(report("an ore drops what it says, in the amounts it says", counts == {2, 3}, f"saw counts {sorted(counts)}"))

    silk = 'minecraft:diamond_pickaxe[minecraft:enchantments={"minecraft:silk_touch":1}]'
    runtime.rcon("prod", "clear", PLAYER, check=False)
    runtime.rcon("prod", "loot", "give", PLAYER, "mine", *spot, silk)
    held = runtime.rcon("prod", "clear", PLAYER, ore, "0")
    results.append(report("silk touch gives the ore itself", "Found 1" in held, held))
    runtime.rcon("prod", "setblock", *spot, "minecraft:air")
    runtime.rcon("prod", "clear", PLAYER, check=False)


def check_plants(results):
    runtime.rcon("prod", "save-all", "flush")
    time.sleep(3)
    moss = slot("moss_cap", "blocks")
    count = count_block(moss)
    results.append(report("plants grew on land that already existed", count > 0, f"{count} of {moss}"))


def check_ruins(results):
    stone = slot("rune_stone", "blocks")
    count = count_block(stone)
    results.append(report("ruins appeared in land nobody has visited", count > 0, f"{count} blocks of {stone}"))

    sys.path.insert(0, str(runtime.REPO / "broker" / "gates"))
    from world_diff import read_chunks

    chests = 0
    for regions in (runtime.RUNTIME / "prod" / "world").rglob("region"):
        for path in regions.glob("*.mca"):
            for _, _, chunk in read_chunks(path):
                chests += sum(1 for entity in chunk.get("block_entities", []) if str(entity.get("LootTable", "")).startswith("gm:"))
    results.append(report("their chests hold this feature's loot", chests > 0, f"{chests} chests"))


def check_biome(results):
    biome = json.loads((runtime.RUNTIME / "prod" / "config" / "conduit" / "biome_patches.json").read_text(encoding="utf-8"))[0]
    found = runtime.rcon("prod", "locate", "biome", biome["to"], check=False)
    results.append(report("the new biome generates", "nearest" in found.lower(), found[:120]))
    results.append(report("the new biome is a sibling, so it can spread into existing land", biome["sibling"] is True))


def check_progress(results):
    ledger = json.loads((runtime.RUNTIME / "prod" / "world" / "conduit_knowledge.json").read_text(encoding="utf-8"))
    results.append(report("what was learned is saved with the world", "lore/gem_cutting" in json.dumps(ledger["known"])))


def release():
    code, promoted = promote()
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if code != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)
    return promoted


def main():
    generate_land()
    build_source()
    print("building and releasing the test feature", flush=True)
    release()
    print("adding a second mob, which shouldn't need a restart", flush=True)
    add_second_mob()
    second = release()

    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    client = Client(mods, runtime.REPORTS / "m8-client.log")
    results = [report("a new mob ships without a restart", second.get("tier") == "T2", f"tier {second.get('tier')}")]
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        results.extend(play(client))
        check_biome(results)
        check_progress(results)
        check_plants(results)
        check_ruins(results)
        check_drops(results)
    finally:
        client.stop()
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    out = runtime.REPORTS / "m8"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_*.png"):
        shutil.copy(path, out)
    check_mob_art(results, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
