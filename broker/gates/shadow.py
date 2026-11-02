"""Tries a release on a copy of the live world, with real boots and a real client login."""
import json
import re
import shutil
import sys
import time

from broker import runtime
from broker.gates import GateFailed, mixins, world_diff

GATE = "shadow"
MAX_BOOT_SECONDS = 45
OVERWORLD = "minecraft:overworld"
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
# It stops at the first that fits. Something that wants high ground only suits about one spot in five.
RUIN_SPOTS_TRIED = 16
# Out where nobody's been in any world, because where people have been would say nothing about whether it can go anywhere. This is only the test copy.
RUIN_TRIED_AT = "12000"
SAMPLE_SECONDS = 45
# For each ruin. Each spot may have to generate its land first, on a test server that's limited so it can't starve the live one.
BIG_RUIN_SECONDS = 120

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
    # A dimension's generator is only ever checked against the game's own format here.
    r"Can't open dimension",
]
FORBIDDEN_RE = re.compile("|".join(FORBIDDEN))
MIXINS_IN_PLACE = re.compile(r"feature mixins in place: \d+ from (\d+) features")
WONT_START = re.compile(r"feature mixin .* didn't apply|Mixin apply for mod .* failed|InvalidMixinException|MixinTransformerError")
BOOT_TIMEOUT_SECONDS = 240
BOOT_LOOK_SECONDS = 5
MOST_LOG_LINE = 2000
MOST_CONTEXT_LINES = 24


def _fail(message):
    raise GateFailed(GATE, message)


def scan_logs(text):
    """Include nested causes and registry decoder details, which usually follow the matching error."""
    lines = text.splitlines()
    found = []
    end = 0
    for index, line in enumerate(lines):
        if index < end or not FORBIDDEN_RE.search(line):
            continue
        end = index + 1
        while end < min(len(lines), index + MOST_CONTEXT_LINES):
            following = lines[end]
            if re.match(r"^\[\d\d:\d\d:\d\d\].*\bINFO\b", following):
                break
            end += 1
        found.append("\n".join(part[:MOST_LOG_LINE] for part in lines[index:end]))
    return found


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
        [sys.executable, "scripts/smoketest_join.py", "--port", runtime.SHADOW_PROXY_PORT, "--name", "gatebot", "--stay", "4",
         # The address offered to a client on its lane's own network doesn't mean anything out here.
         *(["--pack-from", f"localhost:{runtime.SHADOW_ENV['SHADOW_PACK_PORT']}"] if "SHADOW_PACK_URL" in runtime.SHADOW_ENV else [])],
        check=False, timeout=90,
    )
    if result.returncode != 0:
        _fail(f"A client couldn't join the shadow server:\n{result.stdout[-1200:]}")


def world_after_patches(patches):
    """Loads a small sample of each dimension the patches are for, lets them finish on it, and copies the result. A ruin too big for a chunk
    probably wouldn't reach that sample by itself, so it's tried out nearby as well."""
    for dimension in sorted({patch.get("dimension", OVERWORLD) for patch in patches}):
        runtime.rcon("shadow", "execute", "in", dimension, "run", "forceload", "add", "-24", "-24", "24", "24", check=False)
    mark = runtime.utc_now()
    big = {patch["id"]: patch.get("dimension", OVERWORLD) for patch in patches if patch.get("big")}
    for ruin, dimension in big.items():
        runtime.rcon("shadow", "execute", "in", dimension, "positioned", RUIN_TRIED_AT, "64", RUIN_TRIED_AT, "run", "conduit", "ruin", "try", ruin, str(RUIN_SPOTS_TRIED), check=False)
    time.sleep(6)
    finished = False
    for second in range(BIG_RUIN_SECONDS * len(big) if big else SAMPLE_SECONDS):
        status = re.findall(r"retrogen: queued=(\d+) .* plans=(\d+)", runtime.logs_since("shadow", mark))
        # A chunk at the edge of what's loaded can wait forever for the next one to appear, so the queue only gets so long to empty.
        if status and status[-1][1] == "0" and (status[-1][0] == "0" or second >= SAMPLE_SECONDS):
            finished = True
            break
        time.sleep(1)
    for ruin in big:
        summary = runtime.rcon("shadow", "conduit", "ruin", "summary", ruin, check=False)
        if ": placed 0" in summary:
            tried = f"it wasn't placed at any of up to {RUIN_SPOTS_TRIED} spots" if finished else "it hadn't been placed anywhere by the time the test ran out of time"
            _fail(f"Ruin {ruin} is too big for one chunk, and {tried}, so it may never turn up. What stopped it:\n{summary}")
    runtime.rcon("shadow", "save-all", "flush")
    time.sleep(2)
    return copy_regions("after")


def copy_regions(name):
    """The land in every dimension of the shadow world, each in a folder of its own. Anything left over from an earlier copy
    goes, because a dimension that had vanished would otherwise look as though it was still there."""
    target = runtime.DIFF / name
    dimensions = world_diff.dimension_folders(runtime.server_folder("shadow") / "world")
    for folder in target.glob("*/*"):
        if f"{folder.parent.name}:{folder.name}" not in dimensions:
            shutil.rmtree(folder)
    for dimension, folder in dimensions.items():
        if (folder / "region").is_dir():
            runtime.sync_tree(folder / "region", target / dimension.replace(":", "/"))
    return target


def diff_rules(patches, dimension):
    """What each block may replace in one dimension. It goes by the block, so ore can't get away with replacing air just because a plant is
    allowed to. One of this world's blocks has no business in a dimension no patch of it is for, so it may replace nothing there. Vanilla's
    blocks aren't held to that, because something like cobblestone can form by itself. A ruin's rooms are air, and that says nothing, because
    leaves decay and snow melts while this is running."""
    rules = {}
    for patch in patches:
        if patch["block"] in AIR:
            continue
        if patch.get("dimension", OVERWORLD) == dimension:
            rules.setdefault(patch["block"], set()).update(patch["replaces"])
        elif patch["block"].startswith("gm:"):
            rules.setdefault(patch["block"], set())
    return {block: sorted(replaces) for block, replaces in rules.items()}


def run_diff(before, after, patches):
    """Every dimension there was before, so one that lost land fails, whether or not any patch is for it."""
    rules_file = runtime.DIFF / "rules.json"
    for folder in sorted(before.glob("*/*")):
        dimension = f"{folder.parent.name}:{folder.name}"
        rules_file.write_text(json.dumps(diff_rules(patches, dimension)), encoding="utf-8")
        new_block_entities = any(patch.get("adds_block_entities") and patch.get("dimension", OVERWORLD) == dimension for patch in patches)
        result = runtime.run(
            [sys.executable, "broker/gates/world_diff.py", str(folder), str(after / folder.parent.name / folder.name), "--rules", str(rules_file),
             *(["--allow-new-block-entities"] if new_block_entities else [])],
            check=False, timeout=600,
        )
        if result.returncode != 0:
            _fail(f"The world check found a problem in {dimension}:\n{result.stdout[-1500:]}")


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
        _fail("The server logged errors after the feature mixins were removed. A rollback must work without them. "
              "Check the causes below: modules may still depend on removed mixin classes, or saved data may require them. "
              "Make those dependencies optional and keep saved data readable without the mixins:\n" + "\n".join(problems[:12]))


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
            before = copy_regions("before")
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
            before = copy_regions("before")
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
        after = world_after_patches(patches)
        timings["world_sample"] = round(time.monotonic() - started, 1)
        started = time.monotonic()
        run_diff(before, after, patches)
        timings["world_diff"] = round(time.monotonic() - started, 1)
    if new_mixins:
        started = time.monotonic()
        boot_without_mixins(jars)
        timings["without_mixins"] = round(time.monotonic() - started, 1)
    return timings


def stop():
    runtime.stack("stop", "shadow", "shadow-proxy", check=False)
