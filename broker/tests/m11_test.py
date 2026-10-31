#!/usr/bin/env python3
"""Sculpted models on a real game client: creatures of very different shapes and a machine with moving parts, then
hundreds of models at once, because a world can be all about its creatures. Runs against prod, so reset the dev world
afterwards. The models come from broker/tests/fixtures/sculpted, which the agent can't see, so they can't become premade art.

Usage: python3 -m broker.tests.m11_test
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageChops

from broker import runtime
from broker.gates import client as gate_client
from broker.tests.m8_test import Client
from orchestrator import progression

SOURCE = runtime.BROKER / "testsrc-m11"
FEATURES = SOURCE / "mods" / "genesis" / "features"
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "sculpted"
WORK = runtime.RUNTIME / "agent-workspace" / "m11"
OUT = runtime.REPORTS / "m11"
PLAYER = "Player0"
SPOT = (40, 120, 40)
CREATURES = {"mouse": 5, "toad": 5, "dragon": 8, "snake": 7, "jelly": 6}
ZOO_SIZE = 150
CROWD = 60
MAX_BOOT_SECONDS = 45

WORLD = {"goal": "See how far the models go", "nodes": {
    "first_steps": {"stage": "early", "name": "First steps", "requires": [], "opens_with": "", "holds": "Creatures"},
    "machines": {"stage": "mid", "name": "Machines", "requires": ["first_steps"], "opens_with": "fluff", "holds": "The press"},
    "the_end": {"stage": "end", "name": "The end", "requires": ["machines"], "opens_with": "the press", "holds": "The colossus"},
}}

MAKE_PRESS = """
import pathlib, shutil
from orchestrator import templates as t
f = pathlib.Path('/workspace/m11/features/press')
(f / 'assets/models').mkdir(parents=True)
shutil.copy('/workspace/m11/models/press.bbmodel', f / 'assets/models/press.bbmodel')
print(t.new_machine(f, name='press', display='Brass Press', casing='#8a6a28', accent='#ff9a38', recipe_ingredients=['$item:menagerie/fluff', 'minecraft:iron_block'],
                    model='press', automation=[{'what': 'crafting', 'per_minute': 10}], node='machines')['summary'])
"""


def report(results, name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    results.append(passed)
    return passed


def in_agent(*command):
    return runtime.run(["./scripts/stack.sh", "--profile", "agent", "run", "--rm", "-T", "agent", *command], timeout=600).stdout


def sculpt():
    """Runs the scripts the way a modeller does, in the agent's container, which is the only place with its libraries."""
    runtime.run(["./scripts/prepare-workspace.sh"], timeout=60)
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "models").mkdir(parents=True)
    (WORK / "features").mkdir()
    shutil.copytree(FIXTURES, WORK / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    for folder, _, _ in os.walk(WORK):
        os.chmod(folder, 0o2775)
    script = "cd /workspace/m11/scripts && for name in " + " ".join([*CREATURES, "colossus", "press"]) + "; do python3 $name.py /workspace/m11/models; done"
    print("\n".join(line[:240] for line in in_agent("bash", "-c", script).splitlines() if "Container " not in line), flush=True)
    print(in_agent("python3", "-c", MAKE_PRESS)[-400:], flush=True)


def mob_entry(name, **fields):
    numbers = json.loads((WORK / "models" / f"{name}.json").read_text(encoding="utf-8"))
    return {"category": "creature", "display": name.capitalize(), "model": name, "behaviour": "passive", "health": 20, "damage": 0, "speed": 0.2,
            "width": min(numbers.get("width", 0.9), 3), "height": min(numbers.get("height", 0.9), 7), **fields}


def write_feature(feature_id, node, models, **manifest):
    folder = FEATURES / feature_id
    (folder / "assets" / "models").mkdir(parents=True)
    for name in models:
        shutil.copy(WORK / "models" / f"{name}.bbmodel", folder / "assets" / "models")
    (folder / "feature.json").write_text(json.dumps({"id": feature_id, "node": node, "summary": "A test.", **manifest}, indent=1), encoding="utf-8")
    return folder


def build_source():
    sculpt()
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    if FEATURES.exists():
        shutil.rmtree(FEATURES)
    FEATURES.mkdir(parents=True)
    (SOURCE / "bible").mkdir(exist_ok=True)
    progression.save(SOURCE / "bible" / "progression.json", WORLD)
    mobs = {name: mob_entry(name) for name in CREATURES}
    mobs["mouse"]["drops"] = {"item": "fluff", "count": [1, 2]}
    menagerie = write_feature("menagerie", "first_steps", CREATURES, mobs=mobs, items={"fluff": {"display": "Fluff", "texture": "fluff"}},
                              recipes={"cord": {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["$item:fluff"], "result": {"id": "minecraft:string", "count": 1}}}})
    (menagerie / "assets" / "textures").mkdir(parents=True)
    Image.effect_noise((16, 16), 40).convert("RGB").save(menagerie / "assets" / "textures" / "fluff.png")
    write_feature("boss", "the_end", ["colossus"], mobs={"colossus": mob_entry("colossus", category="monster", behaviour="hostile", health=2000, damage=40, display="Colossus")})
    shutil.copytree(WORK / "features" / "press", FEATURES / "press", ignore=shutil.ignore_patterns("__pycache__"))
    # The machine shows it's working, so that a module's call to play an animation really gets tried.
    module = next((FEATURES / "press" / "server").rglob("*.java"))
    source = module.read_text(encoding="utf-8").replace("CompoundTag data = machine.data();", 'machine.play("walk");\n\t\tCompoundTag data = machine.data();')
    source = source.replace("ItemStack main = player.getMainHandItem();", 'player.sendSystemMessage(Component.literal("Brass Press was used"));\n\t\tItemStack main = player.getMainHandItem();')
    module.write_text(source, encoding="utf-8")


def promote(*flags):
    started = time.monotonic()
    subprocess.run([sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m11-{int(time.time())}", *flags],
                   cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1500)
    answer = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    answer["seconds"] = round(time.monotonic() - started, 1)
    return answer


def ledger():
    return json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))


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
    x, y, z = SPOT
    for command in (("gamemode", "survival", PLAYER), ("difficulty", "peaceful"), ("gamerule", "doDaylightCycle", "false"), ("time", "set", "noon"), ("weather", "clear"),
                    ("forceload", "add", str(x - 32), str(z - 32), str(x + 32), str(z + 32)),
                    ("fill", str(x - 24), str(y - 1), str(z - 8), str(x + 24), str(y - 1), str(z + 24), "minecraft:smooth_stone"),
                    ("fill", str(x - 24), str(y), str(z - 8), str(x + 24), str(y + 16), str(z + 24), "minecraft:air"),
                    ("clear", PLAYER)):
        runtime.rcon("prod", *command, check=False)


def look_at_south(height=1.0):
    x, y, z = SPOT
    runtime.rcon("prod", "tp", PLAYER, str(x), str(y), str(z), "0", str(height), check=False)


def check_hurt_and_death(results, client, slot):
    """A body has to stay for as long as its death animation lasts, and go once that's over. Selectors like @e skip
    anything dying, so this looks through the client's eyes, at a boss whose death outlasts the two seconds a screenshot takes."""
    x, y, z = SPOT
    model = json.loads((WORK / "models" / "colossus.bbmodel").read_text(encoding="utf-8"))
    death = next((animation["length"] for animation in model["animations"] if animation["name"] == "death"), None)
    report(results, "a creature has a death animation that outlasts a normal death", (death or 0) > 3, f"{death}s")
    if not death or death <= 3:
        return
    look_at_south(-14)
    runtime.rcon("prod", "summon", slot, str(x), str(y), str(z + 14), "{NoAI:1b,PersistenceRequired:1b,Rotation:[180f,0f]}", check=False)
    time.sleep(2)
    hurt = runtime.rcon("prod", "damage", f"@e[type={slot},limit=1]", "1", check=False)
    report(results, "it can be hurt with no errors", "Applied" in hurt, hurt[:70])
    runtime.rcon("prod", "kill", f"@e[type={slot}]", check=False)
    client.ask("shot dying")
    time.sleep(death + 1)
    client.ask("shot dead")
    shots = collect_shots()
    with Image.open(shots["dying"]) as dying, Image.open(shots["dead"]) as dead:
        box = (dying.width // 4, dying.height // 8, dying.width * 3 // 4, dying.height * 3 // 4)
        changed = ImageChops.difference(dying.convert("RGB").crop(box), dead.convert("RGB").crop(box)).convert("L").point(lambda value: 255 if value > 24 else 0)
    # A normal death would've been gone a second before the first of these was taken.
    report(results, "its body stays through the animation, and then goes", changed.getbbox() is not None, str(changed.getbbox()))


def tour(results, client):
    x, y, z = SPOT
    table = ledger()["mobs"]
    arena()
    time.sleep(3)
    subjects = [(name, f"menagerie/{name}", distance) for name, distance in CREATURES.items()] + [("colossus", "boss/colossus", 14)]
    for name, key, distance in subjects:
        slot = f"gm:{table[key]['slot']}"
        look_at_south(-14 if name == "colossus" else 5)
        answer = runtime.rcon("prod", "summon", slot, str(x), str(y), str(z + distance), "{NoAI:1b,PersistenceRequired:1b,Rotation:[180f,0f]}", check=False)
        report(results, f"the {name} can be summoned", "Summoned" in answer, answer[:70])
        time.sleep(2)
        client.ask(f"shot {name}")
        runtime.rcon("prod", "kill", f"@e[type={slot}]", check=False)
        time.sleep(1)

    check_hurt_and_death(results, client, f"gm:{table['boss/colossus']['slot']}")

    press = f"gm:{ledger()['blocks']['press/press']['slot']}"
    px, py, pz = x, y, z + 3
    placed = runtime.rcon("prod", "setblock", str(px), str(py), str(pz), press, check=False)
    report(results, "the model block can be placed", "Changed" in placed, placed)
    look_at_south(14)
    time.sleep(3)
    client.ask("shot press_1")
    time.sleep(0.6)
    client.ask("shot press_2")
    client.ask(f"useblock {px} {py} {pz}")
    time.sleep(1)
    report(results, "a player can use it, and its module hears about it", "Brass Press was used" in client.text())
    runtime.rcon("prod", "give", PLAYER, "minecraft:diamond_pickaxe", check=False)
    # Mobs killed earlier left their drops around, which mustn't be mistaken for this block's.
    runtime.rcon("prod", "kill", "@e[type=item]", check=False)
    time.sleep(1)
    client.ask("mine 80")
    time.sleep(1)
    gone = runtime.rcon("prod", "execute", "if", "block", str(px), str(py), str(pz), "minecraft:air", check=False)
    report(results, "a player can mine it", "passed" in gone.lower(), gone)
    dropped = runtime.rcon("prod", "execute", "if", "entity", f"@e[type=item,x={px},y={py},z={pz},distance=..4]", check=False)
    report(results, "and it drops itself", "passed" in dropped.lower(), dropped)
    runtime.rcon("prod", "setblock", str(px), str(py), str(pz), "minecraft:air", check=False)
    runtime.rcon("prod", "kill", "@e[type=item]", check=False)


def check_shots(results, shots):
    for name in [*CREATURES, "colossus"]:
        passed = name in shots
        if passed:
            gate_client.check_image(shots[name])
        report(results, f"the {name} shows up on a real client, with no missing textures", passed, str(shots.get(name, ""))[-40:])
    if "press_1" in shots and "press_2" in shots:
        with Image.open(shots["press_1"]) as first, Image.open(shots["press_2"]) as second:
            box = (first.width // 3, first.height // 3, first.width * 2 // 3, first.height * 5 // 6)
            changed = ImageChops.difference(first.convert("RGB").crop(box), second.convert("RGB").crop(box)).getbbox()
        report(results, "its parts really move", changed is not None, str(changed))


def tick_time():
    answer = runtime.rcon("prod", "tick", "query", check=False)
    found = re.search(r"Average time per tick: ([\d.]+)", answer)
    return float(found.group(1)) if found else None


def memory():
    return subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", "livingmod-prod-1"], capture_output=True, text=True, check=False).stdout.strip()


def pack_size():
    path = runtime.RUNTIME / "prod" / "polymer" / "resource_pack.zip"
    return round(path.stat().st_size / 1_000_000, 1) if path.exists() else None


def stress(results):
    """A world with many creatures. Rendering in software says nothing about a real PC's frame rate, so that stays unmeasured."""
    print(f"pack before the zoo: {pack_size()} MB, server {memory()}, {tick_time()} ms a tick", flush=True)
    folder = FEATURES / "zoo"
    models = folder / "assets" / "models"
    models.mkdir(parents=True)
    sources = [json.loads((WORK / "models" / f"{name}.bbmodel").read_text(encoding="utf-8")) for name in CREATURES]
    mobs = {}
    for index in range(ZOO_SIZE):
        model = dict(sources[index % len(sources)])
        model["name"] = f"z{index}"
        (models / f"z{index}.bbmodel").write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
        mobs[f"z{index}"] = {"category": "creature", "display": f"Zoo {index}", "model": f"z{index}", "behaviour": "passive", "health": 20, "damage": 0, "speed": 0.2, "width": 1, "height": 2}
    (folder / "feature.json").write_text(json.dumps({"id": "zoo", "node": "first_steps", "summary": "A lot of creatures.", "mobs": mobs}), encoding="utf-8")

    answer = promote()
    report(results, f"{ZOO_SIZE} more models go live with no restart", answer.get("result") == "released" and answer.get("tier") == "T2",
           f"{answer.get('tier')} in {answer['seconds']}s {answer.get('stages')} {str(answer.get('reason'))[:300]}")
    print(f"pack with the zoo: {pack_size()} MB, server {memory()}", flush=True)

    started = time.monotonic()
    runtime.run(["./scripts/stack.sh", "restart", "prod"], timeout=300)
    runtime.wait_ready("prod", timeout=300)
    boot = round(time.monotonic() - started, 1)
    report(results, f"the server still restarts in under {MAX_BOOT_SECONDS} seconds", boot < MAX_BOOT_SECONDS, f"{boot}s")
    print(f"after a restart: server {memory()}", flush=True)

    client = Client(runtime.WORK / "mods", runtime.REPORTS / "m11-zoo-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 600)
        joined = time.monotonic()
        client.ask("light 0 64 0", 300)
        print(f"a client took {round(time.monotonic() - joined, 1)}s from joining to being ready, including loading the pack", flush=True)
        arena()
        x, y, z = SPOT
        look_at_south(5)
        idle = tick_time()
        table = ledger()["mobs"]
        for index in range(CROWD):
            slot = table[f"zoo/z{index % ZOO_SIZE}"]["slot"]
            runtime.rcon("prod", "summon", f"gm:{slot}", str(x - 12 + index % 12 * 2), str(y), str(z + 6 + index // 12 * 3), "{PersistenceRequired:1b}", check=False)
        time.sleep(15)
        crowded = tick_time()
        print(f"server time per tick: {idle} ms idle, {crowded} ms with {CROWD} creatures nearby, against a budget of 50", flush=True)
        report(results, f"{CROWD} creatures around a player leave the server plenty of room", crowded is not None and crowded < 25, f"{crowded} ms a tick")
        client.ask("shot crowd")
    finally:
        client.stop()
    return collect_shots()


def main():
    results = []
    build_source()
    answer = promote("--lint-only")
    report(results, "the sculpted creatures and model block pass the rule checks", answer.get("result") == "passed_lint", str(answer.get("reason"))[:500])
    print("advice:", answer.get("advice"), flush=True)
    if answer.get("result") != "passed_lint":
        return results
    answer = promote()
    report(results, "and they go live through every gate with no restart", answer.get("result") == "released" and answer.get("tier") == "T2",
           f"{answer.get('tier')} in {answer['seconds']}s {answer.get('stages')} {str(answer.get('reason'))[:500]}")
    if answer.get("result") != "released":
        return results
    print("gate screenshots:", answer.get("screenshots"), flush=True)
    motion = [shot for shot in answer.get("screenshots", []) if "motion_" in shot]
    report(results, "the gates filmed the new mobs moving on a real client", len(motion) >= 2, str([shot.rsplit("/", 1)[-1] for shot in motion]))

    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    client = Client(runtime.WORK / "mods", runtime.REPORTS / "m11-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 600)
        time.sleep(5)
        tour(results, client)
    finally:
        client.stop()
    check_shots(results, collect_shots())
    stress(results)
    return results


if __name__ == "__main__":
    outcome = main()
    print(f"{sum(outcome)} of {len(outcome)} checks passed", flush=True)
    sys.exit(0 if all(outcome) else 1)
