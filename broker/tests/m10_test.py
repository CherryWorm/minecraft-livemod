#!/usr/bin/env python3
"""The arc of a world on a real server: content made by the starter templates goes live and really has its numbers, the
progression stops what doesn't fit it, what players already have is protected, a number can be tuned in under a minute,
and the server icon changes with nobody disconnected. Runs against prod, so reset the dev world afterwards.

Usage: python3 -m broker.tests.m10_test
"""
import base64
import json
import pathlib
import shutil
import socket
import struct
import subprocess
import sys
import time

from PIL import Image

from broker import daemon, runtime
from orchestrator import progression, tuning

SOURCE = runtime.BROKER / "testsrc-m10"
FEATURES = SOURCE / "mods" / "genesis" / "features"
MADE = runtime.RUNTIME / "agent-workspace" / "m10"
PLAYER = "Aria"
BOT_LOG = runtime.BROKER / "m10-bot.jsonl"
PROTOCOL = 777
LINT_SECONDS = 3
TUNE_SECONDS = 60

WORLD = {"goal": "Wind the great engine back up", "nodes": {
    "first_steps": {"stage": "early", "name": "First steps", "requires": [], "opens_with": "", "holds": "Tin, tools, reeds, crabs"},
    "side_path": {"stage": "early", "name": "A side path", "requires": [], "opens_with": "", "holds": "Nothing yet"},
    "machines": {"stage": "mid", "name": "Machines", "requires": ["first_steps"], "opens_with": "tin ingots", "holds": "The press"},
    "the_engine": {"stage": "end", "name": "The engine", "requires": ["machines"], "opens_with": "pressed tin", "holds": "The blade"},
}}

MAKE = """
import pathlib, shutil
from orchestrator import templates as t
root = pathlib.Path('/workspace/m10')
shutil.rmtree(root, ignore_errors=True)
t.new_ore(root / 'tin', name='tin', display='Tin', color='#9fb7c4', tier='iron', node='first_steps')
t.new_tool_set(root / 'tin_tools', material='tin', display='Tin', tier='iron', ingredient='$item:tin/tin_ingot', color='#9fb7c4', node='first_steps')
t.new_armor_set(root / 'tin_armor', material='tin', display='Tin', tier='iron', ingredient='$item:tin/tin_ingot', color='#9fb7c4', node='first_steps')
t.new_plant(root / 'reed', name='reed', display='Sweet Reed', color='#7fae5a', food={'nutrition': 3, 'saturation': 1.8}, on=['minecraft:grass_block', 'minecraft:sand'], node='first_steps')
t.new_plant(root / 'marsh_grass', name='marsh_grass', display='Marsh Grass', color='#808080', family='tinted_plant', kind='grass', on=['minecraft:grass_block'], node='first_steps')
t.new_mob(root / 'crab', name='crab', display='Shore Crab', category='creature', behaviour='skittish', shape='quadruped', primary='#c0603c', secondary='#e8d8b8', health=10, damage=0, node='first_steps')
t.new_machine(root / 'press', name='press', display='Tin Press', casing='#6a7078', accent='#d89a40', recipe_ingredients=['$item:tin/tin_ingot', 'minecraft:iron_block'], automation=[{'what': 'crafting', 'per_minute': 10}], node='machines')
t.new_tool_set(root / 'blade', material='engine', display='Engine', tier='mythic', ingredient='$block:press/press', color='#e04080', kinds=('sword',), node='the_engine')
print('made')
"""


def report(results, name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    results.append(passed)
    return passed


def make_content():
    """Templates need assetkit's libraries, so they run in the agent's container, the way a builder runs them."""
    runtime.run(["./scripts/prepare-workspace.sh"], timeout=60)
    runtime.run(["./scripts/stack.sh", "--profile", "agent", "run", "--rm", "-T", "agent", "python3", "-c", MAKE], timeout=180)
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    if FEATURES.exists():
        shutil.rmtree(FEATURES)
    shutil.copytree(MADE, FEATURES, ignore=shutil.ignore_patterns("__pycache__"))
    bible = SOURCE / "bible"
    bible.mkdir(exist_ok=True)
    progression.save(bible / "progression.json", WORLD)


def promote(*flags):
    release = f"m10-{int(time.time())}"
    started = time.monotonic()
    subprocess.run([sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", release, *flags],
                   cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1200)
    answer = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    answer["seconds"] = round(time.monotonic() - started, 1)
    return answer


def manifest_path(feature):
    return FEATURES / feature / "feature.json"


def edit(feature, change):
    path = manifest_path(feature)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    original = path.read_text(encoding="utf-8")
    change(manifest)
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return lambda: path.write_text(original, encoding="utf-8")


def slot(ledger, table, key):
    return f"gm:{ledger[table][key]['slot']}"


def current_ledger():
    state = runtime.load_state()
    return json.loads((runtime.HISTORY / state["current"] / "registry-ledger.json").read_text(encoding="utf-8"))


def holds(item, predicate=""):
    """Asks the game itself whether the player has an item with this component, and takes none of it."""
    answer = runtime.rcon("prod", "clear", PLAYER, f"{item}[{predicate}]" if predicate else item, "0", check=False)
    return "Found" in answer, answer


def give(item):
    return runtime.rcon("prod", "give", PLAYER, item, check=False)


def varint(value):
    out = b""
    while True:
        part = value & 0x7F
        value >>= 7
        out += bytes([part | (0x80 if value else 0)])
        if not value:
            return out


def read_varint(stream):
    result, shift = 0, 0
    while True:
        byte = stream.recv(1)[0]
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result


def ping():
    """What a client's server list sees."""
    with socket.create_connection(("localhost", 25565), timeout=15) as stream:
        host = b"localhost"
        handshake = b"\x00" + varint(PROTOCOL) + varint(len(host)) + host + struct.pack(">H", 25565) + varint(1)
        stream.sendall(varint(len(handshake)) + handshake + varint(1) + b"\x00")
        read_varint(stream)
        read_varint(stream)
        size = read_varint(stream)
        data = b""
        while len(data) < size:
            data += stream.recv(size - len(data))
    return json.loads(data)


def bot_still_connected():
    """Looks at what's happened since it joined, because being told to wait at login isn't being dropped."""
    kinds = [json.loads(line).get("kind") for line in BOT_LOG.read_text(encoding="utf-8").splitlines()] if BOT_LOG.exists() else []
    return "joined" in kinds and "disconnected" not in kinds[kinds.index("joined"):]


def main():
    results = []
    make_content()

    # The progression stops what doesn't fit, in the instant check.
    undo = edit("tin", lambda manifest: manifest.update(automation=[{"what": "mining", "per_minute": 6}]))
    answer = promote("--lint-only")
    report(results, "early-game automation is refused", answer.get("gate") == "progression" and "themselves" in answer.get("reason", ""), str(answer.get("reason"))[:120])
    report(results, "and the instant check is instant", answer["seconds"] < LINT_SECONDS, f"{answer['seconds']}s")
    undo()
    undo = edit("reed", lambda manifest: next(iter(manifest["items"].values())).update(tier="netherite"))
    answer = promote("--lint-only")
    report(results, "gear too strong for its stage is refused", "strongest allowed" in str(answer.get("reason")), str(answer.get("reason"))[:120])
    undo()
    undo = edit("blade", lambda manifest: next(iter(manifest["recipes"].values()))["json"].update(key={"X": "$item:tin/tin_ingot", "S": "minecraft:stick"}))
    answer = promote("--lint-only")
    report(results, "endgame gear made of the first ore is refused", "nothing gates it" in str(answer.get("reason")), str(answer.get("reason"))[:120])
    undo()
    undo = edit("press", lambda manifest: manifest["automation"][0].update(what="mining", per_minute=60))
    answer = promote("--lint-only")
    report(results, "fast mid-game mining is refused", "Slow it down" in str(answer.get("reason")), str(answer.get("reason"))[:120])
    undo()

    answer = promote("--lint-only")
    report(results, "everything the templates made passes the rule checks", answer.get("result") == "passed_lint", str(answer.get("reason"))[:600])
    print("advice:", json.dumps(answer.get("advice"))[:800], flush=True)
    if answer.get("result") != "passed_lint":
        return results

    answer = promote()
    report(results, "and it all goes live through every gate", answer.get("result") == "released",
           f"{answer.get('tier')} in {answer.get('total_seconds')}s, {answer.get('stages')} {str(answer.get('reason'))[:500]}")
    if answer.get("result") != "released":
        return results
    for shot in answer.get("screenshots", []):
        print("screenshot:", shot, flush=True)

    # Nothing else knows the game's format for components, so a mistake in one has to stop at the test server.
    undo = edit("reed", lambda manifest: next(item for item in manifest["items"].values() if item.get("components"))["components"].update({"minecraft:food": {"nutrition": "lots"}}))
    answer = promote("--no-deploy")
    report(results, "a broken component stops at the test server", answer.get("gate") == "shadow" and "Can't read the defaults" in str(answer.get("reason")),
           f"{answer.get('gate')}: {str(answer.get('reason'))[:200]}")
    undo()

    # A player has to be there for things to count as found, and for numbers on real stacks.
    script = runtime.BROKER / "m10-bot.json"
    script.write_text(json.dumps({"answers": [], "public": []}), encoding="utf-8")
    BOT_LOG.unlink(missing_ok=True)
    bot = subprocess.Popen([sys.executable, "scripts/playtest_bot.py", "--name", PLAYER, "--script", str(script), "--log", str(BOT_LOG), "--seconds", "400"],
                           cwd=runtime.REPO, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(12)
        ledger = current_ledger()
        pick = slot(ledger, "items", "tin_tools/tin_pickaxe")
        give(pick)
        good, detail = holds(pick, "minecraft:max_damage=250")
        report(results, "a templated pickaxe has iron's durability on a real stack", good, detail)
        good, detail = holds(pick, "minecraft:tool")
        report(results, "and it really is a tool", good, detail)
        sword = slot(ledger, "items", "tin_tools/tin_sword")
        give(sword)
        good, detail = holds(sword, "minecraft:attribute_modifiers")
        report(results, "a templated sword has its attack numbers", good, detail)
        chest = slot(ledger, "items", "tin_armor/tin_chestplate")
        give(chest)
        good, detail = holds(chest, "minecraft:equippable")
        report(results, "templated armor can be worn", good, detail)
        food = next(key for key in ledger["items"] if key.startswith("reed/") and "seed" not in key)
        food_slot = slot(ledger, "items", food)
        give(food_slot)
        good, detail = holds(food_slot, "minecraft:food")
        report(results, "a templated plant's food can be eaten", good, detail)

        recipes = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "content" / "recipes.json").read_text(encoding="utf-8"))
        unknown = []
        for recipe, info in recipes.items():
            # Being told it's already known is fine. It's only an error if the game never loaded it.
            answer = "" if info.get("machine") else runtime.rcon("prod", "recipe", "give", PLAYER, recipe, check=False)
            if answer and "Unlocked" not in answer and "No new recipes" not in answer:
                unknown.append((recipe, info["source"], answer[:80]))
        report(results, f"the game accepted all {len(recipes)} templated recipes", not unknown, str(unknown)[:400])

        crab = slot(ledger, "mobs", "crab/crab")
        summoned = runtime.rcon("prod", "summon", crab, "0", "100", "0", check=False)
        report(results, "a templated mob can be summoned", "Summoned" in summoned, summoned)
        press = slot(ledger, "blocks", "press/press")
        placed = runtime.rcon("prod", "setblock", "0", "90", "0", press, check=False)
        time.sleep(4)
        report(results, "a templated machine can be placed, and its module runs without errors", "Changed" in placed or "placed" in placed.lower(), placed)

        # What players have is protected.
        time.sleep(6)
        knowledge = runtime.RUNTIME / "prod" / "world" / "conduit_knowledge.json"
        found = {thing for things in json.loads(knowledge.read_text(encoding="utf-8")).get("found", {}).values() for thing in things}
        report(results, "the game recorded what the player found", pick in found, str(sorted(found))[:200])
        undo = edit("tin_tools", lambda manifest: manifest["items"]["tin_pickaxe"]["components"].update({"minecraft:max_damage": 200}))
        answer = promote("--lint-only")
        report(results, "changing something a player has is refused", "Players already have" in str(answer.get("reason")), str(answer.get("reason"))[:140])
        undo()

        # Tuning: the real path, on the tool the player holds.
        path = manifest_path("tin_tools")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        tuning.apply(manifest, "items", "tin_pickaxe", "durability", 240, "Testing a change players asked for in the feedback")
        path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        answer = promote()
        report(results, f"a tuned number goes live in under {TUNE_SECONDS} seconds", answer.get("result") == "released" and answer["seconds"] < TUNE_SECONDS,
               f"{answer.get('tier')} in {answer['seconds']}s {answer.get('stages')} {str(answer.get('reason'))[:300]}")
        give(pick)
        good, detail = holds(pick, "minecraft:max_damage=240")
        report(results, "and new stacks have the new number", good, detail)

        # The server icon.
        before = ping()
        report(results, "the server has no icon to begin with", "favicon" not in before, str(before.get("description"))[:80])
        daemon.AGENT_ICON.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), (10, 10, 10)).save(daemon.AGENT_ICON)
        refused = daemon.install_icon()
        report(results, "an icon of the wrong size is refused", refused.get("result") == "blocked", refused.get("reason", ""))
        Image.new("RGB", (64, 64), (10, 10, 10)).save(daemon.AGENT_ICON)
        refused = daemon.install_icon()
        report(results, "a blank icon is refused", refused.get("result") == "blocked", refused.get("reason", ""))
        art = Image.effect_noise((64, 64), 80).convert("RGB")
        art.save(daemon.AGENT_ICON)
        installed = daemon.install_icon()
        report(results, "a good icon is installed", installed.get("result") == "installed", str(installed))
        time.sleep(4)
        after = ping()
        favicon = after.get("favicon", "")
        report(results, "a client's server list now shows it", favicon.startswith("data:image/png;base64,") and len(base64.b64decode(favicon.split(",", 1)[1])) > 100, favicon[:50])
        report(results, "and the player stayed connected through all of it", bot_still_connected() and PLAYER in runtime.rcon("prod", "list", check=False))
    finally:
        bot.terminate()
    return results


if __name__ == "__main__":
    outcome = main()
    print(f"{sum(outcome)} of {len(outcome)} checks passed")
    sys.exit(0 if all(outcome) else 1)
