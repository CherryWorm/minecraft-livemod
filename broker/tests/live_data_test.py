#!/usr/bin/env python3
"""Live data on a real client: a server module sending values to a client module, only the last of them in a tick and none that haven't changed, one
that starts listening after a value came, and values too long to send. The client module reading where the player is and which way they face and drawing
a real map of the land around them, on a picture it paints itself, and that it can't have pictures that are too big or too many. Then the same for someone
whose companion can't hear these, who gets nothing and loses nothing. Start with a blank world from reset-dev-world.sh, and reset it afterwards.

Usage: python3 -m broker.tests.live_data_test [--again]
"""
import json
import pathlib
import shutil
import subprocess
import sys
import time

from PIL import Image

from broker import runtime, sign
from broker.tests.m8_test import Client, report

SOURCE = runtime.BROKER / "testsrc-livedata"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "livedata"
PLAYER = "Player0"
SPOT = (30, 121, 40)
KEY_J = 13
# The test client's screens are drawn at twice the size of the numbers a module uses.
GUI_SCALE = 2
GREEN = (0, 255, 0)
COLOUR_SQUARE = (20, 20)
LATE_SQUARE = (20, 56)
BARS_FROM = 176
FACING_BAR = 6
HEARD_BAR = 14
REFUSED_MARK = (178, 22)
ARROW_TOP = (192, 34)
ARROW_BOTTOM = (192, 58)
MAP_LEFT = 40
MAP_TOP = 4
MAP_SIZE = 64
# The red patch is this far from where they first stand.
PATCH = 10
MOVED = 20


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "livedata"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    (target / "assets" / "textures").mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (0x20, 0xC0, 0x40, 255)).save(target / "assets" / "textures" / "ld_block.png")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"livedata-{int(time.time())}"],
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
    rcon("tag", PLAYER, "add", f"ld_{name}")
    time.sleep(1)


class Shots:
    def __init__(self, client, folder):
        self.client = client
        self.folder = folder

    def take(self, name):
        self.client.ask(f"shot {name}")
        found = sorted(self.folder.glob(f"*m8_{name}.png"))
        with Image.open(found[-1]) as image:
            return image.convert("RGB")


def pixel(shot, place):
    return shot.getpixel((place[0] * GUI_SCALE, place[1] * GUI_SCALE))


def bar(shot, row):
    """How long a bar is, in a module's numbers."""
    y = row * GUI_SCALE
    x = BARS_FROM * GUI_SCALE
    while x < shot.width and shot.getpixel((x, y)) == GREEN:
        x += 1
    return (x - BARS_FROM * GUI_SCALE) // GUI_SCALE


def on_map(shot, column, row):
    """What the map shows for this many blocks across and down from its north west corner, which it draws at twice the size."""
    return shot.getpixel(((MAP_LEFT + column * 2 + 1) * GUI_SCALE, (MAP_TOP + row * 2 + 1) * GUI_SCALE))


def is_red(colour):
    return colour[0] > 100 and colour[1] < 80 and colour[2] < 80


def prepare_scene():
    x, y, z = SPOT
    rcon("gamemode", "spectator", PLAYER)
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(3)
    for command in (("difficulty", "peaceful"), ("time", "set", "noon"), ("weather", "clear"), ("gamerule", "doDaylightCycle", "false"),
                    ("fill", x - 32, y - 1, z - 32, x + 32, y + 10, z + 32, "minecraft:air"),
                    ("fill", x - 32, y - 1, z - 32, x + 32, y - 1, z + 32, "minecraft:smooth_stone"),
                    ("fill", x + PATCH, y - 1, z + PATCH, x + PATCH + 3, y - 1, z + PATCH + 3, "minecraft:red_wool")):
        rcon(*command)
    time.sleep(3)


def play_values(client, shots, results):
    before = shots.take("before")
    results.append(report("nothing's been said yet", pixel(before, COLOUR_SQUARE) == (0, 0, 0) and bar(before, HEARD_BAR) == 0, str(pixel(before, COLOUR_SQUARE))))

    tag("ff0000")
    shot = shots.take("value")
    results.append(report("a client module hears a value from the server", pixel(shot, COLOUR_SQUARE) == (255, 0, 0), str(pixel(shot, COLOUR_SQUARE))))
    heard = bar(shot, HEARD_BAR)
    tag("ff0000")
    results.append(report("and doesn't hear it again if it hasn't changed", bar(shots.take("same"), HEARD_BAR) == heard))

    tag("twice")
    shot = shots.take("twice")
    results.append(report("two in one tick is only the last", pixel(shot, COLOUR_SQUARE) == (255, 255, 0) and bar(shot, HEARD_BAR) == heard + 4, f"{pixel(shot, COLOUR_SQUARE)} {bar(shot, HEARD_BAR)}"))
    tag("back")
    shot = shots.take("back")
    results.append(report("and changing and changing back says nothing", pixel(shot, COLOUR_SQUARE) == (255, 255, 0) and bar(shot, HEARD_BAR) == heard + 4, f"{pixel(shot, COLOUR_SQUARE)} {bar(shot, HEARD_BAR)}"))

    tag("long")
    results.append(report("too long a value is refused to whoever sent it", pixel(shots.take("long"), COLOUR_SQUARE) == (0, 255, 255)))

    tag("late")
    results.append(report("a value nobody's listening for waits", pixel(shots.take("late_before"), LATE_SQUARE) == (0, 0, 0)))
    client.ask(f"press {KEY_J}")
    time.sleep(1)
    results.append(report("and arrives when someone starts to", pixel(shots.take("late_after"), LATE_SQUARE) == (255, 0, 255)))


def play_view(client, shots, results):
    x, y, z = SPOT
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(2)
    shot = shots.take("map")
    half = MAP_SIZE // 2
    results.append(report("the map shows the land where it really is", is_red(on_map(shot, half + PATCH + 1, half + PATCH + 1)), str(on_map(shot, half + PATCH + 1, half + PATCH + 1))))
    results.append(report("and not where it isn't", not is_red(on_map(shot, half + PATCH + 6, half + PATCH + 1)), str(on_map(shot, half + PATCH + 6, half + PATCH + 1))))
    results.append(report("a picture it painted is the right colours and turned the right way", pixel(shot, ARROW_TOP) == (0, 0, 255) and pixel(shot, ARROW_BOTTOM) == (255, 0, 0), f"{pixel(shot, ARROW_TOP)} {pixel(shot, ARROW_BOTTOM)}"))
    results.append(report("too big a picture and too many of them are refused", pixel(shot, REFUSED_MARK) == GREEN))
    south = bar(shot, FACING_BAR)

    rcon("tp", PLAYER, x + MOVED, y, z, 90, 0)
    time.sleep(2)
    shot = shots.take("map_moved")
    results.append(report("it moves with the player", is_red(on_map(shot, half + PATCH + 1 - MOVED, half + PATCH + 1)) and not is_red(on_map(shot, half + PATCH + 1, half + PATCH + 1)), str(on_map(shot, half + PATCH + 1 - MOVED, half + PATCH + 1))))
    results.append(report("and a module knows which way they're facing", bar(shot, FACING_BAR) == south + 45, f"{south} {bar(shot, FACING_BAR)}"))
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(2)


def play_old_companion(client, shots, results):
    client.ask("novalues", 300)
    time.sleep(3)
    x, y, z = SPOT
    rcon("tp", PLAYER, x, y, z, 0, 0)
    # Long enough for the game's notice about unverified chat, which has nothing to do with this, to go away.
    time.sleep(10)
    before = shots.take("old_before")
    results.append(report("what was said goes when they leave", pixel(before, COLOUR_SQUARE) == (0, 0, 0), str(pixel(before, COLOUR_SQUARE))))
    tag("00ff00")
    results.append(report("a companion too old for this is told nothing", pixel(shots.take("old_after"), COLOUR_SQUARE) == (0, 0, 0)))
    log = runtime.RUNTIME / "prod" / "logs" / "latest.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    results.append(report("and nothing went wrong on the server", "livedata" not in text or "threw" not in text))


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
    client = Client(mods, runtime.REPORTS / "livedata-client.log", {"COMPANION_TEST_KEY": sign.public_key_text()})
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        shots = Shots(client, folder)
        prepare_scene()
        play_values(client, shots, results)
        play_view(client, shots, results)
        play_old_companion(client, shots, results)
        results.append(report("nothing went wrong in the client", "threw an error" not in client.text() and "failed to load" not in client.text() and "wrong thread" not in client.text() and "Game crashed" not in client.text()))
    finally:
        client.stop()
    out = runtime.REPORTS / "livedata"
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
