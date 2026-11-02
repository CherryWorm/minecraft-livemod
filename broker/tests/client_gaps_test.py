#!/usr/bin/env python3
"""The smaller client abilities on a real client. A panel with icons on its tabs, rows with a second line and several icons, a filter slot that holds nothing,
an image that starts hidden and a list longer than any chest, all with the real mouse. The same panel for a companion too old to draw those, which gets a plain chest
that does all the same things, a page at a time. A module's key, in the controls menu under its own name, changed there and still changed after leaving and coming
back. And bursts of particles, from a server module and from a client module, that a companion too old for them is never sent. Start with a blank world from
reset-dev-world.sh, and reset it afterwards. With --friends-mods the test client also has every client mod friends have.

Usage: python3 -m broker.tests.client_gaps_test [--again] [--friends-mods]
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
from broker.tests.world_draw_test import add_friends_mods

SOURCE = runtime.BROKER / "testsrc-clientgaps"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "clientgaps"
PLAYER = "Player0"
SPOT = (30, 121, 40)
GEM = (0xE0, 0x20, 0xC0)
KEY_ESCAPE = 41
# Keys are numbered by where they are on the keyboard, starting from A at 4.
KEY_Y = 28
KEY_U = 24
CHANGED = 12
GREEN = (0, 255, 0)
TOLERANCE = 12
# What the specks of each burst look like, and how many pixels of that make it one. Nothing else in the scene has these colours.
ORANGE = (255, 136, 0)
PINK = (255, 32, 255)
CYAN = (0, 255, 255)
SPECK_TOLERANCE = 40
SPECK_PIXELS = 30
# Places on the panel, as feature.json has them.
TAB_ALL = (60, 14)
TAB_ICON_ONLY = (102, 14)
TAB_SHOP = (20, 14)
FIRST_ROW = (100, 40)
SECOND_ROW = (100, 68)
THIRD_ROW = (100, 96)
LAST_EXTRA_ICON = (198, 40)
FILTER = (230, 38)
REVEAL = (30, 124)
GEM_PLACE = (74, 124)
LONG_LIST = (100, 60)
LONG_ROW_HEIGHT = 18
LONG_LIST_TOP = 28
HOTBAR_FIRST = (55, 216)
# Places in the plain chest, in the order feature.json lists them.
CHEST_TABS = 0
CHEST_OFFERS = 3
CHEST_FILTER = 12
CHEST_LONG = 14
CHEST_LONG_ROWS = 9
HOTBAR_IN_CHEST = 27 + 27


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "clientgaps"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    for folder in ("textures", "panels", "world"):
        (target / "assets" / folder).mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (0x20, 0xC0, 0x40, 255)).save(target / "assets" / "textures" / "cg_block.png")
    Image.new("RGBA", (16, 16), (*GEM, 255)).save(target / "assets" / "panels" / "gem.png")
    speck = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for place in range(8):
        speck.putpixel((place, place), (0xFF, 0x20, 0xFF, 255))
        speck.putpixel((7 - place, place), (0xFF, 0x20, 0xFF, 255))
    speck.save(target / "assets" / "world" / "speck.png")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"clientgaps-{int(time.time())}"],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1800,
    )
    if not (runtime.BROKER / "last.json").exists():
        print(result.stderr[-3000:], flush=True)
    promoted = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    print(json.dumps({key: promoted.get(key) for key in ("result", "gate", "tier", "stages")}), flush=True)
    if result.returncode != 0:
        print(promoted.get("reason"), flush=True)
        sys.exit(1)
    return promoted


def rcon(*command):
    return runtime.rcon("prod", *map(str, command), check=False)


def tag(name):
    rcon("tag", PLAYER, "add", f"cg_{name}")
    time.sleep(1)


def said(client, text):
    return client.text().count(f"[M8] chat: CG {text}")


def wait_said(client, text, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if said(client, text):
            return True
        time.sleep(0.25)
    return False


def last(client, pattern):
    found = re.findall(pattern, client.text())
    return found[-1] if found else None


class Shots:
    def __init__(self, client, folder):
        self.client = client
        self.folder = folder

    def take(self, name):
        self.client.ask(f"shot {name}")
        found = sorted(self.folder.glob(f"*m8_{name}.png"))
        with Image.open(found[-1]) as image:
            return image.convert("RGB")


def differs(first, second):
    return max(abs(a - b) for a, b in zip(first, second)) > CHANGED


def pixels_like(shot, colour):
    # Above the chat, where the test's own requests show, and clear of JourneyMap's minimap in the top right corner.
    above_chat = shot.crop((0, 0, shot.width * 8 // 10, shot.height * 7 // 10))
    return sum(1 for pixel in above_chat.getdata() if all(abs(a - b) <= SPECK_TOLERANCE for a, b in zip(pixel, colour)))


def bar(shot, row=6):
    """How long the bar along the top left is, in a module's numbers, with screens drawn at twice their size."""
    y, x = row * 2, 4 * 2
    while x < shot.width and shot.getpixel((x, y)) == GREEN:
        x += 1
    return (x - 4 * 2) // 2


def gui(client):
    client.ask("guisize")
    left, top, scale = last(client, r"\[M8\] gui (-?\d+) (-?\d+) (\d+(?:\.\d+)?)")
    return int(left), int(top), float(scale)


def at(shot, place, where):
    left, top, scale = where
    return shot.getpixel((int((left + place[0]) * scale), int((top + place[1]) * scale)))


def near(colour, wanted):
    return all(abs(a - b) <= TOLERANCE for a, b in zip(colour, wanted))


def mouse(client, place):
    client.ask(f"panelmouse {place[0]} {place[1]}")
    time.sleep(0.5)


def prepare_scene():
    x, y, z = SPOT
    rcon("gamemode", "survival", PLAYER)
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(3)
    for command in (("difficulty", "peaceful"), ("time", "set", "noon"), ("weather", "clear"), ("gamerule", "doDaylightCycle", "false"),
                    ("fill", x - 16, y - 1, z - 10, x + 16, y + 12, z + 20, "minecraft:air"),
                    ("fill", x - 16, y - 1, z - 10, x + 16, y - 1, z + 20, "minecraft:smooth_stone"),
                    ("fill", x - 16, y - 1, z + 14, x + 16, y + 12, z + 14, "minecraft:white_concrete")):
        rcon(*command)
    time.sleep(3)


def play_panel(client, shots, results):
    # Only now, because clearing trees for the scene leaves leaves to decay, and whatever falls from them gets picked up.
    rcon("kill", "@e[type=minecraft:item]")
    rcon("clear", PLAYER)
    rcon("give", PLAYER, "minecraft:diamond", 5)
    time.sleep(1)
    tag("open")
    client.ask("screen")
    results.append(report("a panel with newer things on it opens as a panel", last(client, r"\[M8\] the screen is (\w+)") == "PanelScreen", str(last(client, r"\[M8\] the screen is (\w+)"))))
    where = gui(client)
    first = shots.take("panel")
    results.append(report("an image that starts hidden isn't there", not near(at(first, GEM_PLACE, where), GEM), str(at(first, GEM_PLACE, where))))
    mouse(client, REVEAL)
    results.append(report("until a module shows it", near(at(shots.take("panel_revealed"), GEM_PLACE, where), GEM)))

    mouse(client, FIRST_ROW)
    results.append(report("a row with two lines and more icons is still a row", wait_said(client, "clicked offers row 0")))
    mouse(client, SECOND_ROW)
    results.append(report("and one that's turned off does nothing", not wait_said(client, "clicked offers row 1", 2)))
    mouse(client, THIRD_ROW)
    results.append(report("and it knows which row", wait_said(client, "clicked offers row 2")))
    client.ask(f"panelhover {LAST_EXTRA_ICON[0]} {LAST_EXTRA_ICON[1]}")
    shots.take("panel_icon_tooltip")

    mouse(client, HOTBAR_FIRST)
    mouse(client, FILTER)
    results.append(report("a filter slot takes what's being held", wait_said(client, "filter want is minecraft:diamond x1 holding 5 and it reads 1"), "x1 holding 5"))
    client.ask("menu")
    shown = last(client, r"\[M8\] menu holds (.*)") or ""
    results.append(report("and nobody loses anything to it", shown.endswith("carried=5"), shown[-20:]))
    client.ask("panelhover 240 100")
    filtered = shots.take("panel_filter")
    results.append(report("it shows what it's set to", differs(at(filtered, FILTER, where), at(first, FILTER, where)), str(at(filtered, FILTER, where))))
    mouse(client, HOTBAR_FIRST)
    mouse(client, FILTER)
    results.append(report("and an empty hand clears it", wait_said(client, "filter want is nothing x0 holding 0 and it reads 0")))

    mouse(client, TAB_ICON_ONLY)
    results.append(report("a tab that's only an icon is still a tab", wait_said(client, "clicked only row 0")))
    mouse(client, TAB_ALL)
    results.append(report("and so is one with an icon and words", wait_said(client, "clicked long row 0")))
    shots.take("panel_long")
    client.ask(f"panelscroll {LONG_LIST[0]} {LONG_LIST[1]} -150")
    shots.take("panel_long_scrolled")
    mouse(client, (LONG_LIST[0], LONG_LIST_TOP + LONG_ROW_HEIGHT // 2))
    results.append(report("a row further down than any chest could hold can be clicked", wait_said(client, "clicked all row 150")))
    client.ask(f"press {KEY_ESCAPE}")
    time.sleep(1)


def play_plain_chest(client, shots, results):
    client.ask("nonewerpanels", 300)
    time.sleep(3)
    x, y, z = SPOT
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(2)
    tag("open")
    client.ask("screen")
    results.append(report("a companion too old for them gets a plain chest", last(client, r"\[M8\] the screen is (\w+)") == "ContainerScreen", str(last(client, r"\[M8\] the screen is (\w+)"))))
    shots.take("chest")
    before = said(client, "clicked offers row 0")
    client.ask(f"click {CHEST_OFFERS}")
    time.sleep(1)
    results.append(report("whose rows work", said(client, "clicked offers row 0") == before + 1))
    client.ask(f"click {HOTBAR_IN_CHEST}")
    client.ask(f"click {CHEST_FILTER}")
    results.append(report("and whose filter slot works", wait_said(client, "filter want is minecraft:diamond x1 holding 5 and it reads 1"), ""))
    client.ask(f"click {HOTBAR_IN_CHEST}")
    client.ask(f"click {CHEST_TABS + 1}")
    time.sleep(1)
    shots.take("chest_long")
    client.ask(f"click {CHEST_LONG + CHEST_LONG_ROWS + 1}")
    time.sleep(1)
    shots.take("chest_long_next")
    before = said(client, f"clicked all row {CHEST_LONG_ROWS}")
    client.ask(f"click {CHEST_LONG}")
    time.sleep(1)
    results.append(report("and a long list comes a page at a time", said(client, f"clicked all row {CHEST_LONG_ROWS}") == before + 1, str(before)))
    client.ask(f"click {CHEST_LONG + CHEST_LONG_ROWS}")
    time.sleep(1)
    before = said(client, "clicked all row 0")
    client.ask(f"click {CHEST_LONG}")
    time.sleep(1)
    results.append(report("forwards and back", said(client, "clicked all row 0") == before + 1))
    client.ask("closemenu")
    time.sleep(1)


def play_keys(client, shots, results):
    client.ask("nokeys")
    results.append(report("a module's key is among the game's", "key.gm." in (last(client, r"\[M8\] module keys (.*)") or ""), str(last(client, r"\[M8\] module keys (.*)"))))
    start = bar(shots.take("key_before"))
    client.ask(f"press {KEY_Y}")
    time.sleep(1)
    shot = shots.take("key_pressed")
    results.append(report("and pressing it reaches the module", bar(shot) > start, f"{start} {bar(shot)}"))
    pressed = bar(shot)
    client.ask("controls")
    shots.take("controls")
    client.ask(f"rebind {KEY_U}")
    time.sleep(1)
    shots.take("controls_rebound")
    client.ask("closescreen")
    time.sleep(1)
    client.ask(f"press {KEY_Y}")
    time.sleep(1)
    results.append(report("once it's changed, the old key does nothing", bar(shots.take("key_old")) == pressed))
    client.ask(f"press {KEY_U}")
    time.sleep(1)
    moved = bar(shots.take("key_new"))
    results.append(report("and the new one works", moved > pressed, f"{pressed} {moved}"))
    # Long enough for the next tick to notice, and to save it.
    time.sleep(1)
    client.ask("rejoin", 300)
    time.sleep(3)
    x, y, z = SPOT
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(2)
    client.ask(f"press {KEY_U}")
    time.sleep(1)
    results.append(report("and it's still changed after coming back", bar(shots.take("key_back")) > 0))
    client.ask("nokeys")


def play_bursts(client, shots, results):
    x, y, z = SPOT
    rcon("gamemode", "spectator", PLAYER)
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(2)
    before = shots.take("burst_before")
    results.append(report("there's nothing like a burst there to begin with", pixels_like(before, ORANGE) == 0 and pixels_like(before, PINK) == 0, f"{pixels_like(before, ORANGE)} {pixels_like(before, PINK)}"))
    tag("burst")
    orange = pixels_like(shots.take("burst"), ORANGE)
    results.append(report("a burst from a server module shows", orange >= SPECK_PIXELS, f"{orange} pixels"))
    time.sleep(8)
    gone = pixels_like(shots.take("burst_gone"), ORANGE)
    results.append(report("and goes by itself", gone == 0, f"{gone} pixels"))
    tag("pictures")
    pink = pixels_like(shots.take("burst_pictures"), PINK)
    results.append(report("and it can be a picture of your own", pink >= SPECK_PIXELS, f"{pink} pixels"))
    time.sleep(8)
    client.ask(f"press {KEY_U}")
    cyan = pixels_like(shots.take("burst_module"), CYAN)
    results.append(report("and a client module can show one too", cyan >= SPECK_PIXELS, f"{cyan} pixels"))
    time.sleep(8)


def play_old_bursts(client, shots, results):
    client.ask("noburst", 300)
    time.sleep(3)
    x, y, z = SPOT
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(2)
    tag("burst")
    orange = pixels_like(shots.take("old_after"), ORANGE)
    results.append(report("a companion too old for a burst isn't sent one", orange == 0, f"{orange} pixels"))
    client.ask("screen")
    time.sleep(2)
    results.append(report("and stays connected", "Lost connection" not in client.text() and "Disconnected" not in client.text()))


def main():
    if "--again" in sys.argv:
        promoted = json.loads((runtime.BROKER / "passed_gates.json").read_text(encoding="utf-8"))
    else:
        build_source()
        print("building and releasing the test feature", flush=True)
        promoted = release()
    results = []

    with sign._locked():
        sign._load_key()
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    shutil.rmtree(mods / "companion" / "build" / "run" / "clientGameTest" / "config" / "companion", ignore_errors=True)
    folder = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    wanted_mods = add_friends_mods(mods / "friends-mods") if "--friends-mods" in sys.argv else []
    client = Client(mods, runtime.REPORTS / "clientgaps-client.log", {"COMPANION_TEST_KEY": sign.public_key_text()})
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        shots = Shots(client, folder)
        if wanted_mods:
            missing = [name for name in wanted_mods if not re.search(rf"^\s+- {re.escape(name)} ", client.text(), re.MULTILINE)]
            results.append(report("it's really alongside every mod friends have", not missing, f"{len(wanted_mods)} wanted, missing {missing}"))
        prepare_scene()
        play_panel(client, shots, results)
        play_plain_chest(client, shots, results)
        play_keys(client, shots, results)
        play_bursts(client, shots, results)
        play_old_bursts(client, shots, results)
        text = client.text()
        results.append(report("nothing went wrong in the client", "threw an error" not in text and "failed to load" not in text and "wrong thread" not in text and "Stopped drawing" not in text and "Game crashed" not in text))
    finally:
        client.stop()
    results.append(report("and the game closed cleanly at the end", "has crashed" not in client.text()))
    out = runtime.REPORTS / "clientgaps"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in folder.glob("*m8_*.png"):
        shutil.copy(path, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
