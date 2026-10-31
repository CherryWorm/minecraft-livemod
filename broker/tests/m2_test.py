#!/usr/bin/env python3
"""The M2 exit test: a good release ships, bad ones are stopped at the right gate, a crash rolls back.

Runs against the real stack on a throwaway test copy of the source. Prints one line per scenario and
exits non-zero if any of them behaved differently from what's expected.
Usage: python3 -m broker.tests.m2_test [scenario ...]
"""
import json
import pathlib
import shutil
import subprocess
import sys
import time

from broker import bundles, runtime

SOURCE = runtime.BROKER / "testsrc"
FEATURES = SOURCE / "mods" / "genesis" / "features"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ember"
TIME_LIMIT_T2 = 180


def fresh_source():
    runtime.sync_tree(runtime.REPO, SOURCE, ".env", "build/", ".gradle/", "run/")


def add_ember():
    target = FEATURES / "ember"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FIXTURE, target)
    textures = target / "assets" / "textures"
    textures.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(("ember_ore", "ember_block", "ember")):

        data = subprocess.run([sys.executable, "assetkit/proof_texture.py", str(index + 1)], cwd=runtime.REPO,
                              stdout=subprocess.PIPE, check=True).stdout
        (textures / f"{name}.png").write_bytes(data)
    (target / "server" / "src" / "main" / "resources" / "module.properties").write_text(
        "entry=gm.feature.ember.EmberModule\n", encoding="utf-8")


def manifest():
    return json.loads((FEATURES / "ember" / "feature.json").read_text(encoding="utf-8"))


def save_manifest(data):
    (FEATURES / "ember" / "feature.json").write_text(json.dumps(data, indent=1), encoding="utf-8")


def promote(release_id, *extra):
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(SOURCE), "--release-id", release_id, *extra],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=900,
    )
    report = json.loads((runtime.BROKER / "last.json").read_text(encoding="utf-8"))
    return result.returncode, report


def prod_fingerprint():
    return bundles.tree_hash(runtime.RUNTIME / "prod" / "live-assets"), runtime.load_state().get("current")


def expect(name, code, report, want_code, want_gate=None):
    ok = code == want_code and (want_gate is None or report.get("gate") == want_gate)
    reason = (report.get("reason") or "").split("\n")[0][:110]
    print(f"{'PASS' if ok else 'FAIL'}  {name}: exit={code} result={report.get('result')} "
          f"gate={report.get('gate')} total={report.get('total_seconds')}s  {reason}", flush=True)
    if not ok:
        print((report.get("reason") or "")[:1500], flush=True)
    return ok


# Each breaks one thing and names the gate that must catch it.
def bad_texture():
    (FEATURES / "ember" / "assets" / "textures" / "ember.png").write_text("this isn't a picture", encoding="utf-8")


def recipe_without_mode():
    data = manifest()
    del data["recipes"]["ember_block"]["mode"]
    save_manifest(data)


def unknown_reference():
    data = manifest()
    data["recipes"]["ember_block"]["json"]["key"]["X"] = "$item:does_not_exist"
    save_manifest(data)


def removed_block():
    data = manifest()
    del data["blocks"]["ember_block"]
    del data["recipes"]
    save_manifest(data)


def guessable_crafting():
    data = manifest()
    data["recipes"]["ember_block"]["mode"] = "guessable"
    save_manifest(data)




def compile_error():
    path = FEATURES / "ember" / "server" / "src" / "main" / "java" / "gm" / "feature" / "ember" / "EmberModule.java"
    path.write_text(path.read_text(encoding="utf-8").replace("public void enable", "public void enable oops"), encoding="utf-8")


def invalid_recipe():
    data = manifest()
    data["recipes"]["ember_block"]["json"]["result"]["id"] = "minecraft:not_a_real_item"
    save_manifest(data)


def module_crashes_on_load():
    path = FEATURES / "ember" / "server" / "src" / "main" / "java" / "gm" / "feature" / "ember" / "EmberModule.java"
    path.write_text(path.read_text(encoding="utf-8").replace(
        'context.bindBlock("ember_block"', 'if (true) throw new IllegalStateException("broken on purpose");\n\t\tcontext.bindBlock("ember_block"'), encoding="utf-8")


BAD = [
    ("bad_texture", bad_texture, "static"),
    ("recipe_without_mode", recipe_without_mode, "static"),
    ("unknown_reference", unknown_reference, "static"),
    ("removed_block", removed_block, "static"),
    ("guessable_crafting", guessable_crafting, "static"),
    ("compile_error", compile_error, "build"),
    ("invalid_recipe", invalid_recipe, "shadow"),
    ("module_crashes_on_load", module_crashes_on_load, "shadow"),
]


def scenario_good():
    fresh_source()
    add_ember()
    code, report = promote("m2-good")
    ok = expect("good release", code, report, 0)
    print(f"      tier={report.get('tier')} stages={report.get('stages')}", flush=True)
    if report.get("tier") == "T2" and report.get("total_seconds", 999) > TIME_LIMIT_T2:
        print(f"FAIL  T2 took {report['total_seconds']}s, over the {TIME_LIMIT_T2}s target", flush=True)
        ok = False
    runtime.rcon("prod", "forceload", "add", "0", "0")
    placed = runtime.rcon("prod", "setblock", "0", "200", "0", "gm:s1200")
    runtime.rcon("prod", "setblock", "0", "200", "0", "minecraft:air")
    runtime.rcon("prod", "forceload", "remove", "0", "0")
    logs = runtime.logs_since("prod", "10m")
    module = "server module ember enabled" in logs
    print(f"{'PASS' if 'Changed' in placed and module else 'FAIL'}  live server has the new block and module: "
          f"block={'Changed' in placed} module={module}", flush=True)
    return ok and "Changed" in placed and module


def scenario_bad():
    all_ok = True
    for name, breaker, gate in BAD:
        fresh_source()
        add_ember()
        breaker()
        before = prod_fingerprint()
        time.sleep(4)  # Velocity's login rate limit, for scenarios that reach the join test.
        code, report = promote(f"m2-{name}")
        ok = expect(name, code, report, 2, gate)
        if prod_fingerprint() != before:
            print(f"FAIL  {name}: the live server changed", flush=True)
            ok = False
        all_ok = all_ok and ok
    return all_ok


def scenario_rollback():
    fresh_source()
    add_ember()
    data = manifest()
    data["items"]["ember_dust"] = {"display": "Ember Dust", "texture": "ember"}
    save_manifest(data)
    before = runtime.load_state().get("current")
    time.sleep(4)
    code, report = promote("m2-chaos", "--chaos-in-prod")
    ok = expect("forced crash rolls back", code, report, 3)
    print(f"      reason: {(report.get('reason') or '')[:160]}", flush=True)
    after = runtime.load_state().get("current")
    runtime.wait_ready("prod", timeout=120)
    time.sleep(10)
    state = runtime.inspect_state("prod")
    healthy = bool(state and state.get("Running")) and runtime.run(["./scripts/mc.sh", "list"], check=False).returncode == 0
    print(f"{'PASS' if healthy and before == after else 'FAIL'}  after rollback: running={healthy} "
          f"release {before} -> {after}", flush=True)
    return ok and healthy and before == after


SCENARIOS = {"good": scenario_good, "bad": scenario_bad, "rollback": scenario_rollback}


def main():
    chosen = sys.argv[1:] or list(SCENARIOS)
    results = [SCENARIOS[name]() for name in chosen]
    print("M2 PASS" if all(results) else "M2 FAIL", flush=True)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
