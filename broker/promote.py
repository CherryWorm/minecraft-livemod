#!/usr/bin/env python3
"""Takes a source tree through every gate and, if it passes, onto the live server.

Usage: python3 -m broker.promote --source DIR [--no-deploy] [--release-id ID] [--chaos-in-prod]

Exit codes: 0 released (or nothing to release), 2 blocked by a gate, 3 released then rolled back.
The result is also written to runtime/broker/last.json, so the agent can read why something failed.
"""
import argparse
import json
import pathlib
import shutil
import sys
import time

from broker import bundles, deploy, runtime
from broker.gates import GateFailed, client, shadow, static

SERVER_MODS = ("conduit",)


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
    runtime.sync_tree(source / "mods", mods, "build/", ".gradle/", "run/")
    # Build folders are kept for speed, so a deleted feature's would otherwise linger and look like a feature.
    kept = mods / "genesis" / "features"
    if kept.is_dir():
        for folder in kept.iterdir():
            if not (source / "mods" / "genesis" / "features" / folder.name).exists():
                shutil.rmtree(folder)
    for name in ("bible",):
        if (source / name).exists():
            runtime.sync_tree(source / name, runtime.WORK / name)
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
    bundles.render(features, new_ledger, content, runtime.data_format())
    return features, pool, old_ledger, new_ledger


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
    if changed("pack") or changed("modules") or changed("config"):
        return "T2"
    if changed("datapack"):
        return "T1"
    return None


def new_visuals(old_ledger, new_ledger):
    blocks = [entry["slot"] for key, entry in new_ledger["blocks"].items() if key not in old_ledger.get("blocks", {})]
    items = [entry["slot"] for key, entry in new_ledger["items"].items() if key not in old_ledger.get("items", {})]
    return blocks, items


def patches_changed(content, old_content):
    def read(folder):
        path = folder / "config" / "ore_patches.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    old_ids = {patch["id"] for patch in read(old_content)}
    return [patch for patch in read(content) if patch["id"] not in old_ids]


def promote(source, release_id, deploy_to_prod, chaos_in_prod, stages, check_only=False):
    report = {"release": release_id}
    content = runtime.WORK / "content"
    mods = stages.run("prepare", lambda: prepare_source(source))
    features, pool, old_ledger, new_ledger = stages.run("compile", lambda: compile_content(source, mods, content))
    stages.run("static", lambda: static.run(features, old_ledger, new_ledger, pool, content))

    ledger_path = runtime.WORK / "registry-ledger.json"
    bundles.save_ledger(ledger_path, new_ledger)

    stages.run("build", lambda: build(mods))
    jars = collect_jars(mods)
    collect_modules(features, mods, content)
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
    new_patches = patches_changed(content, old_content)
    report["shadow"] = stages.run("shadow", lambda: shadow.run_gate(tier, jars, content, new_patches))

    blocks, items = new_visuals(old_ledger, new_ledger)
    report_dir = runtime.REPORTS / release_id
    shots = stages.run("client", lambda: client.run_gate(blocks, items, mods, report_dir))
    report["screenshots"] = [str(path) for path in shots]

    if not deploy_to_prod:
        report["result"] = "passed_gates"
        return report

    if runtime.AGENT_DISABLED.exists():
        raise GateFailed("control", "The kill switch is on, so nothing can be released.")

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
    parser.add_argument("--chaos-in-prod", action="store_true", help="test only: crash prod to exercise rollback")
    args = parser.parse_args()

    stages = Stages(args.release_id)
    report = {"release": args.release_id}
    code = 0
    try:
        report = promote(args.source.resolve(), args.release_id, not args.no_deploy, args.chaos_in_prod, stages, args.check_only)
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
