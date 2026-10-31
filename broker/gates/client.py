"""Shows new content to a real game client and photographs it, so the agent can see its own work."""
import json
import re
import shutil
import subprocess
import time

from PIL import Image, ImageDraw, ImageStat

from broker import runtime
from broker.gates import GateFailed

GATE = "client"
CONTAINER = "livingmod-gate-client"
PLAYER = "Player0"
SHOT_TIMEOUT = 90
REFERENCE_BLOCKS = ("minecraft:stone", "minecraft:iron_ore", "minecraft:oak_planks", "minecraft:grass_block", "minecraft:copper_block")
# Each frame is a real screenshot, so this keeps a release with new mobs from taking much longer than one without.
FILMED_MOBS = 2
FILMED_ANIMATIONS = ("walk", "attack", "hurt", "death")
FILMED_PHASES = (0.0, 0.25, 0.5, 0.75)
EYE_HEIGHT = 1.62


def _fail(message):
    raise GateFailed(GATE, message)


def _tell(text):
    payload = json.dumps({"text": text})
    runtime.rcon("shadow", "tellraw", PLAYER, payload)


def _wait_log(log, pattern, seconds, process):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        if re.search(pattern, text, re.MULTILINE):
            return
        if re.search(r"BUILD FAILED|Game crashed|\.java:\d+: error:", text):
            _fail(f"The test client failed:\n{text[-1200:]}")
        if process.poll() is not None:
            _fail(f"The test client stopped while waiting for {pattern}:\n{text[-1200:]}")
        time.sleep(0.25)
    _fail(f"Timed out waiting for the test client: {pattern}")


def build_scene(blocks, items, mobs=()):
    """A clean, lit platform with new content facing the camera, and vanilla blocks behind it to compare with."""
    commands = [
        ("gamemode", "spectator", PLAYER),
        ("gamerule", "doDaylightCycle", "false"),
        ("gamerule", "doMobSpawning", "false"),
        ("weather", "clear"),
        ("time", "set", "noon"),
        ("forceload", "add", "-16", "-16", "16", "16"),
        ("fill", "-10", "119", "-10", "10", "119", "10", "minecraft:smooth_stone"),
        ("fill", "-10", "120", "-10", "10", "130", "10", "minecraft:air"),
        ("kill", "@e[type=!player]"),
        ("tp", PLAYER, "0", "121", "-5", "0", "10"),
    ]
    for command in commands:
        runtime.rcon("shadow", *command, check=False)
    for index, block in enumerate(REFERENCE_BLOCKS):
        runtime.rcon("shadow", "setblock", str(index * 2 - 4), "120", "3", block, check=False)
    for index, slot in enumerate(blocks[:15]):
        x = (index % 5) * 2 - 4
        y = 120 + (index // 5) * 2
        runtime.rcon("shadow", "setblock", str(x), str(y), "0", f"gm:{slot}", check=False)
    # Items hang in a row above the blocks, clear of them. A dropped item spins and can be caught edge-on, which shows
    # nothing, so these always face the camera.
    shown = items[:9]
    for index, slot in enumerate(shown):
        data = '{item:{id:"gm:%s",count:1},billboard:"center"}' % slot
        x = (index - (len(shown) - 1) / 2) * 1.2
        runtime.rcon("shadow", "summon", "minecraft:item_display", str(x), "123.4", "1", data, check=False)
    for index, slot in enumerate(mobs[:5]):
        runtime.rcon("shadow", "summon", f"gm:{slot}", str(index * 2 - 4), "120", "-1", "{NoAI:1b,PersistenceRequired:1b}", check=False)


def check_image(path):
    """Catches failures anyone would see: a black frame, or the purple and black missing-texture checks."""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        centre = rgb.crop((width // 6, height // 6, width * 5 // 6, height * 5 // 6))
        pixels = list(centre.getdata())
        magenta = sum(1 for r, g, b in pixels if r > 200 and g < 40 and b > 200)
        if magenta / len(pixels) > 0.002:
            _fail(f"{path.name} shows the missing-texture pattern on {magenta / len(pixels):.1%} of the frame.")
        if max(ImageStat.Stat(centre).mean) < 8:
            _fail(f"{path.name} is almost completely black, so nothing rendered.")


def film(mobs, log, process):
    """Holds new mobs at set points in their animations, on the real client, for a reviewer to judge how they move."""
    filmed = {}
    definitions = json.loads((runtime.RUNTIME / "shadow" / "config" / "conduit" / "mobs.json").read_text(encoding="utf-8"))
    for slot in mobs[:FILMED_MOBS]:
        # Close enough that it fills the frame, whatever its size, with the camera level with the middle of it.
        height = max(0.5, min(float(definitions.get(f"gm:{slot}", {}).get("height", 1)), 8))
        back = 1 - max(2.2, height * 1.5 + 0.8)
        # A mob with a death animation stays around while it plays, so it's moved out of shot first.
        runtime.rcon("shadow", "tp", "@e[type=!player]", "0", "-100", "0", check=False)
        runtime.rcon("shadow", "kill", "@e[type=!player]", check=False)
        runtime.rcon("shadow", "tp", PLAYER, "0", str(round(120 + height / 2 - EYE_HEIGHT, 2)), str(round(back, 2)), "0", "0", check=False)
        runtime.rcon("shadow", "summon", f"gm:{slot}", "0", "120", "1", "{NoAI:1b,PersistenceRequired:1b,Rotation:[150f,0f]}", check=False)
        time.sleep(1)
        rows = filmed.setdefault(slot, {})
        for animation in FILMED_ANIMATIONS:
            for index, phase in enumerate(FILMED_PHASES):
                answer = runtime.rcon("shadow", "conduit", "pose", f"@e[type=gm:{slot}]", animation, str(phase), check=False)
                if answer.endswith(": 0") or "Posed" not in answer:
                    break
                name = f"frame_{slot}_{animation}_{index}"
                _tell(f"SCENE shot {name}")
                _wait_log(log, rf"\[SCENE\] took {name}$", SHOT_TIMEOUT, process)
                rows.setdefault(animation, []).append(name)
    return filmed


def motion_sheet(slot, rows, shots_dir, out):
    """One image per mob, with a row for each animation, which is far easier to judge than a pile of separate shots."""
    sheet = None
    for row, (animation, names) in enumerate(rows.items()):
        for column, name in enumerate(names):
            found = sorted(shots_dir.glob(f"*scene_{name}.png"))
            if not found:
                continue
            with Image.open(found[-1]) as image:
                frame = image.convert("RGB")
            width, height = frame.size
            frame = frame.crop(((width - height) // 2, 0, (width + height) // 2, height)).resize((height // 2, height // 2))
            if sheet is None:
                sheet = Image.new("RGB", (frame.width * len(FILMED_PHASES), (frame.height + 16) * len(rows)), (30, 30, 34))
            sheet.paste(frame, (column * frame.width, row * (frame.height + 16) + 16))
            if column == 0:
                ImageDraw.Draw(sheet).text((4, row * (frame.height + 16) + 2), f"{animation}, across the animation from left to right", fill=(230, 230, 230))
    if sheet is None:
        return None
    target = out / f"motion_{slot}.png"
    sheet.save(target)
    return target


def run_gate(blocks, items, mods_dir, report_dir, mobs=(), client_modules=False):
    """Returns the screenshots taken. Skips when there's nothing new to look at."""
    if not blocks and not items and not mobs and not client_modules:
        return []
    report_dir.mkdir(parents=True, exist_ok=True)
    log = report_dir / "client.log"
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
    shots_dir = mods_dir / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    if shots_dir.exists():
        shutil.rmtree(shots_dir)

    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            ["./scripts/stack.sh", "--profile", "tools", "run", "--rm", "-T", "--name", CONTAINER, "testclient",
             "./gradlew", "--no-daemon", "--console=plain", ":companion:runClientGameTest"],
            cwd=runtime.REPO, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            # Nothing's signed until a release is really going out, so this client takes unsigned modules. It's
            # the test's own copy of the game, and it still refuses anything that fails the code check.
            env={**__import__("os").environ, "MODS_DIR": str(mods_dir), "CLIENT_TEST": "scene",
                 "TEST_SERVER": "localhost:25566", "COMPANION_ALLOW_UNSIGNED": "true"},
        )
    try:
        _wait_log(log, r"\[SCENE\] joined as [A-Za-z0-9_]+$", 300, process)
        time.sleep(2)
        build_scene(blocks, items, mobs)
        time.sleep(2)

        shots = []
        scenes = [("day", "noon"), ("night", "midnight")]
        if client_modules:
            time.sleep(3)
            scenes.append(("hud", "noon"))
        for name, time_of_day in scenes:
            runtime.rcon("shadow", "time", "set", time_of_day, check=False)
            time.sleep(1)
            _tell(f"SCENE shot {name}")
            _wait_log(log, rf"\[SCENE\] took {name}$", SHOT_TIMEOUT, process)
            shots.append(name)
        runtime.rcon("shadow", "time", "set", "noon", check=False)
        filmed = film(mobs, log, process)
        _tell("SCENE done")
        process.wait(timeout=120)
    finally:
        if process.poll() is None:
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
            process.wait(timeout=30)

    saved = []
    for path in sorted(shots_dir.glob("*.png")):
        if "scene_frame_" in path.name:
            continue
        target = report_dir / path.name
        shutil.copy(path, target)
        saved.append(target)
    if len(saved) < len(shots):
        _fail(f"Expected {len(shots)} screenshots, found {len(saved)}")
    for path in saved:
        if "day" in path.name:
            check_image(path)
    for slot, rows in filmed.items():
        sheet = motion_sheet(slot, rows, shots_dir, report_dir)
        if sheet:
            saved.append(sheet)
    return saved
