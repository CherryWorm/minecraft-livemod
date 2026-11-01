#!/usr/bin/env python3
"""Drawing in the world on a real client: a client module drawing a box, the edges of a box, a sheet with a picture, a glowing beam, a billboard
and a sheet each with their own shader, one looking at the world behind it, and see-through copies of blocks. Then a server module doing it with no
client module at all: an effect for everyone near, one that only starts for someone arriving later, a ghost layout taken away again, a streak moving
across the sky, and a shaken camera that doesn't change where a player is facing. Then the same for someone whose companion can't draw these, who
gets nothing and loses nothing. Start with a blank world from reset-dev-world.sh, and reset it afterwards. With --again it plays through once more
on what the last run released, which is enough if no Java has changed. With --friends-mods the test client also has every client mod friends have, so that what
happens here has been tried alongside whatever else is patching the game on their computers.

Usage: python3 -m broker.tests.world_draw_test [--again] [--friends-mods]
"""
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import zipfile

from PIL import Image, ImageDraw

from broker import runtime, sign
from broker.tests.m8_test import Client, report

SOURCE = runtime.BROKER / "testsrc-worlddraw"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "worlddraw"
PLAYER = "Player0"
SPOT = (30, 121, 40)
EYE_HEIGHT = 1.62
# The game's 70, and a tenth more for someone flying, which a spectator always is.
FOV = 77
# Keys are numbered by where they are on the keyboard, starting from A at 4. These two are free in the game and in the mods friends have: O and P open its friends and social screens, and J opens JourneyMap.
KEY_Y = 28
KEY_U = 24
CHANGED = 12
STREAK_PIXELS = 10


def build_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")
    target = SOURCE / "mods" / "genesis" / "features" / "worlddraw"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    (target / "assets" / "textures").mkdir(parents=True, exist_ok=True)
    (target / "assets" / "world").mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (0x20, 0xC0, 0x40, 255)).save(target / "assets" / "textures" / "wd_block.png")
    ring = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((2, 2, 29, 29), outline=(0xFF, 0x80, 0x00, 255), width=6)
    ring.save(target / "assets" / "world" / "ring.png")


def release():
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", f"worlddraw-{int(time.time())}"],
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
    rcon("tag", PLAYER, "add", name)


class Shots:
    """Screenshots, and what's at a place in the world as this player sees it, facing straight along Z with nothing turned."""

    def __init__(self, client, folder):
        self.client = client
        self.folder = folder

    def take(self, name):
        self.client.ask(f"shot {name}")
        found = sorted(self.folder.glob(f"*m8_{name}.png"))
        with Image.open(found[-1]) as image:
            return image.convert("RGB")

    @staticmethod
    def at(shot, x, y, z, standing=SPOT):
        width, height = shot.size
        scale = (height / 2) / math.tan(math.radians(FOV / 2))
        # /tp puts someone in the middle of the block when it's given whole numbers.
        forwards = z - (standing[2] + 0.5)
        return shot.getpixel((round(width / 2 - (x - (standing[0] + 0.5)) / forwards * scale), round(height / 2 - (y - standing[1] - EYE_HEIGHT) / forwards * scale)))


def differs(first, second):
    return max(abs(a - b) for a, b in zip(first, second)) > CHANGED


def changed_share(first, second):
    # The test's own requests show in chat, along the bottom, and JourneyMap's minimap, which never stops changing, is in the top right corner.
    above_chat = (0, 0, first.width * 8 // 10, first.height * 7 // 10)
    small = (first.width // 5, first.height * 7 // 40)
    a, b = list(first.crop(above_chat).resize(small).getdata()), list(second.crop(above_chat).resize(small).getdata())
    return sum(1 for one, other in zip(a, b) if differs(one, other)) / len(a)


def brightest_place(shot):
    """How many pixels are near white, and how far across the picture they are on average. Stars are all dimmer than this."""
    above_chat = shot.crop((0, 0, shot.width * 8 // 10, shot.height * 7 // 10))
    places = [index % above_chat.width for index, pixel in enumerate(above_chat.getdata()) if min(pixel) > 200]
    return len(places), sum(places) // len(places) if places else 0


def prepare_scene():
    x, y, z = SPOT
    rcon("gamemode", "spectator", PLAYER)
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(3)
    for command in (("difficulty", "peaceful"), ("time", "set", "noon"), ("weather", "clear"), ("gamerule", "doDaylightCycle", "false"),
                    ("fill", x - 16, y - 1, z - 10, x + 16, y + 12, z + 20, "minecraft:air"),
                    ("fill", x - 16, y - 1, z - 10, x + 16, y - 1, z + 20, "minecraft:smooth_stone"),
                    # Behind everything, so a change is easy to see, and something for a warp to bend.
                    ("fill", x - 16, y - 1, z + 14, x + 16, y + 12, z + 14, "minecraft:white_concrete"),
                    ("fill", x - 16, y + 5, z + 14, x + 16, y + 5, z + 14, "minecraft:black_concrete"),
                    # In front of what should be hidden, and what shouldn't.
                    ("fill", 33, y + 3, z + 6, 37, y + 6, z + 6, "minecraft:stone")):
        rcon(*command)
    time.sleep(3)


def play_module(client, shots, results):
    before = shots.take("before")
    client.ask(f"press {KEY_Y}")
    time.sleep(1)
    drawn = shots.take("module")
    at = shots.at
    colour = at(drawn, 37, 122, 48)
    results.append(report("a box shows, see-through and the colour it was given", colour[1] < at(before, 37, 122, 48)[1] - 40 and colour[0] > colour[1] and colour[2] > colour[1], str(colour)))
    # An edge is only a few pixels wide, so this allows for being a pixel out.
    results.append(report("the edges of a box show", any(differs(at(drawn, x, 122, 48), at(before, x, 122, 48)) for x in (32.97, 33, 33.03)), str(at(drawn, 33, 122, 48))))
    # Not half way across, which is where the far edge of the box shows from here.
    results.append(report("and not what's inside them", not differs(at(drawn, 34.3, 122, 48), at(before, 34.3, 122, 48)), str(at(drawn, 34.3, 122, 48))))
    ring = [at(drawn, 31, 122, 48), at(before, 31, 122, 48)]
    results.append(report("the middle of a sheet with a ring on it is see-through", not differs(*ring), str(ring)))
    edge = at(drawn, 31, 121.35, 48)
    results.append(report("and its picture shows", differs(edge, at(before, 31, 121.35, 48)), str(edge)))
    results.append(report("a glowing beam shows", differs(at(drawn, 29, 123, 48), at(before, 29, 123, 48)), str(at(drawn, 29, 123, 48))))
    swirl = at(drawn, 27, 122, 48)
    results.append(report("a billboard shows its own shader", swirl[2] > 200 and swirl[0] < 100, str(swirl)))
    gold = at(drawn, 24.5, 121.5, 48)
    results.append(report("a see-through block shows", differs(gold, at(before, 24.5, 121.5, 48)), str(gold)))
    hidden = at(drawn, 36.5, 125.5, 48)
    results.append(report("something behind a wall is hidden", not differs(hidden, at(before, 36.5, 125.5, 48)), str(hidden)))
    through = at(drawn, 33.5, 125.5, 48)
    results.append(report("and one marked to show through walls isn't", through[1] > 200 and through[2] > 200 and through[0] < 80, str(through)))
    results.append(report("a shader that isn't there costs only itself", "module worlddraw" not in client.text() or "disabled" not in client.text()))
    time.sleep(1)
    later = shots.take("module_later")
    results.append(report("a shader moves", differs(at(later, 27.4, 122.4, 48), at(drawn, 27.4, 122.4, 48)) or differs(at(later, 26.5, 121.6, 48), at(drawn, 26.5, 121.6, 48)), f"{at(later, 27.4, 122.4, 48)} {at(drawn, 27.4, 122.4, 48)}"))
    # The black stripe across the wall behind it runs through where the warp is, so it's only bent if the warp can see the world.
    moved = sum(1 for x in (27, 28, 29) for y in range(0, 25) if differs(at(drawn, x, 124.6 + y * 0.1, 48), at(before, x, 124.6 + y * 0.1, 48)))
    # The rest of the sheet is plain white wall from here on, so most places can't look any different, and a sheet that hid the stripe would change a lot more.
    results.append(report("a shader can look at the world behind it", 0 < moved < 30, f"{moved} of 75 places changed"))
    client.ask(f"press {KEY_Y}")
    time.sleep(1)
    results.append(report("and it all goes when the module stops drawing it", changed_share(shots.take("module_off"), before) < 0.01))
    return before


def play_server(client, shots, results, before):
    at = shots.at
    # Everyone near.
    tag("wd_beam")
    time.sleep(1)
    beam = shots.take("server_beam")
    results.append(report("a server module shows a beam with no client module", differs(at(beam, 33, 122.5, 44), at(before, 33, 122.5, 44)), str(at(beam, 33, 122.5, 44))))
    time.sleep(7)
    results.append(report("and it goes when its time is up", changed_share(shots.take("server_beam_gone"), before) < 0.01))

    # A shader, still with no client module.
    tag("wd_shader")
    time.sleep(1)
    shader = shots.take("server_shader")
    results.append(report("a shader on one spot in the world, with no client module", differs(at(shader, 26, 122, 44), at(before, 26, 122, 44)), str(at(shader, 26, 122, 44))))
    time.sleep(6)

    # A layout to build, for one player, which stays until taken away.
    tag("wd_ghost")
    time.sleep(1)
    ghost = shots.take("server_ghost")
    results.append(report("a ghost of one of this world's blocks", differs(at(ghost, 32.5, 121.5, 44), at(before, 32.5, 121.5, 44)), str(at(ghost, 32.5, 121.5, 44))))
    results.append(report("and of one of vanilla's beside it", differs(at(ghost, 30.5, 121.5, 44), at(before, 30.5, 121.5, 44)), str(at(ghost, 30.5, 121.5, 44))))
    time.sleep(6)
    results.append(report("it stays while nothing's said", differs(at(shots.take("server_ghost_stays"), 30.5, 121.5, 44), at(before, 30.5, 121.5, 44))))
    tag("wd_clear")
    time.sleep(1)
    results.append(report("and goes when it's taken away", changed_share(shots.take("server_ghost_gone"), before) < 0.01))

    # Coming near one that's already there.
    tag("wd_far")
    time.sleep(1)
    x, y, z = SPOT
    far = (330, y, z)
    rcon("tp", PLAYER, *far, 0, 0)
    time.sleep(5)
    colour = at(shots.take("server_far"), 330, 123, 44.1, far)
    results.append(report("someone arriving later gets an effect that's still going", colour[0] > 200 and colour[2] < 80, str(colour)))
    rcon("tp", PLAYER, x, y, z, 0, 0)
    time.sleep(3)

    # Across the sky at night.
    rcon("time", "set", "midnight")
    time.sleep(1)
    rcon("tp", PLAYER, x, y, z, 0, -40)
    time.sleep(1)
    tag("wd_streak")
    first = brightest_place(shots.take("server_streak_1"))
    second = brightest_place(shots.take("server_streak_2"))
    # It travels towards the east, which is to the right looking south, by a good way between one picture and the next.
    results.append(report("a streak shows in the night sky", first[0] > STREAK_PIXELS and second[0] > STREAK_PIXELS, f"{first} {second}"))
    results.append(report("and moves across it by itself", second[1] > first[1] + STREAK_PIXELS, f"{first} {second}"))
    rcon("tp", PLAYER, x, y, z, 0, 0)
    rcon("time", "set", "noon")
    time.sleep(9)

    # Shaking.
    client.ask("facing")
    facing = re.findall(r"\[M8\] looking (.*)", client.text())[-1]
    tag("wd_shake")
    shaken = shots.take("server_shake")
    results.append(report("the server can shake a player's view", changed_share(shaken, before) > 0.02, f"{changed_share(shaken, before):.3f} of the picture"))
    client.ask("facing")
    results.append(report("and where they're really facing doesn't change", re.findall(r"\[M8\] looking (.*)", client.text())[-1] == facing))
    time.sleep(7)
    results.append(report("and it stops", changed_share(shots.take("server_shake_done"), before) < 0.01))
    client.ask(f"press {KEY_U}")
    results.append(report("a client module can shake it too", changed_share(shots.take("module_shake"), before) > 0.02))
    time.sleep(7)


def play_old_companion(client, shots, results):
    client.ask("noworld", 300)
    time.sleep(3)
    x, y, z = SPOT
    rcon("tp", PLAYER, x, y, z, 0, 0)
    # Long enough for the game's notice about unverified chat, which has nothing to do with this, to go away.
    time.sleep(10)
    before = shots.take("old_before")
    tag("wd_beam")
    tag("wd_ghost")
    time.sleep(1)
    results.append(report("a companion too old for this is told nothing, and nothing changes", changed_share(shots.take("old_after"), before) < 0.01))
    log = runtime.RUNTIME / "prod" / "logs" / "latest.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    results.append(report("and nothing went wrong on the server", "worlddraw" not in text or "threw" not in text))


def add_friends_mods(folder):
    """Returns what the game should say it's loaded, because a test that didn't really have them would pass just the same."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    subprocess.run(["bash", "infra/fetch-mods.sh", "infra/mods.lock", "client", str(folder)], cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True, timeout=600)
    # A test client asks for these two its own way, and a mod can't load twice.
    os.environ["CLIENT_TEST_JEI"] = "1"
    os.environ["CLIENT_TEST_PATCHOULI"] = "1"
    os.environ["CLIENT_TEST_FRIENDS_MODS"] = "1"
    for path in folder.glob("jei-*.jar"):
        path.unlink()
    names = ["jei", "patchouli"]
    for path in sorted(folder.glob("*.jar")):
        with zipfile.ZipFile(path) as jar:
            names.append(json.loads(jar.read("fabric.mod.json"))["id"])
    print("with", names, flush=True)
    return names


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
    client = Client(mods, runtime.REPORTS / "worlddraw-client.log", {"COMPANION_TEST_KEY": sign.public_key_text()})
    try:
        client.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        shots = Shots(client, folder)
        if wanted_mods:
            missing = [name for name in wanted_mods if not re.search(rf"^\s+- {re.escape(name)} ", client.text(), re.MULTILINE)]
            results.append(report("it's really alongside every mod friends have", not missing, f"{len(wanted_mods)} wanted, missing {missing}"))
        prepare_scene()
        before = play_module(client, shots, results)
        play_server(client, shots, results, before)
        play_old_companion(client, shots, results)
        results.append(report("nothing went wrong in the client", "Stopped drawing in the world" not in client.text() and "wrong thread" not in client.text() and "Game crashed" not in client.text()))
    finally:
        client.stop()
    out = runtime.REPORTS / "worlddraw"
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
