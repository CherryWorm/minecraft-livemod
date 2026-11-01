#!/usr/bin/env python3
"""Runs on the host and answers the agent's requests. The agent has no Docker access, so this is the only
way anything it writes reaches a server, and every request goes through the same gates.

The agent's repository only supplies features and design documents. Everything else, including the code
that polices it, comes from this trusted checkout, so the agent can't change the rules it's checked by.

Usage: python3 -m broker.daemon
"""
import collections
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time

from PIL import Image, ImageStat

from broker import deploy, far, reference_textures, runtime

WORKSPACE = runtime.RUNTIME / "agent-workspace"
REQUESTS = WORKSPACE / "requests"
RESPONSES = WORKSPACE / "responses"
AGENT_REPO = WORKSPACE / "repo"
REPORTS_FOR_AGENT = WORKSPACE / "reports"
CACHE_JAR = "/cache/gradle/caches/fabric-loom/26.3/minecraft-client.jar"
AGENT_ICON = WORKSPACE / "icon" / "server-icon.png"
PROXY_DATA = runtime.RUNTIME / "velocity"
ICON_SIZE = 64
STARTED = runtime.BROKER / "started.json"
TRIES_BEFORE_REFUSING = 2  # How many times one request can take the whole broker down before it's answered instead.
QUICK = ("lint", "check", "javap", "server_icon", "set_rule", "server_errors")  # None of these touch the shadow server, and someone is waiting on each one.
# These don't wait for anything. They share nothing with whatever else is running, and they take seconds at most.
AT_ONCE = ("lint", "javap", "server_icon", "set_rule", "server_errors")
MOST_AT_ONCE = 16  # Of each kind. Far more than the builders can ask for at a time, so it only matters if something floods the broker.
CHECK_LANES = int(runtime.ENV.get("CHECK_LANES", "1"))  # Compile checks side by side. Each lane's Gradle files and work folder take about 1.4 GB of disk.
GATE_LANES = int(runtime.ENV.get("GATE_LANES", "1"))  # Test runs side by side. Each after the first has its own test server, proxy, test client, ports and copy of the world.
# These need real memory, and the live server must never go short. So one beside others only starts if there's room for what it'll use,
# as well as this much to spare, which is what lets the live server grow to its limit. Measured in GB.
BIG_JOBS = {"check": 3, "gates": 4, "release": 4}
# A test server and proxy that aren't running yet. After the first job they stay up, so they're already in the system's figures.
NEW_LANE_GB = int(runtime.ENV.get("SHADOW_MEMORY", "6G").removesuffix("G")) + 1
KEEP_FREE_GB = 4
SETTLING_SECONDS = 60  # A job has reached its full size by about now. Until then what it's going to use isn't in the system's figures yet.
POLL_SECONDS = 0.25
MIXIN_WATCH_SECONDS = 5
MOST_JAVAP_CHARACTERS = 12000
# Written by scripts/update-engine.sh. Nothing new starts while it's here, so what's running can finish before the broker stops.
DRAINING = runtime.BROKER / "draining"
MOST_DRAINING_SECONDS = 1500  # Longer than any job can run, so that a script that died can't leave the broker idle for good.
PROD_LOG = runtime.RUNTIME / "prod" / "logs" / "latest.log"
MOST_LOG_LINES = 200
MOST_LOG_CHARACTERS = 16000
WENT_WRONG = re.compile(r"\b(WARN|ERROR|FATAL)\b|Exception|^\s+at |^Caused by")
IP_ADDRESS = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b")
LOG_NOISE = ("minecraftservices", "authlib", "Services are unavailable")
# Only these, because the rest of what a server command can do would get around the gates. All of them apply to everyone.
RULES = {"players_sleeping_percentage": lambda value: isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100,
         "spawn_phantoms": lambda value: isinstance(value, bool), "keep_inventory": lambda value: isinstance(value, bool)}


def assemble(commit, lane=""):
    """Trusted code plus the agent's features and documents, as they were at one commit."""
    assembled = runtime.lane_folder(lane) / "assembled"
    runtime.sync_tree(runtime.REPO, assembled, ".env", "build/", ".gradle/", "run/", "runtime/")
    features = assembled / "mods" / "genesis" / "features"
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
    subprocess.run(["tar", "-x", "-C", str(assembled), "mods/genesis/features", "bible"], input=archive.stdout, check=False)
    return assembled


def promote(commit, release_id, *flags, lane=""):
    source = assemble(commit, lane)
    if far.is_far(lane):
        report = far.run(source, release_id, flags, lane)
    else:
        # If this run dies before reporting, the agent must hear that rather than the previous run's result.
        last = runtime.lane_folder(lane) / "last.json"
        last.unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, "-m", "broker.promote", "--source", str(source), "--release-id", release_id, *flags],
            cwd=runtime.REPO, env={**os.environ, "BROKER_LANE": lane}, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=1200,
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


def javap(class_name, private=False, code=""):
    """Public members by default. A mixin needs to see the rest, and code shows what's inside one method, which is what it patches."""
    if not all(part.replace("$", "").isidentifier() for part in class_name.split(".")):
        return {"reason": "That isn't a class name."}
    if code and not code.replace("$", "").replace("<", "").replace(">", "").isidentifier():
        return {"reason": "That isn't a method name."}
    flags = "-p -c" if code else "-p" if private else "-public"
    result = runtime.run(
        ["./scripts/stack.sh", "run", "--rm", "-T", "builder", "bash", "-c",
         f"CP=$(find /cache/gradle/caches/modules-2/files-2.1/net.fabricmc.fabric-api -name '*.jar' | tr '\\n' ':'); "
         f"javap {flags} -cp \"{CACHE_JAR}:$CP\" '{class_name}'"],
        check=False, timeout=60,
    )
    lines = [line for line in result.stdout.splitlines() if "Container " not in line]
    return {"output": "\n".join(_one_method(lines, code, class_name) if code else lines)[:MOST_JAVAP_CHARACTERS]}


def _one_method(lines, name, class_name):
    """javap prints a class's methods one after another, each with a blank line after it, and everything inside it indented further.
    A constructor is printed under the class's name, and a static initialiser as static {}."""
    heading = {"<init>": f" {class_name}(", "<clinit>": "static {}"}.get(name, f" {name}(")
    kept, inside = [], False
    for line in lines:
        if line.startswith("  ") and not line.startswith("    "):
            inside = heading in line
        if inside:
            kept.append(line)
    return kept or [f"There's no method called {name} in that class."]


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


def handle(request, lane=""):
    kind = request["kind"]
    if runtime.agent_disabled() and kind != "javap":
        return {"result": "blocked", "gate": "control", "reason": "The kill switch is on."}
    release_id = request.get("release_id", f"check-{request['id']}")
    if kind == "lint":
        return promote(request["commit"], release_id, "--lint-only", lane=lane)
    if kind == "server_icon":
        return install_icon()
    if kind == "set_rule":
        return set_rule(request["rule"], request["value"])
    if kind == "check":
        return promote(request["commit"], release_id, "--check-only", lane=lane)
    if kind == "gates":
        return promote(request["commit"], release_id, "--no-deploy", lane=lane)
    if kind == "release":
        return promote(request["commit"], release_id, f"--why={request.get('why', '')}", lane=lane)
    if kind == "javap":
        return javap(request["class_name"], bool(request.get("private")), str(request.get("code") or ""))
    if kind == "server_errors":
        return server_errors(request.get("contains", ""))
    return {"result": "blocked", "gate": "broker", "reason": f"Unknown request {kind}"}


def _save_started(started):
    temporary = STARTED.with_suffix(".tmp")
    temporary.write_text(json.dumps(started), encoding="utf-8")
    temporary.replace(STARTED)


def started_again(request_id):
    """How many times this request has been started. The record outlives the broker, because that's what it's for: a job
    that kills the broker is otherwise picked up again as soon as it's back, and everything else waits behind it forever."""
    started = json.loads(STARTED.read_text(encoding="utf-8")) if STARTED.exists() else {}
    started = {key: count for key, count in started.items() if (REQUESTS / f"{key}.json").exists()}
    started[request_id] = started.get(request_id, 0) + 1
    _save_started(started)
    return started[request_id]


def didnt_count(request_id):
    """The machine it was sent to let it down, which didn't harm the broker, so that wasn't one of its tries."""
    started = json.loads(STARTED.read_text(encoding="utf-8")) if STARTED.exists() else {}
    if started.get(request_id):
        started[request_id] -= 1
        _save_started(started)


def next_request(pending):
    """With several builders working, a quick check shouldn't wait behind everyone else's full test run, and a small change a
    player is waiting for goes ahead of a big one that's being built in the background. So does a release, because that's
    finished work that everything still being tested would otherwise have to be tested again on top of. A bug fix goes ahead of all of those."""
    def order(path):
        request = json.loads(path.read_text(encoding="utf-8"))
        return (0 if request["kind"] in QUICK else 1 if request.get("first") else 2 if request.get("hurry") or request["kind"] == "release" else 3, path.stat().st_mtime)
    return min(pending, key=order)


def lanes_for(kind):
    """Which lanes a kind of job can run in, in the order they're used. A lane holds one job at a time. A release uses a test lane
    like anything else, because it needs a test server unless what it's releasing has just passed. No lane is the first one."""
    if kind in AT_ONCE:
        return [f"{kind}-{number}" for number in range(MOST_AT_ONCE)]
    if kind == "check":
        return [f"check-{number}" for number in range(CHECK_LANES)]
    here = ["", *(f"gates-{number}" for number in range(1, GATE_LANES))]
    # A test run goes to another machine if there is one, which keeps this one's lanes free for releases, and those are only ever proved here.
    return [*far.lanes(), *here] if kind == "gates" else here


def memory_available_gb():
    for line in pathlib.Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 ** 2
    raise RuntimeError("The system doesn't say how much memory is available.")


def room_for(kind, lane, running):
    """Only big jobs need room, and only beside other big jobs on this machine. One by itself always goes ahead, or a small machine would never do anything."""
    big = [job for job in running.values() if job.kind in BIG_JOBS and not far.is_far(job.lane)]
    if kind not in BIG_JOBS or not big or far.is_far(lane):
        return True
    new_lane = NEW_LANE_GB if lane.startswith("gates-") and lane not in lanes_used else 0
    settling = sum(BIG_JOBS[job.kind] for job in big if time.monotonic() - job.began < SETTLING_SECONDS)
    return memory_available_gb() - settling >= BIG_JOBS[kind] + new_lane + KEEP_FREE_GB


def free_lane(kind, running):
    """The lane a job of this kind can start in now, or None if it has to wait. Releases go one at a time, however many lanes there
    are, because there's one signer, one ledger and one live server, and each is tested on top of the last."""
    if kind == "release" and any(job.kind == "release" for job in running.values()):
        return None
    taken = {job.lane for job in running.values()}
    lane = next((lane for lane in lanes_for(kind) if lane not in taken), None)
    return lane if lane is not None and room_for(kind, lane, running) else None


def draining():
    try:
        return time.time() - DRAINING.stat().st_mtime < MOST_DRAINING_SECONDS
    except FileNotFoundError:
        return False


Job = collections.namedtuple("Job", "kind lane thread began release_id", defaults=(None,))
lanes_used = set()
given_back = set()  # Requests another machine let down, which go round again here without anyone hearing about it.


def finish(path, request, answer, seconds, waited):
    # Written in one go, because several jobs can be finishing at once and each line has to stay whole.
    sys.stdout.write(f"{request['kind']} {request['id']}: {answer.get('result', 'answered')} in {seconds:.1f}s, after waiting {waited:.1f}s\n")
    sys.stdout.flush()
    temporary = RESPONSES / f".{request['id']}.tmp"
    temporary.write_text(json.dumps(answer), encoding="utf-8")
    temporary.rename(RESPONSES / f"{request['id']}.json")
    path.unlink(missing_ok=True)


def run_job(path, request, lane, waited):
    began = time.monotonic()
    try:
        answer = handle(request, lane)
    except far.Gone as error:
        sys.stdout.write(f"{request['kind']} {request['id']}: the test machine let it down, so it's going again here: {error}\n")
        sys.stdout.flush()
        given_back.add(path.name)
        return
    except Exception as error:  # noqa: BLE001 - the agent should hear about any failure, not hang
        answer = {"result": "blocked", "gate": "broker", "reason": f"{type(error).__name__}: {error}"}
    finish(path, request, answer, time.monotonic() - began, waited)


def start_job(path, running):
    """Raises FileNotFoundError if whoever asked has stopped waiting and taken it back."""
    request = json.loads(path.read_text(encoding="utf-8"))
    waited = time.time() - path.stat().st_mtime
    lane = free_lane(request["kind"], running)
    if lane is None:
        return  # Memory has gone since it was last looked at, so this waits for the next look.
    if started_again(request["id"]) > TRIES_BEFORE_REFUSING:
        finish(path, request, {"result": "blocked", "gate": "broker",
                               "reason": f"The broker itself died each of the {TRIES_BEFORE_REFUSING} times it ran this, so it hasn't been checked. "
                                         "That may well not be anything in your work."}, 0, waited)
        return
    thread = threading.Thread(target=run_job, args=(path, request, lane, waited), daemon=True)
    running[path.name] = Job(request["kind"], lane, thread, time.monotonic(), request.get("release_id"))
    lanes_used.add(lane)
    thread.start()


def can_start(path, running):
    """Someone who's waited a very long time asks again with the same name, and the earlier one may still be running. They'd share a
    report folder, so the second waits."""
    if path.name in running:
        return False
    request = json.loads(path.read_text(encoding="utf-8"))
    if request.get("release_id") and request["release_id"] in {job.release_id for job in running.values()}:
        return False
    return free_lane(request["kind"], running) is not None


def note_if_given_back(name):
    if name in given_back:
        given_back.discard(name)
        didnt_count(name.removesuffix(".json"))


def tick(running):
    """Starts the next job there's room for. Returns whether it did, because then there may be room for another straight away."""
    for name in [name for name, job in running.items() if not job.thread.is_alive()]:
        del running[name]
        note_if_given_back(name)
    if draining():
        return False
    try:
        ready = [path for path in REQUESTS.glob("*.json") if can_start(path, running)]
        if not ready:
            return False
        start_job(next_request(ready), running)
    except FileNotFoundError:
        pass  # Whoever asked has stopped waiting and taken it back.
    return True


def retry_suspects():
    """Whatever was running when the broker stopped might be what stopped it, so after a restart each goes by itself, with nothing
    beside it. Otherwise a harmless job that happened to be running next to a bad one would use up its tries as well."""
    started = json.loads(STARTED.read_text(encoding="utf-8")) if STARTED.exists() else {}
    suspects = [path for path in REQUESTS.glob("*.json") if path.stem in started]
    while suspects:
        if draining():
            time.sleep(POLL_SECONDS)
            continue
        try:
            path = next_request(suspects)
        except FileNotFoundError:
            suspects = [path for path in suspects if path.exists()]
            continue
        suspects.remove(path)
        running = {}
        try:
            start_job(path, running)
        except FileNotFoundError:
            continue
        for job in running.values():
            job.thread.join()
        note_if_given_back(path.name)


def look_over_lanes():
    """A test server stays up between jobs so the next one is quicker, and that outlives the broker. One that's up is already using its memory,
    so starting a job there needs less room. One in a lane that's been taken away would only be using memory, so it's stopped. The
    services are named, because this should only ever stop these three."""
    for folder in (runtime.RUNTIME / "lanes").glob("gates-*"):
        env = runtime.shadow_env(folder.name)
        if int(folder.name.removeprefix("gates-")) >= GATE_LANES:
            runtime.run(["./scripts/stack.sh", "--profile", "shadow", "--profile", "lanes", "stop", "shadow", "shadow-proxy", "shadow-pack"], env=env, check=False)
        elif "true" in runtime.run(["docker", "inspect", "-f", "{{.State.Running}}", f"{env['COMPOSE_PROJECT_NAME']}-shadow-1"], check=False).stdout:
            lanes_used.add(folder.name)


def watch_mixins():
    """Beside everything else, because a live server that keeps crashing shouldn't have to wait for someone's test run to end."""
    while True:
        time.sleep(MIXIN_WATCH_SECONDS)
        try:
            deploy.check_for_mixin_crashes()
        except Exception as error:  # noqa: BLE001 - this has to keep watching whatever goes wrong with one look
            print(f"mixin watch: {type(error).__name__}: {error}", flush=True)


def main():
    for folder in (REQUESTS, RESPONSES, REPORTS_FOR_AGENT):
        folder.mkdir(parents=True, exist_ok=True)
    # Vanilla's own art, for builders to compare theirs with. The game's jar is outside the agent's reach.
    client_jar = runtime.RUNTIME / CACHE_JAR.removeprefix("/")
    if client_jar.exists():
        reference_textures.extract(client_jar, WORKSPACE / "reference-textures")
    DRAINING.unlink(missing_ok=True)
    # If memory does run out, the system should stop this, and what it's running, rather than the live server. See started_again.
    pathlib.Path("/proc/self/oom_score_adj").write_text("500", encoding="utf-8")
    look_over_lanes()
    threading.Thread(target=watch_mixins, daemon=True).start()
    print("broker waiting for requests", flush=True)
    retry_suspects()
    running = {}
    while True:
        if not tick(running):
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
