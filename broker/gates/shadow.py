"""Tries a release on a copy of the live world, with real boots and a real client login."""
import re
import shutil
import subprocess
import sys
import time

from broker import runtime
from broker.gates import GateFailed

GATE = "shadow"
MAX_BOOT_SECONDS = 45

# Lines that mean something is wrong even though the server kept running. "Skipping invalid
# attachments" looks like a harmless warning, but it means saved player records are being thrown away.
FORBIDDEN = [
    r"Skipping invalid attachments",
    # The world holds a block ID the mod no longer has, and loading it just erased that block.
    r"Recoverable errors when loading section",
    r"Mixin apply failed",
    r"Exception in server tick loop",
    r"Couldn't parse data file",
    r"Couldn't load tag",
    r"Failed to load",
    # What says which file it was, when something in a data pack stops the server starting.
    r"Errors in (registry|element)",
    r"Unknown registry key",
    r"server module .* failed to load",
    r"server module .* threw an error",
    r"Encountered an unexpected exception",
    r"This crash report",
    # Nothing else checks an item's components against the game's own format before this.
    r"Can't read the defaults for",
    r"Can't read config",
]
FORBIDDEN_RE = re.compile("|".join(FORBIDDEN))


def _fail(message):
    raise GateFailed(GATE, message)


def scan_logs(text):
    return [line[:220] for line in text.splitlines() if FORBIDDEN_RE.search(line)]


def _running():
    """Really answering, because to Docker a server stuck crashing still counts as running, and then every release
    after a bad one would fail for what that one did, rather than starting it afresh."""
    state = runtime.inspect_state("shadow")
    return bool(state and state.get("Running") and not state.get("Restarting")) and "players online" in runtime.rcon("shadow", "list", check=False)


def clone_prod_world():
    """Copies the live world for testing, briefly pausing saves so the copy is consistent."""
    target = runtime.RUNTIME / "shadow" / "world"
    source = runtime.RUNTIME / "prod" / "world"
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    prod_up = runtime.inspect_state("prod")
    prod_up = bool(prod_up and prod_up.get("Running"))
    if prod_up:
        runtime.rcon("prod", "save-off")
        runtime.rcon("prod", "save-all", "flush")
    try:
        runtime.sync_tree(source, target, "session.lock")
    finally:
        if prod_up:
            runtime.rcon("prod", "save-on")


def cold_boot(jars):
    """Stops the shadow server, copies in the live world and candidate jars, and starts it."""
    runtime.stack("stop", "shadow", check=False)
    clone_prod_world()
    candidate = runtime.RELEASES / "candidate"
    candidate.mkdir(parents=True, exist_ok=True)
    for old in candidate.glob("*.jar"):
        old.unlink()
    for jar in jars:
        shutil.copy(jar, candidate)


def start():
    runtime.stack("up", "-d", "shadow", "shadow-proxy")
    return runtime.wait_ready("shadow", timeout=240)


def smoke_join():
    """Logs a test client in through the shadow's proxy: login, pack offer, checksum, world entry."""
    time.sleep(3.5)  # Velocity limits how fast one address can log in.
    result = runtime.run(
        [sys.executable, "scripts/smoketest_join.py", "--port", "25566", "--name", "gatebot", "--stay", "4"],
        check=False, timeout=90,
    )
    if result.returncode != 0:
        _fail(f"A client couldn't join the shadow server:\n{result.stdout[-1200:]}")


def world_after_patches():
    """Loads a small sample of the world, lets the patches finish on it, and copies the result."""
    regions = _region_dir()
    if regions is None:
        _fail("Couldn't find the shadow world's region files")
    runtime.rcon("shadow", "forceload", "add", "-24", "-24", "24", "24", check=False)
    mark = runtime.utc_now()
    time.sleep(6)
    for _ in range(45):
        status = re.findall(r"retrogen: queued=(\d+)", runtime.logs_since("shadow", mark))
        if status and status[-1] == "0":
            break
        time.sleep(1)
    runtime.rcon("shadow", "save-all", "flush")
    time.sleep(2)
    after = runtime.BROKER / "diff" / "after"
    runtime.sync_tree(regions, after)
    return after


def _region_dir():
    found = sorted((runtime.RUNTIME / "shadow" / "world").rglob("region"))
    overworld = [path for path in found if "overworld" in str(path) or path.parent.name == "world"]
    return (overworld or found or [None])[0]


def snapshot_regions():
    regions = _region_dir()
    if regions is None:
        return None
    before = runtime.BROKER / "diff" / "before"
    runtime.sync_tree(regions, before)
    return before


def run_diff(before, after, ore_blocks, allowed, new_block_entities=False):
    for ore in ore_blocks:
        result = runtime.run(
            [sys.executable, "broker/gates/world_diff.py", str(before), str(after), "--ore", ore, "--allow", *allowed,
             *(["--allow-new-block-entities"] if new_block_entities else [])],
            check=False, timeout=600,
        )
        if result.returncode != 0:
            _fail(f"The world check found a problem with {ore}:\n{result.stdout[-1500:]}")


def run_gate(tier, jars, content, patches):
    """Returns timings. Warm for live changes, cold only when the server must restart anyway."""
    timings = {}
    mark = runtime.utc_now()
    cold = tier == "T3" or not _running()
    before = None
    if cold:
        started = time.monotonic()
        cold_boot(jars)
        timings["clone"] = round(time.monotonic() - started, 1)
        if patches:
            before = snapshot_regions()
        runtime.apply_content("shadow", content)
        try:
            boot = start()
        except TimeoutError:
            # A loot table the game can't read stops it starting at all, and it would go round and round trying, so what it said is all there is to go on.
            problems = scan_logs(runtime.logs_since("shadow", mark))
            runtime.stack("stop", "shadow", check=False)
            _fail("The server wouldn't start with this release:\n" + "\n".join(problems[:12]))
        timings["boot"] = round(boot, 1)
        if boot > MAX_BOOT_SECONDS:
            _fail(f"The server took {boot:.0f}s to boot, over the {MAX_BOOT_SECONDS}s limit, which is what "
                  "keeps a restart inside the proxy's hold. Reduce startup work.")
    else:
        started = time.monotonic()
        if patches:
            # Has to happen before the new patches exist, or the "before" copy already contains them.
            runtime.rcon("shadow", "save-all", "flush")
            time.sleep(1)
            before = snapshot_regions()
        runtime.apply_content("shadow", content)
        runtime.reload_content("shadow")
        timings["hot_apply"] = round(time.monotonic() - started, 1)

    if cold:
        runtime.rcon("shadow", "datapack", "enable", '"file/gm_content"', check=False)

    time.sleep(2)
    problems = scan_logs(runtime.logs_since("shadow", mark))
    if problems:
        _fail("The server logged problems:\n" + "\n".join(problems[:12]))

    started = time.monotonic()
    smoke_join()
    timings["smoke_join"] = round(time.monotonic() - started, 1)

    problems = scan_logs(runtime.logs_since("shadow", mark))
    if problems:
        _fail("The server logged problems after a client joined:\n" + "\n".join(problems[:12]))

    if patches and before is not None:
        started = time.monotonic()
        after = world_after_patches()
        timings["world_sample"] = round(time.monotonic() - started, 1)
        started = time.monotonic()
        # Checked per block, so ore can't get away with replacing air just because a plant is allowed to.
        allowed = {}
        for patch in patches:
            allowed.setdefault(patch["block"], set()).update(patch["replaces"])
        new_block_entities = any(patch.get("adds_block_entities") for patch in patches)
        for block, replaces in sorted(allowed.items()):
            run_diff(before, after, [block], sorted(replaces), new_block_entities)
        timings["world_diff"] = round(time.monotonic() - started, 1)
    return timings


def stop():
    subprocess.run(["./scripts/stack.sh", "--profile", "shadow", "stop", "shadow", "shadow-proxy"],
                   cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, check=False)
