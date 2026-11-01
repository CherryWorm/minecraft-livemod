#!/usr/bin/env python3
"""Things alive that aren't mobs, on a real client: a projectile going through a release with its own damage and hit callback, a boat faster than
any real boat can go, a car that follows its rider's look, something that flies, a prop and beams, and then a crowd of them. Runs against prod, so
reset the dev world afterwards.

Usage: python3 -m broker.tests.m28_test [play_boat play_rover ...]    naming parts goes over only those, on a world that already has the rest
To also check that a world from before these slots survives getting them, run this file with --before on a tree with that older engine, on the same
stack, and then run it normally on this one.
"""
import json
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import time

from PIL import Image, ImageChops

from broker import runtime
from broker.gates import client as gate_client
from broker.tests.m8_test import Client
from orchestrator import progression

SOURCE = runtime.BROKER / "testsrc-m28"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "rides"
OUT = runtime.REPORTS / "m28"
PLAYER = "Player0"
SPOT = (40, 120, 40)
POOL = 110
CROWD_VEHICLES = 40
CROWD_PROPS = 200
BOAT_SPEED = 14
ROVER_SPEED = 12
VANILLA_BOAT_SPEED = 8
# A tick on a busy computer isn't always a twentieth of a second, so speeds get some room.
SPEED_ROOM = 0.8
MOST_FLYING = 300
TICKS_PER_SECOND = 20
# 180 blocks and about 47, at 16 to a piece.
TALL_BEAM_PIECES = 12
SLANTED_BEAM_PIECES = 3
BEAM_PIECES = TALL_BEAM_PIECES + SLANTED_BEAM_PIECES
ELDER_SPOT = (18, 120, 40)
ELDER_UUID_ARRAY = "[I;1,2,3,4]"
ELDER_UUID = "00000001-0000-0002-0000-000300000004"
MARKER = runtime.BROKER / "m28-before.json"
WORLD = {"goal": "See how far things go", "nodes": {
    "first_steps": {"stage": "early", "name": "First steps", "requires": [], "opens_with": "", "holds": "Rides"},
    "machines": {"stage": "mid", "name": "Machines", "requires": ["first_steps"], "opens_with": "rides", "holds": "Nothing yet"},
    "the_end": {"stage": "end", "name": "The end", "requires": ["machines"], "opens_with": "machines", "holds": "Nothing yet"},
}}


def report(results, name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    results.append(passed)
    return passed


def rcon(*command):
    return runtime.rcon("prod", *command, check=False)


def write_elder(features):
    """A plain mob, which is what's already in released worlds. It needs nothing the new slots brought with them, so an older engine can have it too."""
    from assetkit import bbmodel

    target = features / "elder"
    (target / "assets" / "models").mkdir(parents=True)
    bbmodel.save(bbmodel.quadruped("m28walker", primary="#7a5a8c", secondary="#d8cdb8", seed=3), target / "assets" / "models" / "walker.bbmodel")
    (target / "feature.json").write_text(json.dumps({"id": "elder", "node": "first_steps", "summary": "A mob from before there were any other slots.", "mobs": {
        "walker": {"category": "creature", "display": "Walker", "model": "walker", "behaviour": "passive", "health": 12, "damage": 0, "speed": 0.2, "width": 0.9, "height": 0.9}}}), encoding="utf-8")


def build_source(with_rides=True):
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    features = SOURCE / "mods" / "genesis" / "features"
    if features.exists():
        shutil.rmtree(features)
    features.mkdir(parents=True)
    write_elder(features)
    (SOURCE / "bible").mkdir(exist_ok=True)
    progression.save(SOURCE / "bible" / "progression.json", WORLD)
    if not with_rides:
        return
    target = features / "rides"
    shutil.copytree(FIXTURE, target, ignore=shutil.ignore_patterns("models.py", "__pycache__"))
    subprocess.run([sys.executable, str(FIXTURE / "models.py"), str(target / "assets" / "models")], cwd=runtime.REPO, check=True,
                   env={**__import__("os").environ, "PYTHONPATH": str(runtime.REPO)})
    # Only the models go in. The pictures of them are for looking at.
    OUT.mkdir(parents=True, exist_ok=True)
    for preview in (target / "assets" / "models").glob("*.png"):
        shutil.move(preview, OUT / f"model_{preview.name}")
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True)
    for index, name in enumerate(("wand", "kit")):
        data = subprocess.run([sys.executable, "assetkit/proof_texture.py", str(index + 5)], cwd=runtime.REPO, stdout=subprocess.PIPE, check=True).stdout
        (textures / f"{name}.png").write_bytes(data)


def promote(*flags):
    started = time.monotonic()
    # A crash leaves the last answer where this one should be, and that would read as this one's.
    runtime.LAST_REPORT.unlink(missing_ok=True)
    done = subprocess.run([sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m28-{int(time.time())}", *flags],
                          cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1500)
    if not runtime.LAST_REPORT.exists():
        raise RuntimeError(f"The release stopped with no answer:\n{done.stderr[-2500:]}")
    answer = json.loads(runtime.LAST_REPORT.read_text(encoding="utf-8"))
    answer["seconds"] = round(time.monotonic() - started, 1)
    return answer


def ledger(table):
    return json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))[table]


def slot(table, name):
    return "gm:" + ledger(table)[f"rides/{name}"]["slot"]


def collect_shots():
    shots = runtime.WORK / "mods" / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    OUT.mkdir(parents=True, exist_ok=True)
    found = {}
    for path in sorted(shots.glob("*m8_*.png")):
        name = path.stem.split("m8_", 1)[1]
        target = OUT / f"{name}.png"
        shutil.copy(path, target)
        found[name] = target
    return found


def arena():
    """A stone floor, a long pool, and a step to drive up."""
    x, y, z = SPOT
    for command in (("difficulty", "peaceful"), ("gamerule", "advance_time", "false"), ("time", "set", "noon"), ("weather", "clear"),
                    ("gamerule", "mob_griefing", "true"), ("gamerule", "projectiles_can_break_blocks", "true"),
                    ("forceload", "add", str(x - 40), str(z - 40), str(x + POOL + 40), str(z + 40)),
                    ("fill", str(x - 16), str(y - 2), str(z - 24), str(x + 16), str(y - 1), str(z + 24), "minecraft:smooth_stone"),
                    ("fill", str(x - 16), str(y), str(z - 24), str(x + 16), str(y + 20), str(z + 24), "minecraft:air"),
                    # The pool runs east from here, and it's deep enough for a hull to float clear of its bottom.
                    ("fill", str(x + 17), str(y - 3), str(z - 6), str(x + POOL), str(y - 2), str(z + 6), "minecraft:smooth_stone"),
                    ("fill", str(x + 17), str(y - 1), str(z - 6), str(x + POOL), str(y - 1), str(z + 6), "minecraft:water"),
                    ("fill", str(x + 17), str(y), str(z - 6), str(x + POOL), str(y + 12), str(z + 6), "minecraft:air"),
                    ("clear", PLAYER)):
        rcon(*command)
    # Only once there's a floor under them, or this kills them.
    rcon("tp", PLAYER, str(x), str(y), str(z))
    rcon("gamemode", "survival", PLAYER)


def stand(x_offset, z_offset, yaw=0, pitch=0):
    x, y, z = SPOT
    rcon("tp", PLAYER, str(x + x_offset), str(y), str(z + z_offset), str(yaw), str(pitch))


def number(text):
    """The last number in what a command said."""
    found = re.findall(r"(-?\d+(?:\.\d+)?)[a-zA-Z]?", text)
    return float(found[-1]) if found else None


def position(selector):
    reply = rcon("data", "get", "entity", selector, "Pos")
    values = re.findall(r"(-?\d+\.\d+)d", reply)
    return tuple(float(value) for value in values[:3]) if len(values) >= 3 else None


def yaw_of(selector):
    return number(rcon("data", "get", "entity", selector, "Rotation[0]"))


def distance(first, second):
    return sum((a - b) ** 2 for a, b in zip(first, second)) ** 0.5


def has(*selector):
    return "passed" in rcon("execute", "if", *selector).lower()


def wait_after(client, mark, pattern, seconds=15):
    """Like client.wait, but only for what's been said since then, because the same thing has often been said earlier on."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = re.search(pattern, client.text()[mark:], re.MULTILINE)
        if found:
            return found
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {pattern}")


def rode(client, before):
    """Where the client said its player was, tick by tick, since `before` lines of its log."""
    return [tuple(float(value) for value in line) for line in re.findall(r"\[M8\] rode: (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) yaw (-?[\d.]+)", client.text()[before:])]


def smoothness(steps):
    """How even a ride is on the client, tick by tick once it's up to speed: the largest step, and how far they spread around the usual one."""
    moved = [distance(first[:3], second[:3]) for first, second in zip(steps, steps[1:])]
    settled = moved[len(moved) // 2:]
    return statistics.median(settled), max(settled), statistics.pstdev(settled)


def server_speed(client, mark, name):
    """Its fastest blocks a second, from where its module says it is once a second of the server's own time. Going by a client's ticks would only
    measure how well that client keeps up, and a software-rendered one drawing water doesn't."""
    spots = [tuple(float(value) for value in spot) for spot in re.findall(rf"\[M8\] chat: RIDE {name} at (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)$", client.text()[mark:], re.MULTILINE)]
    return max((distance(first, second) for first, second in zip(spots, spots[1:])), default=0.0)


def play_projectile(results, client):
    x, y, z = SPOT
    arena()
    time.sleep(2)
    rcon("give", PLAYER, slot("items", "wand"))
    # Things a thrown snowball or a fireball could damage, right in its path, with the game's rules allowing it.
    z_target = z + 10
    rcon("summon", "minecraft:villager", str(x), str(y), str(z_target), "{NoAI:1b,PersistenceRequired:1b,Health:20f,Invulnerable:0b}")
    rcon("setblock", str(x + 3), str(y - 1), str(z_target), "minecraft:end_stone")
    rcon("setblock", str(x + 3), str(y), str(z_target), "minecraft:chorus_flower")
    rcon("setblock", str(x + 6), str(y), str(z_target), "minecraft:decorated_pot")
    rcon("setblock", str(x + 9), str(y), str(z_target), "minecraft:tnt")
    time.sleep(1)

    health = number(rcon("data", "get", "entity", f"@e[type=minecraft:villager,limit=1]", "Health"))
    stand(0, 2, yaw=0, pitch=5)
    time.sleep(1)
    mark = len(client.text())
    client.ask("use")
    wait_after(client, mark, r"chat: RIDE bolt fired for 5\.0")
    # At 12 blocks a second, it's still on its way when this is taken.
    client.ask("shotnow bolt_flying")
    time.sleep(1.5)
    found = wait_after(client, mark, r"chat: RIDE bolt hit (\S+) and (hurt it|did nothing), shot by (\S+)")
    report(results, "a projectile hits what it's aimed at, and its callback hears about it", found.group(1).endswith("villager") and found.group(2) == "hurt it" and found.group(3) == PLAYER, found.group(0)[:90])
    after = number(rcon("data", "get", "entity", "@e[type=minecraft:villager,limit=1]", "Health"))
    report(results, "and it does exactly the damage in its definition", after == health - 5, f"{health} to {after}")

    for index, (offset, block) in enumerate(((3, "minecraft:chorus_flower"), (6, "minecraft:decorated_pot"), (9, "minecraft:tnt"))):
        stand(offset, 2, yaw=0, pitch=5)
        time.sleep(1)
        before = client.text().count("chat: RIDE bolt hit block")
        client.ask("use")
        deadline = time.monotonic() + 8
        while client.text().count("chat: RIDE bolt hit block") == before and time.monotonic() < deadline:
            time.sleep(0.2)
        report(results, f"and {block} is still there after being hit", client.text().count("chat: RIDE bolt hit block") > before and has("block", str(x + offset), str(y), str(z_target), block))
    report(results, "and nothing got lit", not has("entity", "@e[type=minecraft:tnt]"))

    # Only around the targets, because the trees cut down for the arena drop saplings wherever their leaves decay.
    near = f"x={x + 5},y={y},z={z_target},distance=..12"
    report(results, "and it left nothing to pick up", not has("entity", f"@e[type=minecraft:item,{near}]"), rcon("data", "get", "entity", f"@e[type=minecraft:item,{near},limit=1]", "Item")[:120])
    report(results, "and every shot is gone", not has("entity", f"@e[type={slot('projectiles', 'bolt')}]"))
    rcon("kill", "@e[type=minecraft:villager]")

    # Holding the button down can't fire faster than its definition says, whatever a module asks for.
    stand(0, 0, yaw=180, pitch=0)
    time.sleep(1)
    mark = len(client.text())
    client.ask("hold 40")
    time.sleep(1)
    said = client.text()[mark:]
    fired, refused = said.count("[M8] chat: RIDE bolt fired"), said.count("[M8] chat: RIDE bolt refused")
    report(results, "and firing faster than its shots_per_second is refused", refused > 0 and 0 < fired <= 5, f"{fired} fired in two seconds, at 2 a second, and {refused} refused")
    rcon("kill", f"@e[type={slot('projectiles', 'bolt')}]")

    # Shot straight up, it comes down again, so gravity's real, and left alone with nothing to hit, it goes out by itself.
    stand(0, 0, yaw=0, pitch=-60)
    time.sleep(1)
    mark = len(client.text())
    client.ask("use")
    found = wait_after(client, mark, r"chat: RIDE bolt (expired|hit block)")
    print(found.group(0), flush=True)
    time.sleep(1)
    report(results, "and it comes down, or goes out by itself", not has("entity", f"@e[type={slot('projectiles', 'bolt')}]"))

    # A picture of it side on, hanging still, which is how a builder can tell what it looks like and which way it faces.
    rcon("kill", f"@e[type={slot('projectiles', 'bolt')}]")
    stand(-1.5, 3, yaw=-90, pitch=0)
    rcon("summon", slot("projectiles", "bolt"), str(x), str(y + 1.6), str(z + 3), "{Rotation:[0f,0f]}")
    client.ask("shot bolt_hanging")
    rcon("kill", f"@e[type={slot('projectiles', 'bolt')}]")
    for selector in ("minecraft:chorus_flower", "minecraft:decorated_pot", "minecraft:tnt", "minecraft:end_stone"):
        rcon("fill", str(x - 2), str(y - 1), str(z_target - 2), str(x + 12), str(y + 4), str(z_target + 2), "minecraft:air", "replace", selector)


def board(results, client, name, kit_name, stand_at, pitch):
    """Gets a kit, places it from the player's own hand, climbs in, and gives back how the client saw it."""
    rcon("clear", PLAYER)
    rcon("give", PLAYER, slot("items", kit_name))
    stand(*stand_at, pitch=pitch)
    time.sleep(1.5)
    client.ask("rightclick")
    time.sleep(1)
    kind = slot("vehicles", name)
    report(results, f"using its item places the {name}", has("entity", f"@e[type={kind}]") and not has("items", "entity", PLAYER, "weapon.mainhand", "*"), str(position(f"@e[type={kind},limit=1]")))
    client.ask("rightclick")
    found = client.wait(rf"chat: RIDE {name} boarded by {PLAYER}", 10)
    report(results, f"a {name} can be climbed into, and its module hears", bool(found))
    client.ask("riding")
    seen = re.findall(r"\[M8\] riding: .* riding (.+)$", client.text(), re.MULTILINE)[-1]
    report(results, "the client sees itself riding it", "nothing" not in seen, seen)
    # The same look that landed on it from outside has to go through it from inside, or a rider could never use or break anything.
    mark = len(client.text())
    client.ask("rightclick")
    found = wait_after(client, mark, r"\[M8\] using what the crosshair is on, which is a (\w+)")
    report(results, "and for its rider, its own hitbox isn't in the way", found.group(1) != "ENTITY", found.group(1))
    return kind, f"@e[type={kind},limit=1]"


def measure(client, name, selector, key, ticks):
    """Drives for a while. Gives back how far it went and its speed as the server has it, and then how even the ride was on the client, in blocks a client tick."""
    start = len(client.text())
    before = position(selector)
    client.ask(f"drive {key} {ticks}")
    after = position(selector)
    return distance(before, after), server_speed(client, start, name), *smoothness(rode(client, start))


def third_person(client, name):
    """From behind, with nothing in front of it, because a module saying where it is every second would otherwise fill the picture with chat."""
    client.ask("camera third")
    client.ask("hud off")
    client.ask(f"shot {name}")
    client.ask("hud on")
    client.ask("camera first")


def play_boat(results, client):
    kind, selector = board(results, client, "skiff", "skiff_kit", (16.5, 0, -90), 40)
    x, y, z = SPOT
    rcon("tp", selector, str(x + 22), str(y - 1), str(z), "-90", "0")
    time.sleep(2)
    settled = position(selector)
    report(results, "the boat floats on the water, with its hull partly under", settled is not None and y - 1 < settled[1] < y, str(settled))

    moved, speed, usual, largest, spread = measure(client, "skiff", selector, "forward", 60)
    client.ask("shot skiff_first_person")
    report(results, f"its speed is the {BOAT_SPEED} blocks a second it's set to, as a real boat's can't be", BOAT_SPEED * SPEED_ROOM <= speed <= BOAT_SPEED * 1.05, f"{speed:.2f} blocks a second on the server, against {VANILLA_BOAT_SPEED} for a vanilla boat")
    report(results, "and the ride is even on the client, with no hitches", largest <= usual * 2.2, f"a client tick's usual step {usual:.2f} blocks, largest {largest:.2f}, spread {spread:.2f}")
    print(f"boat: moved {moved:.1f} blocks", flush=True)

    before = yaw_of(selector)
    start_log = len(client.text())
    client.ask("drive right 20")
    turned = yaw_of(selector)
    steps = rode(client, start_log)
    camera = abs(steps[-1][3] - steps[0][3]) if steps else 0
    report(results, "the right key turns it", abs(turned - before) > 30, f"{before} to {turned}")
    report(results, "and turns the rider's view with it", camera > 30, f"the client's view turned {camera:.0f} degrees")

    client.ask("drive forward 10")
    third_person(client, "skiff_third_person")

    rcon("tp", selector, str(x + 5), str(y), str(z), "90", "0")
    time.sleep(1)
    _, on_land, *_ = measure(client, "skiff", selector, "forward", 60)
    report(results, "on land it only crawls", 0 < on_land <= BOAT_SPEED * 0.1 * 1.05, f"{on_land:.2f} blocks a second")

    mark = len(client.text())
    client.ask("sneak")
    wait_after(client, mark, rf"chat: RIDE skiff left by {PLAYER}")
    client.ask("unsneak")
    client.ask("riding")
    seen = re.findall(r"\[M8\] riding: .* riding (.+)$", client.text(), re.MULTILINE)[-1]
    report(results, "sneaking gets off, as with anything else", seen == "nothing", seen)

    rcon("kill", "@e[type=minecraft:item]")
    rcon("tp", selector, str(x), str(y), str(z + 3), "0", "0")
    stand(0, 0, yaw=0, pitch=25)
    time.sleep(1.5)
    client.ask("hit 10")
    time.sleep(1)
    gone = not has("entity", f"@e[type={kind}]")
    report(results, "hitting it breaks it", gone, client.text()[-200:].count("hurt by") and "hurt messages seen" or "")
    kit = slot("items", "skiff_kit")
    dropped = rcon("execute", "if", "entity", f"@e[type=minecraft:item,nbt={{Item:{{id:\"{kit}\"}}}}]")
    report(results, "and it gives back the item that placed it", "passed" in dropped.lower(), dropped[:80])
    rcon("kill", "@e[type=minecraft:item]")


def play_rover(results, client):
    x, y, z = SPOT
    _, selector = board(results, client, "rover", "rover_kit", (-8, -18, 0), 45)
    rcon("tp", selector, str(x - 8), str(y), str(z - 16), "0", "0")
    client.ask("look 0 0")
    time.sleep(1)
    _, speed, usual, largest, spread = measure(client, "rover", selector, "forward", 60)
    report(results, f"the car goes the {ROVER_SPEED} blocks a second it's set to", ROVER_SPEED * SPEED_ROOM <= speed <= ROVER_SPEED * 1.05, f"{speed:.2f} blocks a second on the server")
    report(results, "and the ride is even on the client, with no hitches", largest <= usual * 2.2, f"a client tick's usual step {usual:.2f} blocks, largest {largest:.2f}, spread {spread:.2f}")
    third_person(client, "rover_third_person")

    # It goes where its rider looks, whatever way it was facing.
    rcon("tp", selector, str(x - 8), str(y), str(z - 16), "0", "0")
    client.ask("look -90 0")
    time.sleep(0.5)
    before = position(selector)
    client.ask("drive forward 30")
    after = position(selector)
    report(results, "it goes where its rider looks", after[0] - before[0] > 3 and abs(after[2] - before[2]) < after[0] - before[0], f"from {before} to {after}")

    # Up a step, off the far side, and into a wall, which is what makes where it ends up not depend on how fast a client goes.
    rcon("fill", str(x + 2), str(y), str(z - 20), str(x + 8), str(y), str(z - 10), "minecraft:stone")
    rcon("fill", str(x + 14), str(y), str(z - 20), str(x + 14), str(y + 3), str(z - 10), "minecraft:stone")
    rcon("tp", selector, str(x - 4), str(y), str(z - 15), "-90", "0")
    client.ask("look -90 0")
    time.sleep(1)
    mark = len(client.text())
    client.ask("drive forward 70")
    heights = [step[1] for step in rode(client, mark)]
    report(results, "it drives up a step by itself", max(heights) - heights[0] > 0.99, f"up by {max(heights) - heights[0]:.2f}")
    report(results, "and comes down the far side", abs(heights[-1] - heights[0]) < 0.01, f"ends {heights[-1] - heights[0]:.2f} from where it started")
    end = position(selector)
    report(results, "and a wall stops it", end[0] < x + 14 and end[0] > x + 10, str(end))
    rcon("fill", str(x + 2), str(y), str(z - 20), str(x + 14), str(y + 3), str(z - 10), "minecraft:air")

    # A module can hold one back, but it has no way to make it go faster than the definition.
    mark = len(client.text())
    client.ask("sneak")
    wait_after(client, mark, rf"chat: RIDE rover left by {PLAYER}")
    client.ask("unsneak")
    rcon("give", PLAYER, "minecraft:slime_ball")
    rcon("tp", selector, str(x - 8), str(y), str(z - 16), "0", "0")
    stand(-8, -19, yaw=0, pitch=30)
    time.sleep(1)
    client.ask("rightclick")
    client.wait(r"chat: RIDE rover held to half speed", 10)
    report(results, "a module can hold it to half speed, and that stops the player getting in that time", not re.search(r"riding (?!nothing)", client.text()[-400:]))
    rcon("clear", PLAYER)
    mark = len(client.text())
    client.ask("rightclick")
    wait_after(client, mark, rf"chat: RIDE rover boarded by {PLAYER}")
    client.ask("look 0 0")
    _, slower, *_ = measure(client, "rover", selector, "forward", 60)
    report(results, "and then it goes that much slower", 0 < slower <= ROVER_SPEED * 0.5 * 1.05, f"{slower:.2f} blocks a second")


def play_rejoin(results, client):
    """Leaving the game on a vehicle and coming back has to put its rider back on it, with its hitbox still out of their way."""
    selector = f"@e[type={slot('vehicles', 'rover')},limit=1]"
    client.stop()
    # A new client clears out the last one's pictures.
    collect_shots()
    time.sleep(3)
    client = Client(runtime.WORK / "mods", runtime.REPORTS / "m28-rejoin-client.log")
    client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 300)
    time.sleep(5)
    client.ask("riding")
    seen = re.findall(r"\[M8\] riding: .* riding (.+)$", client.text(), re.MULTILINE)[-1]
    report(results, "someone who leaves on a vehicle comes back on it", "nothing" not in seen, seen)
    before = position(selector)
    client.ask("drive forward 20")
    after = position(selector)
    report(results, "and it still drives", before is not None and after is not None and distance(before, after) > 1, f"{before} to {after}")
    client.ask("sneak")
    client.wait(rf"chat: RIDE rover left by {PLAYER}", 10)
    client.ask("unsneak")
    return client


def play_air(results, client):
    x, y, z = SPOT
    kind = slot("vehicles", "glider")
    rcon("summon", kind, str(x), str(y), str(z - 18), "{Rotation:[0f,0f]}")
    selector = f"@e[type={kind},limit=1]"
    stand(0, -21, yaw=0, pitch=25)
    time.sleep(1.5)
    client.ask("rightclick")
    client.wait(rf"chat: RIDE glider boarded by {PLAYER}", 10)
    before = position(selector)
    client.ask("drive jump 40")
    high = position(selector)
    report(results, "the flying one goes up with the jump key", high[1] - before[1] > 5, f"{before[1]} to {high[1]}")
    time.sleep(2)
    held = position(selector)
    report(results, "and stays up there", abs(held[1] - high[1]) < 0.2, f"{high[1]} to {held[1]}")
    client.ask("look 0 0")
    client.ask("drive forward 30")
    third_person(client, "glider_third_person")
    client.ask("drive sprint 20")
    low = position(selector)
    report(results, "and comes down with the sprint key", low[1] < held[1] - 1, f"{held[1]} to {low[1]}")
    client.ask("sneak")
    client.wait(rf"chat: RIDE glider left by {PLAYER}", 10)
    client.ask("unsneak")
    time.sleep(3)
    sinking = position(selector)
    report(results, "and left alone, it sinks", sinking[1] < low[1], f"{low[1]} to {sinking[1]}")
    rcon("kill", selector)


def display_count(client):
    client.ask("entities")
    found = re.findall(r"\[M8\] entities: \{(.*)\}$", client.text(), re.MULTILINE)[-1]
    return int((re.search(r"block_display=(\d+)", found) or [0, 0])[1])


def play_show(results, client):
    x, y, z = SPOT
    kind = slot("props", "totem")
    stand(0, 0, yaw=0, pitch=0)
    rcon("clear", PLAYER)
    rcon("give", PLAYER, slot("items", "show_wand"))
    time.sleep(1)
    client.ask("use")
    client.wait(r"chat: RIDE totem placed", 10)
    report(results, "a module can place a prop", has("entity", f"@e[type={kind}]"))
    time.sleep(1)
    client.ask("shot prop")
    rcon("conduit", "pose", f"@e[type={kind}]", "spin", "0.25")
    client.ask("shot prop_turned")
    with Image.open(collect_shots()["prop"]) as first, Image.open(collect_shots()["prop_turned"]) as second:
        changed = ImageChops.difference(first.convert("RGB"), second.convert("RGB")).getbbox()
    report(results, "and its animations really move it", changed is not None, str(changed))
    rcon("tp", PLAYER, str(x), str(y), str(z + 1.5), "0", "0")
    time.sleep(0.5)
    client.ask("rightclick")
    client.wait(r"chat: RIDE totem clicked", 10)
    report(results, "and a player can click one", True)

    # A tall beam, and a slanted one with a time limit, close up, from most of the way across what a client can see, from past that, and then gone.
    stand(0, 0, yaw=90, pitch=-25)
    drawn = time.monotonic()
    client.ask("use")
    client.wait(r"chat: RIDE beams drawn", 10)
    time.sleep(1)
    displays = display_count(client)
    report(results, "both beams reach the client, in pieces", displays >= BEAM_PIECES, f"{displays} block displays, and {BEAM_PIECES} of them are pieces")
    client.ask("shot beam_close")
    chunks = int(re.findall(r"\[M8\] render distance: (\d+)$", client.text(), re.MULTILINE)[-1])
    rcon("gamemode", "spectator", PLAYER)
    rcon("tp", PLAYER, str(x + chunks * 12), str(y + 20), str(z), "90", "-20")
    time.sleep(4)
    near_edge = display_count(client)
    report(results, f"they can still be seen from {chunks * 12} blocks away, in a render distance of {chunks} chunks", near_edge >= TALL_BEAM_PIECES, f"{near_edge} block displays")
    client.ask("shot beam_far")
    rcon("tp", PLAYER, str(x + (chunks + 4) * 16), str(y + 20), str(z), "90", "-20")
    time.sleep(4)
    past_edge = display_count(client)
    report(results, "and past what a client can see, they aren't sent at all", past_edge < TALL_BEAM_PIECES, f"{past_edge} block displays from {(chunks + 4) * 16} blocks away")
    client.ask("shot beam_beyond")
    rcon("tp", PLAYER, str(x), str(y), str(z), "90", "-25")
    rcon("gamemode", "survival", PLAYER)
    # The slanted one lasts 15 seconds, and the other until it's removed.
    time.sleep(max(3, drawn + 18 - time.monotonic()))
    left = display_count(client)
    report(results, "the one with a time limit goes by itself", left == displays - SLANTED_BEAM_PIECES, f"{displays} to {left}")
    client.ask("use")
    client.wait(r"chat: RIDE beam removed: true", 10)
    time.sleep(2)
    gone = display_count(client)
    report(results, "and a module can take one away", gone == left - TALL_BEAM_PIECES, f"{left} to {gone}")


def tick_time():
    answer = rcon("tick", "query")
    found = re.search(r"Average time per tick: ([\d.]+)", answer)
    return float(found.group(1)) if found else None


def stress(results, client):
    """What each kind costs the server, with one player watching. Software rendering says nothing about a real PC's frame rate, so that stays unmeasured."""
    x, y, z = SPOT
    arena()
    stand(0, 0, yaw=0, pitch=0)
    rcon("clear", PLAYER)
    rcon("give", PLAYER, slot("items", "crowd_wand"))
    time.sleep(15)
    idle = tick_time()
    print(f"server time per tick: {idle} ms idle", flush=True)

    kind = slot("projectiles", "swarm")
    client.ask("use")
    client.wait(r"chat: RIDE crowd true", 10)
    time.sleep(15)
    found = re.search(r"count: (\d+)", rcon("execute", "if", "entity", f"@e[type={kind}]"), re.IGNORECASE)
    flying = int(found.group(1)) if found else 0
    shots = tick_time()
    print(f"server time per tick: {shots} ms with {flying} projectiles in the air", flush=True)
    report(results, f"however many a module fires, no more than {MOST_FLYING} are in the air", 0 < flying <= MOST_FLYING, f"{flying} in the air")
    report(results, "and that crowd of shots leaves the server plenty of room", shots is not None and shots < 25, f"{shots} ms a tick")
    client.ask("shot crowd_projectiles")
    client.ask("use")
    client.wait(r"chat: RIDE crowd false", 10)
    time.sleep(10)
    rcon("kill", f"@e[type={kind}]")

    rover = slot("vehicles", "rover")
    for index in range(CROWD_VEHICLES):
        rcon("summon", rover, str(x - 14 + index % 8 * 4), str(y), str(z + 4 + index // 8 * 4))
    time.sleep(15)
    vehicles = tick_time()
    print(f"server time per tick: {vehicles} ms with {CROWD_VEHICLES} vehicles nearby, none with a rider", flush=True)
    report(results, "and a crowd of vehicles does too", vehicles is not None and vehicles < 25, f"{vehicles} ms a tick")
    client.ask("shot crowd_vehicles")
    rcon("kill", f"@e[type={rover}]")

    totem = slot("props", "totem")
    for index in range(CROWD_PROPS):
        rcon("summon", totem, str(x - 14 + index % 20 * 1.5), str(y), str(z + 3 + index // 20 * 2))
    time.sleep(15)
    props = tick_time()
    print(f"server time per tick: {props} ms with {CROWD_PROPS} props nearby", flush=True)
    report(results, "and a crowd of props does too", props is not None and props < 25, f"{props} ms a tick")
    client.ask("shot crowd_props")
    rcon("kill", f"@e[type={totem}]")


def check_restart(results):
    """A vehicle and a prop are in the world's files like anything else, and these are the first entities of their kinds to go through a restart."""
    x, y, z = SPOT
    rover = slot("vehicles", "rover")
    totem = slot("props", "totem")
    rcon("kill", f"@e[type={rover}]")
    rcon("summon", rover, str(x), str(y), str(z - 10), "{UUID:[I;9,10,11,12]}")
    rcon("summon", totem, str(x + 3), str(y), str(z - 10), "{UUID:[I;5,6,7,8]}")
    rcon("save-all", "flush")
    time.sleep(3)
    runtime.run(["./scripts/stack.sh", "restart", "prod"], timeout=300)
    runtime.wait_ready("prod", timeout=300)
    rcon("forceload", "add", str(x - 8), str(z - 16), str(x + 8), str(z - 4))
    time.sleep(5)
    report(results, "a vehicle and a prop are still there after a restart", has("entity", f"@e[type={rover},x={x},y={y},z={z - 10},distance=..2]") and has("entity", f"@e[type={totem},x={x + 3},y={y},z={z - 10},distance=..2]"))


def before():
    """Run this on an engine from before these slots existed, so that a mob is already in the world when a later run brings them in."""
    build_source(with_rides=False)
    answer = promote()
    print(json.dumps({key: answer.get(key) for key in ("result", "tier", "stages", "seconds")}), str(answer.get("reason"))[:800], flush=True)
    if answer.get("result") != "released":
        return 1
    walker = "gm:" + ledger("mobs")["elder/walker"]["slot"]
    x, y, z = ELDER_SPOT
    rcon("forceload", "add", str(x - 8), str(z - 8), str(x + 8), str(z + 8))
    rcon("fill", str(x - 3), str(y - 1), str(z - 3), str(x + 3), str(y - 1), str(z + 3), "minecraft:smooth_stone")
    summoned = rcon("summon", walker, str(x), str(y), str(z), "{UUID:%s,NoAI:1b,PersistenceRequired:1b,Rotation:[90f,0f]}" % ELDER_UUID_ARRAY)
    print(summoned, flush=True)
    rcon("save-all", "flush")
    time.sleep(5)
    MARKER.write_text(json.dumps({"slot": walker, "pool": subprocess.run(["grep", "-c", "SlotEntities", "mods/conduit/src/main/java/gm/conduit/Conduit.java"], cwd=runtime.REPO, capture_output=True, text=True, check=False).stdout.strip()}), encoding="utf-8")
    return 0 if "Summoned" in summoned else 1


def check_from_before(results, client):
    """The new pools can't be allowed to change what's in a world that was there first."""
    if not MARKER.exists():
        print("no mob from an older engine in this world, so that part isn't tested", flush=True)
        return
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    walker = "gm:" + ledger("mobs")["elder/walker"]["slot"]
    x, y, z = ELDER_SPOT
    report(results, "that mob started on an engine with none of these slots", marker["pool"] == "0", str(marker))
    report(results, "and its slot hasn't changed in the ledger", walker == marker["slot"], f"{marker['slot']} to {walker}")
    report(results, "and it's still in the world, the same one, after the upgrade", has("entity", ELDER_UUID) and has("entity", f"@e[type={walker},x={x},y={y},z={z},distance=..2]"), walker)
    health = number(rcon("data", "get", "entity", ELDER_UUID, "Health"))
    report(results, "and it's still what it was", health == 12, f"{health} health")
    rcon("gamemode", "spectator", PLAYER)
    rcon("tp", PLAYER, str(x - 3.5), str(y), str(z), "-90", "10")
    client.ask("shot elder_after_upgrade")


def attempt(results, client, play, start_clean=True):
    """One part failing says nothing about the next, and a run takes long enough that it should say all it can."""
    try:
        if start_clean:
            rcon("ride", PLAYER, "dismount")
            for name in ("skiff", "rover", "glider"):
                rcon("kill", f"@e[type={slot('vehicles', name)}]")
            rcon("kill", "@e[type=minecraft:item]")
            arena()
            client.ask("unsneak")
            client.ask("camera first")
        return play(results, client)
    except (TimeoutError, RuntimeError, IndexError, KeyError, TypeError, ValueError) as error:
        report(results, f"{play.__name__} gets to its end", False, repr(error)[:500])
        return None


def main(parts):
    results = []
    build_source()
    answer = promote("--lint-only")
    report(results, "the test feature passes the rule checks", answer.get("result") == "passed_lint", str(answer.get("reason"))[:800])
    print("advice:", answer.get("advice"), flush=True)
    if answer.get("result") != "passed_lint":
        return results
    answer = promote()
    # Already released is fine, for going over the rest again without starting a world from nothing.
    report(results, "and it goes live through every gate", answer.get("result") in ("released", "nothing_to_release"),
           f"{answer.get('tier')} in {answer['seconds']}s {answer.get('stages')} {str(answer.get('reason'))[:800]}")
    if answer.get("result") not in ("released", "nothing_to_release"):
        return results
    print("gate screenshots:", answer.get("screenshots"), flush=True)

    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    client = Client(runtime.WORK / "mods", runtime.REPORTS / "m28-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 600)
        time.sleep(5)
        wanted = lambda play: not parts or play.__name__ in parts  # noqa: E731
        if wanted(check_from_before):
            attempt(results, client, check_from_before, start_clean=False)
        for play in filter(wanted, (play_projectile, play_boat, play_rover)):
            attempt(results, client, play)
        if wanted(play_rejoin):
            client = attempt(results, client, play_rejoin, start_clean=False) or client
        for play in filter(wanted, (play_air, play_show, stress)):
            attempt(results, client, play)
    finally:
        client.stop()
    if wanted(check_restart):
        check_restart(results)
    collect_shots()
    return results


if __name__ == "__main__":
    if "--before" in sys.argv:
        sys.exit(before())
    outcome = main(sys.argv[1:])
    print(f"{sum(outcome)} of {len(outcome)} checks passed", flush=True)
    sys.exit(0 if all(outcome) else 1)
