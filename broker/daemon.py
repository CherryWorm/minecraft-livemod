#!/usr/bin/env python3
"""Runs on the host and answers the agent's requests. The agent has no Docker access, so this is the only
way anything it writes reaches a server, and every request goes through the same gates.

The agent's repository only supplies features and design documents. Everything else, including the code
that polices it, comes from this trusted checkout, so the agent can't change the rules it's checked by.

Usage: python3 -m broker.daemon
"""
import json
import os
import re
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
STARTED = runtime.BROKER / "started.json"
TRIES_BEFORE_REFUSING = 2  # How many times one request can take the whole broker down before it's answered instead.
QUICK = ("lint", "check", "javap", "server_icon", "set_rule", "server_errors")  # None of these touch the shadow server, and someone is waiting on each one.
PROD_LOG = runtime.RUNTIME / "prod" / "logs" / "latest.log"
MOST_LOG_LINES = 200
MOST_LOG_CHARACTERS = 16000
WENT_WRONG = re.compile(r"\b(WARN|ERROR|FATAL)\b|Exception|^\s+at |^Caused by")
IP_ADDRESS = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b")
LOG_NOISE = ("minecraftservices", "authlib", "Services are unavailable")
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


def server_errors(contains=""):
    """What's gone wrong on the live server lately, for whoever's looking into a bug. It's only warnings and errors, because the rest
    of the log says who's been doing what, and never anyone's address."""
    if not PROD_LOG.exists():
        return {"output": "There's no log yet."}
    lines = [IP_ADDRESS.sub("(address)", line) for line in PROD_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
             if WENT_WRONG.search(line) and not any(noise in line for noise in LOG_NOISE)]
    if contains:
        lines = [line for line in lines if contains.lower() in line.lower()]
    return {"output": "\n".join(lines[-MOST_LOG_LINES:])[-MOST_LOG_CHARACTERS:] or "Nothing like that in the log."}


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
        return promote(request["commit"], release_id, f"--why={request.get('why', '')}")
    if kind == "javap":
        return javap(request["class_name"])
    if kind == "server_errors":
        return server_errors(request.get("contains", ""))
    return {"result": "blocked", "gate": "broker", "reason": f"Unknown request {kind}"}


def started_again(request_id):
    """How many times this request has been started. The record outlives the broker, because that's what it's for: a job
    that kills the broker is otherwise picked up again as soon as it's back, and everything else waits behind it forever."""
    started = json.loads(STARTED.read_text(encoding="utf-8")) if STARTED.exists() else {}
    started = {key: count for key, count in started.items() if (REQUESTS / f"{key}.json").exists()}
    started[request_id] = started.get(request_id, 0) + 1
    temporary = STARTED.with_suffix(".tmp")
    temporary.write_text(json.dumps(started), encoding="utf-8")
    temporary.replace(STARTED)
    return started[request_id]


def next_request(pending):
    """Still one at a time, because there's one shadow server and releases must not overlap. But with several builders
    working, a quick check shouldn't wait behind everyone else's full test run, and a small change a player is waiting
    for goes ahead of a big one that's being built in the background. So does a release, because that's finished work
    that everything still being tested would otherwise have to be tested again on top of. A bug fix goes ahead of all of those."""
    def order(path):
        request = json.loads(path.read_text(encoding="utf-8"))
        return (0 if request["kind"] in QUICK else 1 if request.get("first") else 2 if request.get("hurry") or request["kind"] == "release" else 3, path.stat().st_mtime)
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
        try:
            path = next_request(pending)
            request = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue  # Whoever asked has stopped waiting and taken it back.
        started = time.monotonic()
        if started_again(request["id"]) > TRIES_BEFORE_REFUSING:
            answer = {"result": "blocked", "gate": "broker",
                      "reason": f"The broker itself died each of the {TRIES_BEFORE_REFUSING} times it ran this, so it hasn't been checked. "
                                "That may well not be anything in your work."}
        else:
            try:
                answer = handle(request)
            except Exception as error:  # noqa: BLE001 - the agent should hear about any failure, not hang
                answer = {"result": "blocked", "gate": "broker", "reason": f"{type(error).__name__}: {error}"}
        print(f"{request['kind']} {request['id']}: {answer.get('result', 'answered')} "
              f"in {time.monotonic() - started:.1f}s", flush=True)
        temporary = RESPONSES / f".{request['id']}.tmp"
        temporary.write_text(json.dumps(answer), encoding="utf-8")
        temporary.rename(RESPONSES / f"{request['id']}.json")
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
