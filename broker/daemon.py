#!/usr/bin/env python3
"""Runs on the host and answers the agent's requests. The agent has no Docker access, so this is the only
way anything it writes reaches a server, and every request goes through the same gates.

The agent's repository only supplies features and design documents. Everything else, including the code
that polices it, comes from this trusted checkout, so the agent can't change the rules it's checked by.

Usage: python3 -m broker.daemon
"""
import json
import os
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageStat

from broker import reference_textures, runtime

WORKSPACE = runtime.RUNTIME / "agent-workspace"
REQUESTS = WORKSPACE / "requests"
RESPONSES = WORKSPACE / "responses"
AGENT_REPO = WORKSPACE / "repo"
ASSEMBLED = runtime.BROKER / "assembled"
REPORTS_FOR_AGENT = WORKSPACE / "reports"
CACHE_JAR = "/cache/gradle/caches/fabric-loom/26.3/minecraft-client.jar"
AGENT_ICON = WORKSPACE / "icon" / "server-icon.png"
PROXY_DATA = runtime.RUNTIME / "velocity"
ICON_SIZE = 64
QUICK = ("lint", "check", "javap", "server_icon", "set_rule")  # None of these touch the shadow server, and someone is waiting on each one.
# Only these, because the rest of what a server command can do would get around the gates. All of them apply to everyone.
RULES = {"players_sleeping_percentage": lambda value: isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100,
         "spawn_phantoms": lambda value: isinstance(value, bool), "keep_inventory": lambda value: isinstance(value, bool)}


def assemble(commit):
    """Trusted code plus the agent's features and documents, as they were at one commit."""
    runtime.sync_tree(runtime.REPO, ASSEMBLED, ".env", "build/", ".gradle/", "run/", "runtime/")
    features = ASSEMBLED / "mods" / "genesis" / "features"
    if features.exists():
        shutil.rmtree(features)
    features.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(AGENT_REPO), "archive", commit, "mods/genesis/features", "bible"],
        capture_output=True, check=False,
    )
    if archive.returncode != 0:
        # An early commit may have no features yet, which git archive reports as an error for that path.
        archive = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(AGENT_REPO), "archive", commit],
                                 capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(ASSEMBLED), "mods/genesis/features", "bible"], input=archive.stdout, check=False)
    return ASSEMBLED


def promote(commit, release_id, *flags):
    source = assemble(commit)
    # If this run dies before reporting, the agent must hear that rather than the previous run's result.
    last = runtime.BROKER / "last.json"
    last.unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "broker.promote", "--source", str(source), "--release-id", release_id, *flags],
        cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1200,
    )
    if not last.exists():
        return {"result": "blocked", "gate": "broker", "reason": f"The broker crashed:\n{result.stderr[-1500:]}"}
    report = json.loads(last.read_text(encoding="utf-8"))
    # Screenshots go where the agent can read them.
    copied = []
    for path in report.get("screenshots", []):
        target = REPORTS_FOR_AGENT / release_id
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)
        copied.append(f"/workspace/reports/{release_id}/{path.rsplit('/', 1)[-1]}")
    report["screenshots"] = copied
    return report


def javap(class_name):
    if not all(part.replace("$", "").isidentifier() for part in class_name.split(".")):
        return {"reason": "That isn't a class name."}
    result = runtime.run(
        ["./scripts/stack.sh", "run", "--rm", "-T", "builder", "bash", "-c",
         f"CP=$(find /cache/gradle/caches/modules-2/files-2.1/net.fabricmc.fabric-api -name '*.jar' | tr '\\n' ':'); "
         f"javap -public -cp \"{CACHE_JAR}:$CP\" '{class_name}'"],
        check=False, timeout=60,
    )
    lines = [line for line in result.stdout.splitlines() if "Container " not in line]
    return {"output": "\n".join(lines)[:12000]}


def type_into_proxy(command):
    """Velocity only takes commands at its console, so its container reads them from this pipe."""
    try:
        pipe = os.open(PROXY_DATA / "console.pipe", os.O_WRONLY | os.O_NONBLOCK)
    except OSError as error:
        raise RuntimeError(f"the proxy isn't listening: {error}") from error
    with os.fdopen(pipe, "w") as stream:
        stream.write(command + "\n")


def install_icon():
    """Checks what the agent drew and writes a fresh copy of it, so that only a plain image reaches the proxy."""
    if AGENT_ICON.is_symlink() or not AGENT_ICON.is_file():
        return {"result": "blocked", "gate": "icon", "reason": f"Expected a file at /workspace/icon/{AGENT_ICON.name}."}
    try:
        with Image.open(AGENT_ICON) as image:
            if image.format != "PNG" or image.size != (ICON_SIZE, ICON_SIZE):
                return {"result": "blocked", "gate": "icon", "reason": f"It must be a {ICON_SIZE}x{ICON_SIZE} PNG. Found a {image.size} {image.format}."}
            clean = image.convert("RGBA")
    except OSError as error:
        return {"result": "blocked", "gate": "icon", "reason": f"That isn't a readable image: {error}"}
    if max(ImageStat.Stat(clean.convert("RGB")).stddev) < 8:
        return {"result": "blocked", "gate": "icon", "reason": "It's almost one flat colour, so there's nothing to see."}
    target = PROXY_DATA / AGENT_ICON.name
    temporary = target.with_suffix(".tmp")
    clean.save(temporary, format="PNG")
    temporary.replace(target)
    type_into_proxy("velocity reload")
    return {"result": "installed"}


def set_rule(rule, value):
    if rule not in RULES:
        return {"result": "blocked", "gate": "rule", "reason": f"{rule} isn't a rule that can be changed. These are: {', '.join(RULES)}."}
    if not RULES[rule](value):
        return {"result": "blocked", "gate": "rule", "reason": f"{value!r} isn't a usable value for {rule}."}
    runtime.rcon("prod", "gamerule", rule, json.dumps(value))
    return {"result": "set"}


def handle(request):
    kind = request["kind"]
    if runtime.agent_disabled() and kind != "javap":
        return {"result": "blocked", "gate": "control", "reason": "The kill switch is on."}
    release_id = request.get("release_id", f"check-{request['id']}")
    if kind == "lint":
        return promote(request["commit"], release_id, "--lint-only")
    if kind == "server_icon":
        return install_icon()
    if kind == "set_rule":
        return set_rule(request["rule"], request["value"])
    if kind == "check":
        return promote(request["commit"], release_id, "--check-only")
    if kind == "gates":
        return promote(request["commit"], release_id, "--no-deploy")
    if kind == "release":
        return promote(request["commit"], release_id)
    if kind == "javap":
        return javap(request["class_name"])
    return {"result": "blocked", "gate": "broker", "reason": f"Unknown request {kind}"}


def next_request(pending):
    """Still one at a time, because there's one shadow server and releases must not overlap. But with several builders
    working, a quick check shouldn't wait behind everyone else's full test run, and a small change a player is waiting
    for goes ahead of a big one that's being built in the background."""
    def order(path):
        request = json.loads(path.read_text(encoding="utf-8"))
        return (0 if request["kind"] in QUICK else 1 if request.get("hurry") else 2, path.stat().st_mtime)
    return min(pending, key=order)


def main():
    for folder in (REQUESTS, RESPONSES, REPORTS_FOR_AGENT):
        folder.mkdir(parents=True, exist_ok=True)
    # Vanilla's own art, for builders to compare theirs with. The game's jar is outside the agent's reach.
    client_jar = runtime.RUNTIME / CACHE_JAR.removeprefix("/")
    if client_jar.exists():
        reference_textures.extract(client_jar, WORKSPACE / "reference-textures")
    print("broker waiting for requests", flush=True)
    while True:
        pending = list(REQUESTS.glob("*.json"))
        if not pending:
            time.sleep(0.5)
            continue
        path = next_request(pending)
        request = json.loads(path.read_text(encoding="utf-8"))
        started = time.monotonic()
        try:
            answer = handle(request)
        except Exception as error:  # noqa: BLE001 - the agent should hear about any failure, not hang
            answer = {"result": "blocked", "gate": "broker", "reason": f"{type(error).__name__}: {error}"}
        print(f"{request['kind']} {request['id']}: {answer.get('result', 'answered')} "
              f"in {time.monotonic() - started:.1f}s", flush=True)
        temporary = RESPONSES / f".{request['id']}.tmp"
        temporary.write_text(json.dumps(answer), encoding="utf-8")
        temporary.rename(RESPONSES / f"{request['id']}.json")
        path.unlink()


if __name__ == "__main__":
    main()
