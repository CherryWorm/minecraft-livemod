#!/usr/bin/env python3
"""How this world's names and pictures reach a real client: a module writing an item's name into a message, an item used up in the
hand that becomes another one, what a recipe's slots show in the recipe book, and what blocks that aren't cubes look like in an
inventory. Start with a world from reset-dev-world.sh and a baseline, and reset it afterwards.

Usage: python3 -m broker.tests.m23_test
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

from PIL import Image

from broker import runtime
from broker.tests.m8_test import Client, PLAYER, SPOT, make_model
from broker.tests.m14_test import report, results

SOURCE = runtime.BROKER / "testsrc-m23"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "names"
PRESS_COLOUR = (0x11, 0x88, 0x99)
SLOT_BACK = (0x8B, 0x8B, 0x8B)
PLANT_GREY = (0x80, 0x80, 0x80)
TOLERANCE = 12
RAW_KEY = re.compile(r"(item|block)\.gm\.")
# The hotbar's first two places in the player's own inventory screen.
FIRST_HOTBAR = (8, 142)
SECOND_HOTBAR = (26, 142)
SLOT_SIZE = 16


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "names"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), (0x77, 0x55, 0x33, 255)).save(textures / "name_token.png")
    Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), (*PLANT_GREY, 255)).save(textures / "name_grass.png")
    # A picture with see-through parts, which is what builders draw for a sculpted block.
    icon = Image.new("RGBA", (SLOT_SIZE, SLOT_SIZE), (0, 0, 0, 0))
    icon.paste((*PRESS_COLOUR, 255), (0, 0, SLOT_SIZE // 2, SLOT_SIZE))
    icon.save(textures / "name_press_icon.png")
    models = target / "assets" / "models"
    models.mkdir(parents=True, exist_ok=True)
    make_model(models / "name_press.bbmodel", "quadruped")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m23-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)


def slot(name, table="items"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"names/{name}"]["slot"]


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def holding(*items):
    """Clears the player's inventory and fills the hotbar from its first place, as (item, count) pairs."""
    rcon("clear", PLAYER)
    for place, (item, count) in enumerate(items):
        rcon("item", "replace", "entity", PLAYER, f"hotbar.{place}", "with", item, count)
    time.sleep(1)


def last(client, pattern):
    found = re.findall(pattern, client.text(), re.MULTILINE)
    return found[-1] if found else None


def colour_at(shots, name, place, gui):
    left, top, scale = gui
    found = sorted(shots.glob(f"*m8_{name}.png"))
    if not found:
        return None
    with Image.open(found[-1]) as image:
        return image.convert("RGB").getpixel((int((left + place[0]) * scale), int((top + place[1]) * scale)))


def near(colour, wanted):
    return colour is not None and all(abs(a - b) <= TOLERANCE for a, b in zip(colour, wanted))


def check_names(client):
    holding((slot("name_reader"), 1))
    client.ask("use")
    found = client.wait(r"\[M8\] chat: NAMES (.*)$", 20).group(1)
    report("a module writing an item's name into a message gets what players call it", "Name Token" in found and not RAW_KEY.search(found), found)
    report("and a block's", "Name Press" in found, found)

    # A name still reaches clients as a translation, which is what lets them show it in their own language.
    holding((slot("name_token"), 1))
    client.ask("held")
    held = last(client, r"\[M8\] holding (.*)$")
    report("an item's own tooltip still shows its name", "Name Token" in held and not RAW_KEY.search(held), held)


def check_hand(client):
    kit, chart = slot("name_kit"), slot("name_chart")
    holding((kit, 1))
    client.ask("use")
    time.sleep(1)
    answer = rcon("data", "get", "entity", PLAYER, "SelectedItem")
    report("using the last of something leaves what it became in the hand", chart in answer, answer)
    client.ask("held")
    held = last(client, r"\[M8\] holding (.*)$")
    report("and the player's client sees that too", "Name Chart" in held, held)

    holding((kit, 2))
    client.ask("use")
    time.sleep(1)
    answer = rcon("data", "get", "entity", PLAYER, "SelectedItem")
    report("with some left over, those stay in the hand", kit in answer and "count: 1" in answer, answer)
    found = rcon("clear", PLAYER, chart, 0)
    report("and what it became is in the inventory", " 1 " in found, found)


def check_recipe_book(client):
    rcon("recipe", "give", PLAYER, "*")
    time.sleep(3)
    client.ask("recipebook")
    recipes = json.loads(last(client, r"\[M8\] recipe book: (.*)$"))
    ours = [recipe for recipe in recipes if any(model.startswith("gm:") for place in recipe for model in place)]
    report("the book shows a recipe using one of this world's items", bool(ours), ours[:3])
    stand_ins = [recipe for recipe in recipes if any("minecraft:trial_key" in place for place in recipe)]
    report("and no slot ever shows the stand-in", not stand_ins, stand_ins[:3])


def check_icons(client, shots):
    press, grass = slot("name_press", "blocks"), slot("name_grass", "blocks")
    holding((press, 1), (grass, 1))
    client.ask("inventory")
    client.ask("guisize")
    left, top, scale = last(client, r"\[M8\] gui (-?\d+) (-?\d+) (\d+(?:\.\d+)?)")
    gui = (int(left), int(top), float(scale))
    client.ask("shot icons")
    client.ask("close")
    corner = colour_at(shots, "icons", (FIRST_HOTBAR[0] + 1, FIRST_HOTBAR[1] + 1), gui)
    report("a sculpted block's icon fills its slot, flat", near(corner, PRESS_COLOUR), corner)
    clear_part = colour_at(shots, "icons", (FIRST_HOTBAR[0] + SLOT_SIZE - 3, FIRST_HOTBAR[1] + SLOT_SIZE // 2), gui)
    report("and what's see-through in it shows the slot behind", near(clear_part, SLOT_BACK), clear_part)
    plant = colour_at(shots, "icons", (SECOND_HOTBAR[0] + SLOT_SIZE // 2, SECOND_HOTBAR[1] + SLOT_SIZE // 2), gui)
    report("a plant coloured by its biome is green when held", plant is not None and plant[1] > plant[0] + TOLERANCE, plant)


def check_jei(client):
    rcon("clear", PLAYER)
    time.sleep(8)
    client.ask("jei")
    shown = json.loads(last(client, r"\[M8\] jei: (.*)$"))
    report("JEI still lists the recipes", any("Name Kit" in line for line in shown), shown[:5])


def main():
    build_source()
    print("releasing the test feature", flush=True)
    release()
    os.environ["CLIENT_TEST_JEI"] = "1"
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    if shots.exists():
        shutil.rmtree(shots)
    client = Client(mods, runtime.REPORTS / "m23-client.log")
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(15)
        x, y, z = SPOT
        # Creative until there's a floor, because the fall from up here can kill a player waiting for the chunks to load.
        rcon("gamemode", "creative", PLAYER)
        rcon("tp", PLAYER, x, y + 5, z, 0, 0)
        time.sleep(3)
        for command in (("difficulty", "peaceful"), ("time", "set", "noon"),
                        ("fill", x - 4, y - 1, z - 4, x + 4, y + 3, z + 4, "minecraft:air"),
                        ("fill", x - 4, y - 1, z - 4, x + 4, y - 1, z + 4, "minecraft:smooth_stone")):
            rcon(*command)
        rcon("tp", PLAYER, x, y, z, 0, 0)
        time.sleep(1)
        rcon("gamemode", "survival", PLAYER)
        check_names(client)
        check_hand(client)
        check_recipe_book(client)
        check_icons(client, shots)
        check_jei(client)
    finally:
        client.stop()

    out = runtime.REPORTS / "m23"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_icons*.png"):
        shutil.copy(path, out)
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
