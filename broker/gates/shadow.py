"""Tries a release on a copy of the live world, with real boots and a real client login."""
import re
import shutil
import sys
import time

from broker import runtime
from broker.gates import GateFailed, mixins

GATE = "shadow"
MAX_BOOT_SECONDS = 45

# Lines that mean something is wrong even though the server kept running. "Skipping invalid
# attachments" looks like a harmless warning, but it means saved player records are being thrown away.
FORBIDDEN = [
    r"Skipping invalid attachments",
    # The world holds a block ID the mod no longer has, and loading it just erased that block.
    r"Recoverable errors when loading section",
    r"Mixin apply failed",
    r"Mixin apply for mod .* failed",
    r"InvalidMixinException",
    r"InvalidInjectionException",
    r"InjectionError",
    r"MixinTransformerError",
    r"MixinApplyError",
    r"@Mixin target .* was not found",
    r"feature mixin .* didn't apply",
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
MIXINS_IN_PLACE = re.compile(r"feature mixins in place: \d+ from (\d+) features")
WONT_START = re.compile(r"feature mixin .* didn't apply|Mixin apply for mod .* failed|InvalidMixinException|MixinTransformerError")
BOOT_TIMEOUT_SECONDS = 240
BOOT_LOOK_SECONDS = 5
MOST_LOG_LINE = 500


def _fail(message):
    raise GateFailed(GATE, message)


def scan_logs(text):
    # Long enough for a mixin's failure to say which mixin and how, which comes after a full method description.
    return [line[:MOST_LOG_LINE] for line in text.splitlines() if FORBIDDEN_RE.search(line)]


def _running():
    """Really answering, because to Docker a server stuck crashing still counts as running, and then every release
    after a bad one would fail for what that one did, rather than starting it afresh."""
    state = runtime.inspect_state("shadow")
    return bool(state and state.get("Running") and not state.get("Restarting")) and "players online" in runtime.rcon("shadow", "list", check=False)


def clone_prod_world():
    copy_live_world(runtime.server_folder("shadow") / "world")


def copy_live_world(target):
    """Copies the live world for testing, briefly pausing saves so the copy is consistent."""
    source = runtime.RUNTIME / "prod" / "world"
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    with runtime.world_lock():
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
    candidate = runtime.candidate_folder()
    candidate.mkdir(parents=True, exist_ok=True)
    for old in candidate.glob("*.jar"):
        old.unlink()
    for jar in jars:
        shutil.copy(jar, candidate)


def running_these_jars(jars):
    """Another lane can have shipped a new engine since this test server started, and testing on top of the old one would prove nothing."""
    started_with = {path.name: path.read_bytes() for path in runtime.candidate_folder().glob("*.jar")}
    return started_with == {jar.name: jar.read_bytes() for jar in jars}


def start(mark, test_mods=True):
    # Docker would make these as root if they weren't there, and then the server couldn't write to them.
    runtime.server_folder("shadow").mkdir(parents=True, exist_ok=True)
    runtime.server_folder("shadow-proxy").mkdir(parents=True, exist_ok=True)
    runtime.stack("up", "-d", *runtime.SHADOW_SERVICES, env={"SHADOW_TEST_MODS": "true" if test_mods else "false"})
    started = time.monotonic()
    while time.monotonic() - started < BOOT_TIMEOUT_SECONDS:
        try:
            runtime.wait_ready("shadow", timeout=BOOT_LOOK_SECONDS)
            return time.monotonic() - started
        except TimeoutError:
            # A mixin that won't apply stops it starting every time, so there's no need to wait all that time to find out.
            if WONT_START.search(runtime.logs_since("shadow", mark)):
                break
    raise TimeoutError(f"shadow didn't answer after {time.monotonic() - started:.0f}s")


def smoke_join():
    """Logs a test client in through the shadow's proxy: login, pack offer, checksum, world entry."""
    time.sleep(3.5)  # Velocity limits how fast one address can log in.
    result = runtime.run(
        [sys.executable, "scripts/smoketest_join.py", "--port", runtime.SHADOW_PROXY_PORT, "--name", "gatebot", "--stay", "4"],
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
    after = runtime.DIFF / "after"
    runtime.sync_tree(regions, after)
    return after


def _region_dir():
    found = sorted((runtime.server_folder("shadow") / "world").rglob("region"))
    overworld = [path for path in found if "overworld" in str(path) or path.parent.name == "world"]
    return (overworld or found or [None])[0]


def snapshot_regions():
    regions = _region_dir()
    if regions is None:
        return None
    before = runtime.DIFF / "before"
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


def check_mixins_applied(jars, logs):
    """Conduit makes every feature's mixins apply as the server starts, and says how many there were. A mixin that fails
    says so too, which scan_logs looks for, but this is what shows the check really ran."""
    expected = sum(1 for jar in jars if mixins.feature_of(jar))
    found = MIXINS_IN_PLACE.findall(logs)
    if expected and (not found or int(found[-1]) != expected):
        _fail(f"This release has {expected} features with mixins, but the server didn't say they were all in place: "
              + (found[-1] if found else "it said nothing about them"))


def boot_without_mixins(jars):
    """A mixin can go at any moment, by a rollback, by crashing or by being taken out, and when it does the world it's been running on has
    to load without it. So this tries that now: what the mixin's world saved, on a server that's never heard of it."""
    runtime.rcon("shadow", "forceload", "add", "-24", "-24", "24", "24", check=False)
    time.sleep(1)
    runtime.rcon("shadow", "save-all", "flush", check=False)
    runtime.stack("stop", "shadow", check=False)
    candidate = runtime.candidate_folder()
    for jar in jars:
        if mixins.feature_of(jar):
            (candidate / jar.name).unlink(missing_ok=True)
    mark = runtime.utc_now()
    try:
        start(mark, test_mods=False)
        time.sleep(2)
        problems = scan_logs(runtime.logs_since("shadow", mark))
    except TimeoutError:
        problems = scan_logs(runtime.logs_since("shadow", mark)) or ["it wouldn't start"]
    # Stopped, so that the next test here starts afresh rather than finding a server with no mixins.
    runtime.stack("stop", "shadow", check=False)
    if problems:
        _fail("The world these mixins leave behind doesn't load without them, and it has to, because that's what a rollback does. "
              "Keep what they save in fields a game without them will ignore, and don't change the format of what the game saves:\n" + "\n".join(problems[:12]))


def run_gate(tier, jars, content, patches, new_mixins=()):
    """Returns timings. Warm for live changes, cold only when the server must restart anyway."""
    timings = {}
    mark = runtime.utc_now()
    cold = tier == "T3" or not _running() or not running_these_jars(jars)
    before = None
    # Anything with mixins runs with exactly the mods the live server has, because the test ones patch the game as well, so
    # they could hide a mixin's failure or cause one that wouldn't happen for real.
    any_mixins = any(mixins.feature_of(jar) for jar in jars)
    if cold:
        started = time.monotonic()
        cold_boot(jars)
        timings["clone"] = round(time.monotonic() - started, 1)
        if patches:
            before = snapshot_regions()
        runtime.apply_content("shadow", content)
        try:
            boot = start(mark, test_mods=not any_mixins)
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
    if cold:
        check_mixins_applied(jars, runtime.logs_since("shadow", mark))

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
    if new_mixins:
        started = time.monotonic()
        boot_without_mixins(jars)
        timings["without_mixins"] = round(time.monotonic() - started, 1)
    return timings


def stop():
    runtime.stack("stop", "shadow", "shadow-proxy", check=False)
