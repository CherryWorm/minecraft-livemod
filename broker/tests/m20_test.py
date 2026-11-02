#!/usr/bin/env python3
"""A panel on a real client: a machine's own screen with its art, real item slots, a button, a bar that moves while it's open, tabs, a
list and a text field, all with the real mouse and keyboard. Then a shift-click into a slot that hands back what it's given, and the same
panel for someone whose companion can't draw it, who gets a plain chest that does the same things. And the release gate's own photograph
of it. Start with a blank world from reset-dev-world.sh, and reset it afterwards. With --again it plays through once more on what the last run released, which is enough if no Java has changed.

Usage: python3 -m broker.tests.m20_test [--again]
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

from PIL import Image

from broker import runtime, sign
from broker.tests.m8_test import Client, report

SOURCE = runtime.BROKER / "testsrc-m20"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "panels"
PLAYER = "Player0"
SPOT = (40, 120, 40)
BADGE = (0x11, 0x88, 0x99)
PANEL = (0xC6, 0xC6, 0xC6)
BAR = (0xFF, 0x00, 0xFF)
TRACK = (0x8B, 0x8B, 0x8B)
TOLERANCE = 12
KEY_ESCAPE = 41
# Where things are in the fixture's panel.
FIRST_SLOT = (56, 35)
HOTBAR = (8, 142)
BAR_LEFT = (82, 44)
BAR_RIGHT = (101, 44)
START = (20, 58)
BADGE_PLACE = (160, 12)
EMPTY_PLACE = (140, 62)
TALK_TAB = (100, 10)
ROW_HEIGHT = 18
ROWS = (20, 22 + ROW_HEIGHT // 2)
FIELD = (130, 76)
# Its places in the plain chest, in the order the feature lists them: two slots, bar, label, then these.
START_PLACE = 4
TABS_PLACE = 5
# After its two rows of chest, and the player's three rows.
HOTBAR_PLACE = 45
# The same on the panel with one slot, which has one row of chest.
SIEVE_HOTBAR_PLACE = 36
GIVEN = "minecraft:iron_ingot"
# A server that's hung doesn't answer at all until its watchdog kills it, which takes a minute.
ANSWERS_WITHIN_SECONDS = 20


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "panels"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    (target / "assets" / "textures").mkdir(parents=True, exist_ok=True)
    (target / "assets" / "panels").mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (0x88, 0x88, 0x88, 255)).save(target / "assets" / "textures" / "panel_block.png")
    Image.new("RGBA", (16, 16), (*BADGE, 255)).save(target / "assets" / "panels" / "kiln_badge.png")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"m20-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)
    return promoted


def slot(name, table="blocks"):
    ledger = json.loads((runtime.HISTORY / runtime.load_state()["current"] / "registry-ledger.json").read_text(encoding="utf-8"))
    return "gm:" + ledger[table][f"panels/{name}"]["slot"]


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def last(client, pattern):
    found = re.findall(pattern, client.text())
    return found[-1] if found else None


def said(client, text):
    return client.text().count(f"chat: PAN {text}")


def wait_said(client, text, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if said(client, text):
            return True
        time.sleep(0.25)
    return False


def mouse(client, place):
    client.ask(f"panelmouse {place[0]} {place[1]}")


def colour_at(shots, name, place, gui):
    left, top, scale = gui
    found = sorted(shots.glob(f"*m8_{name}.png"))
    if not found:
        return None
    with Image.open(found[-1]) as image:
        return image.convert("RGB").getpixel((int((left + place[0]) * scale), int((top + place[1]) * scale)))


def near(colour, wanted):
    return colour is not None and all(abs(a - b) <= TOLERANCE for a, b in zip(colour, wanted))


def gui(client):
    client.ask("guisize")
    left, top, scale = last(client, r"\[M8\] gui (-?\d+) (-?\d+) (\d+(?:\.\d+)?)")
    return int(left), int(top), float(scale)


def play_panel(client, results, shots, kiln):
    x, y, z = SPOT
    # Nothing can be placed until the chunks there are loaded.
    # Creative for now, because there is nothing under them yet, and a long enough fall would kill them.
    rcon("gamemode", "creative", PLAYER)
    rcon("tp", PLAYER, x, y + 5, z, 0, 0)
    time.sleep(3)
    for command in (("difficulty", "peaceful"), ("time", "set", "noon"),
                    ("fill", x - 4, y - 1, z - 4, x + 4, y + 3, z + 4, "minecraft:air"),
                    ("fill", x - 4, y - 1, z - 4, x + 4, y - 1, z + 4, "minecraft:smooth_stone")):
        rcon(*command)
    rcon("setblock", x, y, z + 2, kiln)
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(1)
    rcon("gamemode", "survival", PLAYER)
    rcon("clear", PLAYER)
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", "minecraft:iron_ingot", 3)
    time.sleep(1)

    client.ask(f"useblock {x} {y} {z + 2}")
    time.sleep(1)
    client.ask("screen")
    results.append(report("a machine's panel opens as its own screen", last(client, r"\[M8\] the screen is (\w+)") == "PanelScreen", str(last(client, r"\[M8\] the screen is (\w+)"))))
    at = gui(client)
    client.ask("shot panel_cold")
    colour = colour_at(shots, "panel_cold", BADGE_PLACE, at)
    results.append(report("it shows the feature's own art", near(colour, BADGE), str(colour)))
    colour = colour_at(shots, "panel_cold", EMPTY_PLACE, at)
    results.append(report("and with none for its background it's the game's own grey", near(colour, PANEL), str(colour)))
    colour = colour_at(shots, "panel_cold", BAR_LEFT, at)
    results.append(report("a bar starts where the module said", near(colour, TRACK), str(colour)))

    # Real item slots, moved where the feature wanted them.
    mouse(client, (HOTBAR[0] + 8, HOTBAR[1] + 8))
    mouse(client, (FIRST_SLOT[0] + 8, FIRST_SLOT[1] + 8))
    results.append(report("items go into a slot wherever the panel put it", wait_said(client, "holds 3 minecraft:iron_ingot")))
    answer = rcon("data", "get", "block", x, y, z + 2, "Items")
    results.append(report("and they're really in the machine", "iron_ingot" in answer, answer[:120]))

    # A button, and what the module does about it reaching the screen while it's open.
    mouse(client, START)
    results.append(report("a button reaches the module", wait_said(client, "clicked start row 0")))
    client.ask("shot panel_warming")
    left, right = colour_at(shots, "panel_warming", BAR_LEFT, at), colour_at(shots, "panel_warming", BAR_RIGHT, at)
    results.append(report("a bar moves while it's open", near(left, BAR) and near(right, TRACK), f"{left} {right}"))
    time.sleep(9)
    client.ask("shot panel_hot")
    right = colour_at(shots, "panel_hot", BAR_RIGHT, at)
    results.append(report("and it keeps moving", near(right, BAR), str(right)))
    mouse(client, START)
    time.sleep(1)
    results.append(report("a button the module disabled does nothing", said(client, "clicked start row 0") == 1, str(said(client, "clicked start row 0"))))

    # A shift-click only goes where an item may go, which isn't a machine's output, even one holding the same thing.
    rcon("item", "replace", "block", x, y, z + 2, "container.1", "with", "minecraft:iron_ingot", 1)
    rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", "minecraft:iron_ingot", 2)
    time.sleep(1)
    client.ask(f"click {HOTBAR_PLACE} shift")
    time.sleep(1)
    answer = rcon("data", "get", "block", x, y, z + 2, "Items")
    results.append(report("a shift-click goes in the input and never onto an output", "count: 5, Slot: 0b" in answer and "count: 1, Slot: 1b" in answer, answer[:160]))

    # Pages, a list and something to type in.
    mouse(client, TALK_TAB)
    results.append(report("a tab reaches the module", wait_said(client, "clicked talk row 0")))
    client.ask("shot panel_talk")
    colour = colour_at(shots, "panel_talk", BAR_LEFT, at)
    results.append(report("and what's on another page goes away", not near(colour, BAR), str(colour)))
    mouse(client, ROWS)
    results.append(report("a row of a list reaches the module", wait_said(client, "clicked offers row 0")))
    mouse(client, (ROWS[0], ROWS[1] + ROW_HEIGHT))
    mouse(client, (ROWS[0], ROWS[1] + ROW_HEIGHT * 2))
    results.append(report("and it knows which row", wait_said(client, "clicked offers row 2")))
    results.append(report("a row that's turned off does nothing", said(client, "clicked offers row 1") == 0))
    mouse(client, FIELD)
    client.ask("type hello")
    results.append(report("typing reaches the module", wait_said(client, "typed hello")))
    client.ask("screen")
    results.append(report("and the letters don't work the game's keys while typing", last(client, r"\[M8\] the screen is (\w+)") == "PanelScreen"))
    client.ask("shot panel_typed")
    client.ask(f"press {KEY_ESCAPE}")
    results.append(report("escape closes it, and the module hears", wait_said(client, "closed")))
    client.ask("screen")
    results.append(report("and it's gone", last(client, r"\[M8\] the screen is (\w+)") == "none"))
    answer = rcon("data", "get", "block", x, y, z + 2, "Items")
    results.append(report("what was in the machine stays there", "iron_ingot" in answer, answer[:120]))


def carried(item):
    found = re.search(r"Found (\d+)", rcon("clear", PLAYER, item, 0))
    return int(found.group(1)) if found else 0


def carries_on(since):
    started = time.monotonic()
    answer = rcon("list")
    took = time.monotonic() - started
    watchdog = "A single server tick took" in runtime.logs_since("prod", since)
    return "players online" in answer and took < ANSWERS_WITHIN_SECONDS and not watchdog, f"{took:.0f}s, {answer[:60]}"


def play_giving_back(client, results, sieve):
    """The game repeats a shift-click for as long as the menu says something moved, so a slot that hands back what it's given could hang the
    server until its watchdog killed it, and the last of a stack could vanish. Says whether the server's still there to carry on with."""
    x, y, z = SPOT
    rcon("setblock", x, y, z - 2, sieve)
    since = runtime.utc_now()
    # The single item first, because going wrong the other way ends the test.
    for count, what in ((1, "a single item"), (3, "a stack")):
        rcon("clear", PLAYER)
        rcon("item", "replace", "entity", PLAYER, "hotbar.0", "with", GIVEN, count)
        time.sleep(1)
        client.ask(f"useblock {x} {y} {z - 2}")
        time.sleep(1)
        before = said(client, f"remembers {GIVEN}")
        client.ask(f"click {SIEVE_HOTBAR_PLACE} shift")
        time.sleep(1)
        alive, shown = carries_on(since)
        results.append(report(f"shift-clicking {what} into a slot that hands it back leaves the server running, with no watchdog", alive, shown))
        if not alive:
            return False
        results.append(report("and the slot really was given it", said(client, f"remembers {GIVEN}") > before))
        found = carried(GIVEN)
        results.append(report("and the player still has all of it", found == count, str(found)))
        client.ask("held")
        held = last(client, r"\[M8\] holding (\d+)")
        results.append(report("and their client shows all of it", held == str(count), str(held)))
        client.ask("closemenu")
    return True


def play_without_companion(client, results):
    x, y, z = SPOT
    client.ask("nopanels", 300)
    time.sleep(3)
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(1)
    client.ask(f"useblock {x} {y} {z + 2}")
    time.sleep(1)
    client.ask("screen")
    results.append(report("a companion that can't draw panels gets a plain chest", last(client, r"\[M8\] the screen is (\w+)") == "ContainerScreen", str(last(client, r"\[M8\] the screen is (\w+)"))))
    client.ask("shot panel_chest")
    client.ask("menu")
    shown = last(client, r"\[M8\] menu holds (.*)") or ""
    results.append(report("with the same items in it", "0=5xminecraft:iron_ingot" in shown, shown[:200]))
    before = said(client, "clicked start row 0")
    client.ask(f"click {START_PLACE}")
    time.sleep(1)
    results.append(report("and clicking a button's picture does what the button does", said(client, "clicked start row 0") == before + 1))
    client.ask(f"click {TABS_PLACE + 1}")
    time.sleep(1)
    results.append(report("and a tab's", said(client, "clicked talk row 0") >= 2))
    client.ask("menu")
    shown = last(client, r"\[M8\] menu holds (.*)") or ""
    results.append(report("and a picture can't be taken out", shown.endswith("carried=0"), shown[-40:]))
    client.ask("closemenu")


def main():
    if "--again" in sys.argv:
        promoted = json.loads(max((runtime.BROKER / "passed_gates").glob("*.json"), key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8"))
    else:
        build_source()
        print("building and releasing the test feature", flush=True)
        promoted = release()
    results = []
    photographs = [pathlib.Path(path).name for path in promoted.get("screenshots", [])]
    results.append(report("the release gate photographed the panel, for whoever reviews it", any("panel_panels_kiln" in name for name in photographs), str(photographs)))
    kiln = slot("panel_kiln")

    with sign._locked():
        sign._load_key()
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    shutil.rmtree(mods / "companion" / "build" / "run" / "clientGameTest" / "config" / "companion", ignore_errors=True)
    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    client = Client(mods, runtime.REPORTS / "m20-client.log", {"COMPANION_TEST_KEY": sign.public_key_text()})
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        play_panel(client, results, shots, kiln)
        if play_giving_back(client, results, slot("panel_sieve")):
            play_without_companion(client, results)
        results.append(report("nothing went wrong in the client", "PanelScreen." not in client.text() and "PanelClient." not in client.text()))
    finally:
        client.stop()
    out = runtime.REPORTS / "m20"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_*.png"):
        shutil.copy(path, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
