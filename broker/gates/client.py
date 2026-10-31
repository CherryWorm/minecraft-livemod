"""Shows new content to a real game client and photographs it, so the agent can see its own work."""
import json
import re
import shutil
import subprocess
import time

from PIL import Image, ImageStat

from broker import runtime
from broker.gates import GateFailed

GATE = "client"
CONTAINER = "livingmod-gate-client"
PLAYER = "Player0"
SHOT_TIMEOUT = 90


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


def build_scene(blocks, items):
    """A clean, lit platform with the new blocks in a row, facing the camera."""
    commands = [
        ("gamemode", "creative", PLAYER),
        ("gamerule", "doDaylightCycle", "false"),
        ("weather", "clear"),
        ("time", "set", "noon"),
        ("forceload", "add", "-16", "-16", "16", "16"),
        ("fill", "-10", "119", "-10", "10", "119", "10", "minecraft:smooth_stone"),
        ("fill", "-10", "120", "-10", "10", "130", "10", "minecraft:air"),
        ("tp", PLAYER, "0", "120", "-7", "0", "12"),
        ("clear", PLAYER),
    ]
    for command in commands:
        runtime.rcon("shadow", *command, check=False)
    for index, slot in enumerate(blocks[:15]):
        x = (index % 5) * 2 - 4
        y = 120 + (index // 5) * 2
        runtime.rcon("shadow", "setblock", str(x), str(y), "0", f"gm:{slot}", check=False)
    for slot in items[:9]:
        runtime.rcon("shadow", "give", PLAYER, f"gm:{slot}", "1", check=False)


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


def run_gate(blocks, items, mods_dir, report_dir):
    """Returns the screenshots taken. Skips when there's nothing new to look at."""
    if not blocks and not items:
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
            env={**__import__("os").environ, "MODS_DIR": str(mods_dir), "CLIENT_TEST": "scene",
                 "TEST_SERVER": "localhost:25566"},
        )
    try:
        _wait_log(log, r"\[SCENE\] joined as [A-Za-z0-9_]+$", 300, process)
        time.sleep(2)
        build_scene(blocks, items)
        time.sleep(2)

        shots = []
        for name, time_of_day in (("day", "noon"), ("night", "midnight")):
            runtime.rcon("shadow", "time", "set", time_of_day, check=False)
            time.sleep(1)
            _tell(f"SCENE shot {name}")
            _wait_log(log, rf"\[SCENE\] took {name}$", SHOT_TIMEOUT, process)
            shots.append(name)
        _tell("SCENE done")
        process.wait(timeout=120)
    finally:
        if process.poll() is None:
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
            process.wait(timeout=30)

    saved = []
    for path in sorted(shots_dir.glob("*.png")):
        target = report_dir / path.name
        shutil.copy(path, target)
        saved.append(target)
    if len(saved) < len(shots):
        _fail(f"Expected {len(shots)} screenshots, found {len(saved)}")
    for path in saved:
        if "day" in path.name:
            check_image(path)
    return saved
