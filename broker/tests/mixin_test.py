#!/usr/bin/env python3
"""The exit test for mixins: a real one goes through a release with a restart and changes how a boat moves on the server. One that won't
apply is refused at the gates, and so is one aimed at gm.conduit. One that crashes after its release comes out again and the server
returns, and taking one away leaves the world loading.

Runs against the real stack, so give it a stack of its own or take the dev stack's lock. It leaves a release called mixin-gone live.
Usage: python3 -m broker.tests.mixin_test [scenario ...]
"""
import contextlib
import json
import re
import shutil
import subprocess
import sys
import time

from broker import deploy, runtime
from broker.gates import mixins, shadow
from broker.tests import m2_test

FEATURE = m2_test.FEATURES / "ember"
FOLDER = FEATURE / "mixins"
PACKAGE = FOLDER / "src" / "main" / "java" / "gm" / "feature" / "ember" / "mixin"
WHY = {"why": "Nothing in WorldEvents or a behaviour runs for an empty boat moving, so no hook can change how far it glides."}
GAME_PORT = runtime.ENV.get("GAME_PORT", "25565")
LANE_X = 3000
LANE_Y = 200
LANE_Z = 3000
LANE_LENGTH = 90
MIXIN_JAR = mixins.jar_name("ember")

# Friction on water and in the air. A boat slows by this much each tick, so 0.9 means it goes ten times its speed in all, and 0.99 a hundred.
GLIDE = """package gm.feature.ember.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import net.minecraft.world.level.storage.ValueOutput;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Constant;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyConstant;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(AbstractBoat.class)
abstract class AbstractBoatMixin {
	@Unique private int ember$glides;

	@ModifyConstant(method = "floatBoat", constant = @Constant(floatValue = 0.9F))
	private float ember$glide(float friction) {
		this.ember$glides++;
		return 0.99F;
	}

	// An extra key in what a boat saves, for a game without this mixin to ignore.
	@Inject(method = "addAdditionalSaveData", at = @At("TAIL"))
	private void ember$save(ValueOutput output, CallbackInfo info) {
		output.putInt("ember_glides", this.ember$glides);
	}
}
"""
# Only when a boat has this tag, so it passes every gate, like a bug nobody's met yet, and then someone gets in a boat.
BOOM = """package gm.feature.ember.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(AbstractBoat.class)
abstract class AbstractBoatMixin {
	@Inject(method = "tick", at = @At("HEAD"))
	private void ember$boom(CallbackInfo info) {
		if (((AbstractBoat) (Object) this).entityTags().contains("ember_boom")) {
			throw new IllegalStateException("A mixin test crash");
		}
	}
}
"""
# From a few seconds after the server starts, every time.
CRASHES_AT_ONCE = """package gm.feature.ember.mixin;

import java.util.function.BooleanSupplier;
import net.minecraft.server.level.ServerLevel;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ServerLevel.class)
abstract class ServerLevelMixin {
	@Unique private int ember$ticks;

	@Inject(method = "tick", at = @At("HEAD"))
	private void ember$boom(BooleanSupplier ahead, CallbackInfo info) {
		if (++this.ember$ticks > 100) {
			throw new IllegalStateException("A mixin test crash");
		}
	}
}
"""
NO_SUCH_POINT = """package gm.feature.ember.mixin;

import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(AbstractBoat.class)
abstract class AbstractBoatMixin {
	@Inject(method = "tick", at = @At(value = "INVOKE", target = "Lnet/minecraft/world/entity/vehicle/boat/AbstractBoat;noSuchCall()V"))
	private void ember$nothing(CallbackInfo info) {
	}
}
"""
NO_SUCH_CLASS = """package gm.feature.ember.mixin;

import org.spongepowered.asm.mixin.Mixin;

@Mixin(targets = "net.minecraft.world.entity.vehicle.boat.NoSuchBoat")
abstract class NoSuchBoatMixin {
}
"""
AT_CONDUIT = """package gm.feature.ember.mixin;

import gm.conduit.KillSwitch;
import org.spongepowered.asm.mixin.Mixin;

@Mixin(KillSwitch.class)
abstract class KillSwitchMixin {
}
"""


def report(results, name, passed, detail=""):
    results.append(passed)
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}"[:600], flush=True)
    return passed


def source_with(*mixin_sources):
    m2_test.fresh_source()
    m2_test.add_ember()
    data = m2_test.manifest()
    if mixin_sources:
        data["mixins"] = WHY
        PACKAGE.mkdir(parents=True)
        for text in mixin_sources:
            name = re.search(r"(?:class|interface) (\w+)", text).group(1)
            (PACKAGE / f"{name}.java").write_text(text, encoding="utf-8")
    m2_test.save_manifest(data)


def promote(release_id, *flags):
    time.sleep(4)  # Velocity's limit on logins, for anything that gets as far as the join test.
    code, result = m2_test.promote(release_id, *flags)
    print(f"      {release_id}: exit={code} result={result.get('result')} gate={result.get('gate')} tier={result.get('tier')} "
          f"total={result.get('total_seconds')}s shadow={result.get('shadow')}", flush=True)
    return code, result


@contextlib.contextmanager
def someone_on():
    """A server with nobody on stops ticking after a minute, so a boat would never move."""
    time.sleep(4)
    bot = subprocess.Popen([sys.executable, "scripts/smoketest_join.py", "--port", GAME_PORT, "--name", "boater", "--stay", "30"],
                           cwd=runtime.REPO, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    try:
        yield
    finally:
        bot.kill()
        bot.wait()


def boat_x():
    reply = runtime.rcon("prod", "data", "get", "entity", "@e[tag=ember_lane,limit=1]", "Pos[0]")
    return float(re.search(r"(-?[\d.]+)d", reply).group(1))


def how_far_a_boat_goes(*extra_tags):
    """Sends an empty boat down a walled channel of water and says how far it got. The server works out an empty boat's movement itself."""
    x, y, z = LANE_X, LANE_Y, LANE_Z
    runtime.rcon("prod", "forceload", "add", str(x - 8), str(z - 8), str(x + LANE_LENGTH + 8), str(z + 8))
    runtime.rcon("prod", "fill", str(x - 1), str(y - 1), str(z - 2), str(x + LANE_LENGTH), str(y + 2), str(z + 2), "minecraft:barrier")
    runtime.rcon("prod", "fill", str(x), str(y), str(z - 1), str(x + LANE_LENGTH - 1), str(y), str(z + 1), "minecraft:water")
    runtime.rcon("prod", "fill", str(x), str(y + 1), str(z - 1), str(x + LANE_LENGTH - 1), str(y + 2), str(z + 1), "minecraft:air")
    runtime.rcon("prod", "kill", "@e[type=minecraft:oak_boat]", check=False)
    time.sleep(1)
    tags = json.dumps(["ember_lane", *extra_tags])
    runtime.rcon("prod", "summon", "minecraft:oak_boat", str(x + 1), f"{y + 0.5}", str(z), "{Motion:[1.0d,0.0d,0.0d],Tags:" + tags + "}")
    time.sleep(3)
    return boat_x() - x


def on_prod():
    """Whether the live server's jars have the mixin, as it would see them at its next start and as it's really running."""
    in_release = (runtime.RELEASES / "current" / MIXIN_JAR).exists()
    listing = runtime.run(["./scripts/stack.sh", "exec", "-T", "prod", "ls", "mods"], check=False).stdout
    return in_release, MIXIN_JAR in listing


def healthy():
    state = runtime.inspect_state("prod")
    return bool(state and state.get("Running")) and "players online" in runtime.rcon("prod", "list", check=False)


def scenario_refused(results):
    """Nothing here gets as far as a server."""
    source_with(AT_CONDUIT)
    before = runtime.load_state().get("current")
    code, result = promote("mixin-at-conduit-lint", "--lint-only")
    report(results, "a mixin aimed at gm.conduit is refused by lint, from its source", code == 2 and result.get("gate") == "static" and "gm.conduit.KillSwitch" in result.get("reason", ""), result.get("reason", ""))
    # Lint reads the source, and the gate that counts reads what was compiled, so this takes the source's words out of lint's way.
    (PACKAGE / "KillSwitchMixin.java").write_text(AT_CONDUIT.replace("@Mixin(KillSwitch.class)", "@Mixin(value = {KillSwitch\n.class})").replace("import gm.conduit.KillSwitch;", "import gm.conduit.*;"), encoding="utf-8")
    code, result = promote("mixin-at-conduit", "--check-only")
    report(results, "and by the check on what's compiled, whatever the source looks like", code == 2 and "target gm/conduit/KillSwitch" in result.get("reason", ""), f"gate={result.get('gate')} {result.get('reason', '')[:300]}")
    report(results, "and the live server didn't change", runtime.load_state().get("current") == before)

    source_with()
    resources = FEATURE / "server" / "src" / "main" / "resources"
    marker = runtime.WORK / "mods" / "EXPANDED"
    marker.unlink(missing_ok=True)
    (resources / "fabric.mod.json").write_text('{"x": "${new File(\\"/work/EXPANDED\\").text = \\"ran\\"}"}', encoding="utf-8")
    code, result = promote("mixin-expand", "--check-only")
    report(results, "a feature's file isn't run as code by the build", not marker.exists(), f"{result.get('gate')}: {result.get('reason', '')[:200]}")
    report(results, "and it can't ship", code == 2)

    source_with()
    (FEATURE / "server" / "build.gradle").write_text('file("/work/EXPANDED").text = "ran"\n', encoding="utf-8")
    code, result = promote("mixin-build-script", "--check-only")
    report(results, "a feature can't bring a build script", code == 2 and result.get("gate") == "static" and not marker.exists(), result.get("reason", "")[:200])

    source_with()
    (FEATURE / "server" / "build").symlink_to("/work/conduit/build")
    code, result = promote("mixin-link", "--lint-only")
    report(results, "or a link", code == 2 and "is a link" in result.get("reason", ""), f"{result.get('gate')}: {result.get('reason', '')[:200]}")


def scenario_wont_apply(results):
    before = runtime.load_state().get("current")
    for name, text, words in (("an injection point that isn't there", NO_SUCH_POINT, "AbstractBoatMixin"),
                              ("a target class that doesn't exist", NO_SUCH_CLASS, "NoSuchBoat")):
        source_with(text)
        started = time.monotonic()
        code, result = promote(f"mixin-wont-apply-{words.lower()}", "--no-deploy")
        reason = result.get("reason", "")
        report(results, f"{name} is refused at the gates", code == 2 and result.get("gate") == "shadow" and words in reason,
               f"{time.monotonic() - started:.0f}s gate={result.get('gate')} {reason[:400]}")
    report(results, "and the live server didn't change", runtime.load_state().get("current") == before and healthy())
    runtime.stack("stop", "shadow", check=False)


def scenario_release(results):
    source_with()
    code, result = promote("mixin-base")
    report(results, "a release with no mixins goes out", code == 0, str(result.get("result")))
    with someone_on():
        ordinary = how_far_a_boat_goes()
    report(results, "an empty boat slows down on water as usual", 5 < ordinary < 15, f"{ordinary:.1f} blocks")

    source_with(GLIDE)
    state = runtime.inspect_state("prod")
    mark = runtime.utc_now()
    code, result = promote("mixin-glide")
    report(results, "a release with a real mixin goes out", code == 0 and result.get("result") == "released", str(result.get("reason", ""))[:600])
    report(results, "and it took a restart", result.get("tier") == "T3" and runtime.inspect_state("prod")["StartedAt"] != state["StartedAt"], f"tier={result.get('tier')}")
    report(results, "the world was tried without it first", "without_mixins" in (result.get("shadow") or {}), str(result.get("shadow")))
    logs = runtime.logs_since("prod", mark)
    report(results, "the live server says it's in place", "feature mixins in place: 1 from 1 features" in logs)
    report(results, "with nothing wrong in the log", not shadow.scan_logs(logs), str(shadow.scan_logs(logs))[:300])
    with someone_on():
        patched = how_far_a_boat_goes()
        saved = runtime.rcon("prod", "data", "get", "entity", "@e[tag=ember_lane,limit=1]", "ember_glides")
    report(results, "and a boat really does go further", patched > 2 * ordinary, f"{ordinary:.1f} blocks before, {patched:.1f} now")
    report(results, "what the mixin saves is in the boat's data", "has the following entity data" in saved, saved)
    return ordinary


def scenario_crash_at_once(results):
    """Straight to the live server, as if the gates had missed it, to show what's behind them."""
    source_with(CRASHES_AT_ONCE)
    code, result = promote("mixin-crash-check", "--check-only")
    report(results, "a mixin that will crash passes the checks that don't run it", code == 0, str(result.get("reason", ""))[:300])
    jars = [path for path in (runtime.WORK / "mods" / "conduit" / "build" / "libs").glob("*.jar") if not path.name.endswith("-sources.jar")]
    jars.append(runtime.WORK / "mixin-jars" / MIXIN_JAR)
    before = runtime.load_state().get("current")
    folder = runtime.HISTORY / before
    release = deploy.store_release("mixin-crash", jars, folder / "content", folder / "registry-ledger.json")
    had_it = (folder / "jars" / MIXIN_JAR).exists()
    started = time.monotonic()
    try:
        deploy.deploy("T3", release, "a test")
        rolled_back = None
    except deploy.RolledBack as error:
        rolled_back = str(error)
    report(results, "one that crashes the live server soon after its release is rolled back", rolled_back is not None, f"{time.monotonic() - started:.0f}s {rolled_back}")
    runtime.wait_ready("prod", timeout=120)
    time.sleep(10)
    report(results, "the server came back and stayed", healthy() and runtime.load_state().get("current") == before)
    in_release, running = on_prod()
    report(results, "with the release as it was before", in_release == had_it and running == had_it, f"in the release: {in_release}, running: {running}")
    shutil.rmtree(release)

    source_with(CRASHES_AT_ONCE)
    code, result = promote("mixin-crash-gates", "--no-deploy")
    report(results, "the same mixin is refused at the gates when it goes through them", code == 2 and result.get("gate") == "shadow", f"{result.get('gate')}: {result.get('reason', '')[:300]}")
    runtime.stack("stop", "shadow", check=False)


def scenario_crash_later(results):
    source_with(BOOM)
    code, result = promote("mixin-boom")
    report(results, "a mixin with a bug nobody's met yet passes the gates and goes out", code == 0 and result.get("result") == "released", str(result.get("reason", ""))[:300])
    report(results, "and it's on the server", all(on_prod()))
    deploy.check_for_mixin_crashes()
    reports = runtime.RUNTIME / "prod" / "crash-reports"
    before = set(reports.glob("*.txt"))
    started = time.monotonic()
    with someone_on():
        with contextlib.suppress(Exception):
            how_far_a_boat_goes("ember_boom")
        while time.monotonic() - started < 60 and not set(reports.glob("*.txt")) - before:
            time.sleep(1)
    new = set(reports.glob("*.txt")) - before
    report(results, "someone meets it, and the server crashes", bool(new), str(sorted(path.name for path in new)))
    text = "".join(path.read_text(encoding="utf-8", errors="replace") for path in new)
    print("      what's in the crash report:", [line.strip() for line in text.splitlines() if "ember" in line][:8], flush=True)
    removed = deploy.check_for_mixin_crashes()
    report(results, "the watch points to that mixin and takes it out", removed == ["ember"], str(removed))
    report(results, "and it says why", "ember" in deploy.crashed_mixins().get("ember", {}).get("reason", ""), str(deploy.crashed_mixins()))
    runtime.wait_ready("prod", timeout=120)
    time.sleep(10)
    report(results, "the server came back and stayed", healthy())
    report(results, "and doesn't have that mixin any more", not any(on_prod()), str(on_prod()))
    with someone_on():
        again = how_far_a_boat_goes("ember_boom")
    time.sleep(5)
    report(results, "the same boat does nothing now", healthy(), f"{again:.1f} blocks")
    report(results, "and the rest of the feature is still there", "server module ember enabled" in runtime.logs_since("prod", "5m"))
    runtime.rcon("prod", "kill", "@e[type=minecraft:oak_boat]", check=False)

    code, result = promote("mixin-boom-again")
    report(results, "the same jar doesn't go out again, and nothing else is held up by it",
           code == 0 and result.get("result") == "nothing_to_release" and "ember" in result.get("withheld_mixins", {}),
           f"{result.get('result')} withheld={result.get('withheld_mixins')}")
    deploy.CRASHED_MIXINS.unlink()


def scenario_removal(results):
    source_with(GLIDE)
    code, result = promote("mixin-glide-again")
    report(results, "a mixin goes out again", code == 0 and all(on_prod()), str(result.get("reason", ""))[:300])
    with someone_on():
        patched = how_far_a_boat_goes()
        runtime.rcon("prod", "save-all", "flush")
    source_with()
    state = runtime.inspect_state("prod")
    mark = runtime.utc_now()
    code, result = promote("mixin-gone")
    report(results, "taking it away is a release too, with a restart", code == 0 and result.get("tier") == "T3" and runtime.inspect_state("prod")["StartedAt"] != state["StartedAt"], f"tier={result.get('tier')} {result.get('reason', '')}")
    report(results, "and it's gone from the server", not any(on_prod()), str(on_prod()))
    logs = runtime.logs_since("prod", mark)
    report(results, "the world loaded, boats and what they saved included, with nothing wrong", healthy() and not shadow.scan_logs(logs), str(shadow.scan_logs(logs))[:300])
    with someone_on():
        boats = runtime.rcon("prod", "execute", "if", "entity", "@e[tag=ember_lane]")
        ordinary = how_far_a_boat_goes()
    report(results, "the boat it left behind is still in the world", "passed" in boats.lower(), boats)
    report(results, "and boats are back to how they were", ordinary < patched / 2, f"{patched:.1f} blocks with it, {ordinary:.1f} without")


SCENARIOS = {"refused": scenario_refused, "wont_apply": scenario_wont_apply, "release": scenario_release, "crash_at_once": scenario_crash_at_once,
             "crash_later": scenario_crash_later, "removal": scenario_removal}


def main():
    results = []
    for name in sys.argv[1:] or SCENARIOS:
        print(f"--- {name}", flush=True)
        SCENARIOS[name](results)
    print(f"{sum(results)} of {len(results)} passed", flush=True)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
