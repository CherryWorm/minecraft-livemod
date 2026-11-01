#!/usr/bin/env python3
"""Takes a source tree through every gate and, if it passes, onto the live server.

Usage: python3 -m broker.promote --source DIR [--no-deploy] [--release-id ID] [--chaos-in-prod]

Exit codes: 0 released (or nothing to release), 2 blocked by a gate, 3 released then rolled back.
The result is also written to runtime/broker/last.json, so the agent can read why something failed.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import time

from broker import bundles, deploy, runtime, sign
from broker.gates import GateFailed, advice, balance, bytecode, client, progression, shadow, static

SERVER_MODS = ("conduit",)
PROGRESS_SNAPSHOT = "progress_snapshot.json"


class Stages:
    """Times each stage, because the slowest one is what gets fixed first."""

    def __init__(self, release_id):
        self.release_id = release_id
        self.times = {}
        self.started = time.monotonic()

    def run(self, name, call):
        began = time.monotonic()
        print(f"--- {name}", flush=True)
        try:
            return call()
        finally:
            self.times[name] = round(time.monotonic() - began, 1)
            runtime.record_timeline({"release": self.release_id, "stage": name, "seconds": self.times[name]})

    def total(self):
        return round(time.monotonic() - self.started, 1)


def prepare_source(source):
    """Copies the source to a stable folder, so Gradle's caches make repeat builds fast."""
    mods = runtime.WORK / "mods"
    runtime.sync_tree(source / "mods", mods, "build/", ".gradle/", "run/", exact=True)
    # Build folders are kept for speed, so a deleted feature's would otherwise linger and look like a feature.
    kept = mods / "genesis" / "features"
    if kept.is_dir():
        for folder in kept.iterdir():
            if not (source / "mods" / "genesis" / "features" / folder.name).exists():
                shutil.rmtree(folder)
    for name in ("bible",):
        if (source / name).exists():
            runtime.sync_tree(source / name, runtime.WORK / name, exact=True)
    return mods


def compile_content(source, mods, content):
    features = bundles.load_features(mods / "genesis" / "features")
    pool = bundles.read_pool(source)
    state = runtime.load_state()
    ledger_source = runtime.HISTORY / str(state.get("current")) / "registry-ledger.json"
    old_ledger = bundles.load_ledger(ledger_source)
    new_ledger = bundles.assign_slots(features, json.loads(json.dumps(old_ledger)), pool)
    if content.exists():
        shutil.rmtree(content)
    bundles.render(features, new_ledger, content, runtime.data_format(), runtime.vanilla_biome, discovery_scope(source))
    return features, pool, old_ledger, new_ledger


def check_progression(source, features, new_ledger, content):
    """Compares with the live release, because that's what players' things came from."""
    current = runtime.HISTORY / str(runtime.load_state().get("current")) / "content" / PROGRESS_SNAPSHOT
    old_prints = json.loads(current.read_text(encoding="utf-8")) if current.exists() else {}
    new_prints = progression.snapshot(features)
    content.mkdir(parents=True, exist_ok=True)
    (content / PROGRESS_SNAPSHOT).write_text(json.dumps(new_prints, indent=1), encoding="utf-8")
    knowledge = runtime.RUNTIME / "prod" / "world" / "conduit_knowledge.json"
    progression.run(features, source / "bible", new_ledger, old_prints, knowledge, new_prints)


def discovery_scope(source):
    """Whether learning is shared or per player. The agent chooses this for each world in its discovery plan."""
    path = source / "bible" / "discovery.json"
    return json.loads(path.read_text(encoding="utf-8")).get("scope", "shared") if path.exists() else "shared"


def build(mods):
    result = runtime.run(
        ["./scripts/stack.sh", "run", "--rm", "-T", "builder", "./gradlew", "--no-daemon", "--console=plain", "build"],
        check=False, env={"MODS_DIR": str(mods)}, timeout=600,
    )
    if result.returncode != 0:
        errors = [line for line in result.stdout.splitlines() if "error:" in line or "FAILED" in line]
        raise GateFailed("build", "\n".join(errors[:15]) or result.stdout[-1500:])


def collect_jars(mods):
    jars = []
    for mod in SERVER_MODS:
        found = [path for path in (mods / mod / "build" / "libs").glob("*.jar") if not path.name.endswith("-sources.jar")]
        jars.extend(found)
    return jars


def collect_modules(features, mods, content):
    for feature_id, side in bundles.find_modules(features):
        libs = mods / "genesis" / "features" / feature_id / side / "build" / "libs"
        built = [path for path in libs.glob("*.jar") if not path.name.endswith("-sources.jar")]
        if not built:
            raise GateFailed("build", f"{feature_id}: its {side} module didn't produce a jar")
        target = content / "modules" / side
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(built[0], target / f"{feature_id}.jar")


def check_modules(features, content):
    """Checks the copies in the release, not the build output, so what's checked is what ships."""
    for feature_id, side in bundles.find_modules(features):
        bytecode.check_jar(content / "modules" / side / f"{feature_id}.jar", side, feature_id)


def sign_modules(content, old_content):
    """Signs last, because a jar can't change after this without breaking its signature, and only for a release
    that's really going out, because every signature uses up a generation."""
    try:
        sign.sign_release(content, old_content)
    except (sign.SigningError, OSError) as error:
        raise GateFailed("sign", f"Client modules couldn't be signed, which only the owner can fix: {error}") from error


def jar_hashes(folder):
    return {str(path.relative_to(folder)): bundles.hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*.jar")} if folder.exists() else {}


def choose_tier(content, jars):
    """Works out what the release needs from what actually changed. It's never taken from the agent."""
    state = runtime.load_state()
    current = runtime.HISTORY / str(state.get("current"))
    old_content = current / "content"

    def changed(relative):
        return bundles.tree_hash(content / relative) != bundles.tree_hash(old_content / relative)

    old_jars = sorted(path.name + ":" + bundles.hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (current / "jars").glob("*.jar")) if current.exists() else []
    new_jars = sorted(path.name + ":" + bundles.hashlib.sha256(path.read_bytes()).hexdigest() for path in jars)
    worldgen = bundles.tree_hash(content / "datapack/data/gm/worldgen") != bundles.tree_hash(old_content / "datapack/data/gm/worldgen")
    if old_jars != new_jars or worldgen or not current.exists():
        return "T3"
    # Only the jars count in modules/. The last release's signatures sit beside its jars and this one has none
    # yet, so comparing whole folders would make every check look like a change.
    if changed("pack") or changed("config") or jar_hashes(content / "modules") != jar_hashes(old_content / "modules"):
        return "T2"
    if changed("datapack"):
        return "T1"
    return None


def new_visuals(old_ledger, new_ledger):
    blocks = [entry["slot"] for key, entry in new_ledger["blocks"].items() if key not in old_ledger.get("blocks", {})]
    items = [entry["slot"] for key, entry in new_ledger["items"].items() if key not in old_ledger.get("items", {})]
    mobs = [entry["slot"] for key, entry in new_ledger.get("mobs", {}).items() if key not in old_ledger.get("mobs", {})]
    return blocks, items, mobs


def fingerprint(content, jars, current):
    """Identifies what a gate run proved: this exact content and these jars, on top of this release."""
    digest = hashlib.sha256(str(current).encode())
    digest.update(bundles.tree_hash(content).encode())
    for jar in sorted(jars):
        digest.update(jar.read_bytes())
    return digest.hexdigest()


def run_gates(tier, jars, content, old_ledger, new_ledger, old_content, mods, release_id, stages, report):
    """The slow gates. The agent runs them, has the work reviewed, then asks to release the same commit, and
    running them a second time would only make players wait, so a match with the last pass is enough."""
    proof = fingerprint(content, jars, runtime.load_state().get("current"))
    passed_file = runtime.BROKER / "passed_gates.json"
    if passed_file.exists():
        passed = json.loads(passed_file.read_text(encoding="utf-8"))
        if passed["fingerprint"] == proof:
            print("these exact gates have already passed", flush=True)
            report["screenshots"] = passed["screenshots"]
            return

    new_patches = patches_changed(content, old_content)
    client_modules = jar_hashes(content / "modules" / "client") != jar_hashes(old_content / "modules" / "client")
    sign.mark_for_testing(content)
    report["shadow"] = stages.run("shadow", lambda: shadow.run_gate(tier, jars, content, new_patches))

    blocks, items, mobs = new_visuals(old_ledger, new_ledger)
    report_dir = runtime.REPORTS / release_id
    shots = stages.run("client", lambda: client.run_gate(blocks, items, mods, report_dir, mobs, client_modules))
    report["screenshots"] = [str(path) for path in shots]
    passed_file.parent.mkdir(parents=True, exist_ok=True)
    passed_file.write_text(json.dumps({"fingerprint": proof, "screenshots": report["screenshots"]}), encoding="utf-8")


def patches_changed(content, old_content):
    def read(folder):
        found = []
        ores = folder / "config" / "ore_patches.json"
        if ores.exists():
            found.extend(json.loads(ores.read_text(encoding="utf-8")))
        plants = folder / "config" / "surface_patches.json"
        if plants.exists():
            # A plant grows into open air, so that's all it's allowed to replace.
            found.extend({**plant, "replaces": ["minecraft:air"]} for plant in json.loads(plants.read_text(encoding="utf-8")))
        ruins = folder / "config" / "ruin_patches.json"
        if ruins.exists():
            # Each block in a ruin can only overwrite what the ruin says it may, and only a ruin may add a chest.
            for ruin in json.loads(ruins.read_text(encoding="utf-8")):
                found.extend({"id": ruin["id"], "block": block, "replaces": ruin["replaces"], "adds_block_entities": True}
                             for block in {part["block"] for layout in balance.ruin_layouts(ruin) for part in layout})
        return found

    old_ids = {patch["id"] for patch in read(old_content)}
    return [patch for patch in read(content) if patch["id"] not in old_ids]


def promote(source, release_id, deploy_to_prod, chaos_in_prod, stages, check_only=False, lint_only=False):
    report = {"release": release_id}
    content = runtime.WORK / "content"
    mods = stages.run("prepare", lambda: prepare_source(source))
    features, pool, old_ledger, new_ledger = stages.run("compile", lambda: compile_content(source, mods, content))
    stages.run("static", lambda: static.run(features, old_ledger, new_ledger, pool, content))
    stages.run("progression", lambda: check_progression(source, features, new_ledger, content))
    report["advice"] = advice.run(features)
    if lint_only:
        report["result"] = "passed_lint"
        return report

    ledger_path = runtime.WORK / "registry-ledger.json"
    bundles.save_ledger(ledger_path, new_ledger)

    stages.run("build", lambda: build(mods))
    jars = collect_jars(mods)
    collect_modules(features, mods, content)
    stages.run("bytecode", lambda: check_modules(features, content))
    if check_only:
        report["result"] = "passed_gates"
        return report

    tier = choose_tier(content, jars)
    report["tier"] = tier
    if tier is None:
        report["result"] = "nothing_to_release"
        return report
    print(f"tier: {tier}", flush=True)

    state = runtime.load_state()
    old_content = runtime.HISTORY / str(state.get("current")) / "content"
    run_gates(tier, jars, content, old_ledger, new_ledger, old_content, mods, release_id, stages, report)

    if not deploy_to_prod:
        report["result"] = "passed_gates"
        return report

    if runtime.agent_disabled():
        raise GateFailed("control", "The kill switch is on, so nothing can be released.")

    stages.run("sign", lambda: sign_modules(content, old_content))
    release_folder = deploy.store_release(release_id, jars, content, ledger_path)
    if chaos_in_prod:
        marker = runtime.RUNTIME / "prod" / "config" / "conduit" / "chaos_crash_after_ticks"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("60\n", encoding="utf-8")
    report["deploy"] = stages.run("deploy", lambda: deploy.deploy("T3" if chaos_in_prod else tier, release_folder))
    report["result"] = "released"
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=pathlib.Path)
    parser.add_argument("--release-id", default=time.strftime("r%Y%m%d-%H%M%S"))
    parser.add_argument("--no-deploy", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="stop after the static checks and build")
    parser.add_argument("--lint-only", action="store_true", help="stop after the static checks, with no compile")
    parser.add_argument("--chaos-in-prod", action="store_true", help="test only: crash prod to exercise rollback")
    args = parser.parse_args()

    stages = Stages(args.release_id)
    report = {"release": args.release_id}
    code = 0
    try:
        report = promote(args.source.resolve(), args.release_id, not args.no_deploy, args.chaos_in_prod, stages, args.check_only, args.lint_only)
    except GateFailed as error:
        report.update(result="blocked", gate=error.gate, reason=error.message)
        code = 2
    except bundles.BundleError as error:
        report.update(result="blocked", gate="static", reason=str(error))
        code = 2
    except deploy.RolledBack as error:
        report.update(result="rolled_back", reason=str(error))
        code = 3
    report["stages"] = stages.times
    report["total_seconds"] = stages.total()
    runtime.BROKER.mkdir(parents=True, exist_ok=True)
    (runtime.BROKER / "last.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    sys.exit(code)


if __name__ == "__main__":
    main()
