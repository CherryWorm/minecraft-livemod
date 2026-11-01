"""Talking to the stack: paths, compose, server commands and logs."""
import contextlib
import fcntl
import json
import os
import pathlib
import re
import subprocess
import time

REPO = pathlib.Path(__file__).resolve().parent.parent


def _read_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


ENV = {**_read_env(REPO / "versions.env"), **_read_env(REPO / ".env")}
RUNTIME = pathlib.Path(ENV["RUNTIME_DIR"])
BROKER = RUNTIME / "broker"


def lane_folder(lane):
    """Where a job in this lane keeps its files, so that jobs running at the same time can't touch each other's. No lane is
    the folders the broker has always used, which is also where anything run by hand works."""
    return RUNTIME / "lanes" / lane if lane else BROKER


LANE = os.environ.get("BROKER_LANE", "")
WORK = lane_folder(LANE) / "work"
LAST_REPORT = lane_folder(LANE) / "last.json"
DIFF = lane_folder(LANE) / "diff"
REPORTS = BROKER / "reports"
PROJECT = ENV.get("COMPOSE_PROJECT_NAME", "livingmod")
FIRST_LANE_PORT = 25570


def shadow_env(lane):
    """Compose settings for this lane's test server. It's the same services under another project name, with folders and ports of
    its own, so a mistake can't reach the live server: to compose, that's not in this project at all. The first lane doesn't
    need any, because it's what the compose file says already."""
    if not lane.startswith("gates-"):
        return {}
    number = int(lane.removeprefix("gates-"))
    return {"COMPOSE_PROJECT_NAME": f"{PROJECT}-{lane}", "SHADOW_FOLDER": str(lane_folder(lane)),
            "SHADOW_PROXY_PORT": str(FIRST_LANE_PORT + number * 2), "SHADOW_PACK_PORT": str(FIRST_LANE_PORT + number * 2 + 1)}


SHADOW_ENV = shadow_env(LANE)
SHADOW_PROXY_PORT = SHADOW_ENV.get("SHADOW_PROXY_PORT") or ENV.get("SHADOW_PROXY_PORT", "25566")
# The first lane's test server has the site as its way in to its resource pack, and the others have a service of their own for that.
SHADOW_SERVICES = ("--no-deps", "shadow", "shadow-proxy", "shadow-pack") if SHADOW_ENV else ("shadow", "shadow-proxy")


def server_folder(server):
    return lane_folder(LANE) / server if server.startswith("shadow") and SHADOW_ENV else RUNTIME / server


def candidate_folder():
    """The jars this lane's test server starts with."""
    return lane_folder(LANE) / "candidate" if SHADOW_ENV else RELEASES / "candidate"


def _compose_env(server):
    return SHADOW_ENV if server == "shadow" else {}


@contextlib.contextmanager
def world_lock():
    """Held while the live world is being copied, backed up or restarted. Saving is turned off for a copy and back on after it, so if
    two overlapped, the first to finish would turn it back on while the other was still copying, and that copy could be torn."""
    BROKER.mkdir(parents=True, exist_ok=True)
    with (BROKER / "world.lock").open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
RELEASES = RUNTIME / "releases"
HISTORY = RELEASES / "history"
STATE_FILE = BROKER / "state.json"
TIMELINE = RUNTIME / "timeline.jsonl"
CONTROL = RUNTIME / "control"
AGENT_DISABLED = CONTROL / "agent_disabled"
OWNER_KILL_SWITCH = RUNTIME / "prod" / "config" / "conduit" / "agent_disabled"


def agent_disabled():
    """Set from this host, or by the owner from inside the game. Either one stops every release."""
    return AGENT_DISABLED.exists() or OWNER_KILL_SWITCH.exists()


def tools_cache():
    """Compose settings that give this lane's builds a copy of Gradle's files of their own. Loom holds a lock on them while it sets a
    build up, and another build fails after a minute of waiting, so they can't be shared by builds at the same time. Each copy
    starts from the main one, so it doesn't have to download everything, and it's mounted at the same place, because Gradle and
    Loom remember paths. The locks are left out because they'd say a build that's running now in the main one was running here."""
    if not LANE:
        return {}
    cache = lane_folder(LANE) / "cache"
    if not cache.exists():
        partial = cache.with_name("cache.partial")
        sync_tree(RUNTIME / "cache", partial, "*.lock", "daemon/")
        partial.rename(cache)
    return {"TOOLS_CACHE": str(cache)}


def run(command, *, check=True, capture=True, env=None, timeout=None, cwd=REPO):
    """Runs a command with stdin closed, so nothing it starts can swallow a caller's input."""
    result = subprocess.run(
        command, cwd=cwd, env={**os.environ, **(env or {})}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None,
        text=True, timeout=timeout, check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, command))} failed:\n{(result.stdout or '')[-2000:]}")
    return result


def stack(*args, env=None, check=True, timeout=None):
    """The test server's own compose project, so this lane's if it's in one."""
    return run(["./scripts/stack.sh", "--profile", "shadow", "--profile", "tools", *args], env={**SHADOW_ENV, **(env or {})}, check=check, timeout=timeout)


def rcon(server, *command, check=True):
    result = run(["./scripts/mc.sh", "--server", server, *command], check=check, env=_compose_env(server))
    return (result.stdout or "").strip()


def container(server):
    return f"{_compose_env(server).get('COMPOSE_PROJECT_NAME', PROJECT)}-{server}-1"


def inspect_state(server):
    result = run(["docker", "inspect", container(server), "--format", "{{json .State}}|{{.RestartCount}}"], check=False)
    if result.returncode != 0:
        return None
    state, restarts = result.stdout.strip().rsplit("|", 1)
    return {**json.loads(state), "RestartCount": int(restarts)}


def logs_since(server, since):
    result = run(["docker", "logs", "--since", since, container(server)], check=False)
    return result.stdout or ""


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def wait_ready(server, timeout=180):
    """Waits until the server answers commands. Returns the seconds it took."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        result = run(["./scripts/mc.sh", "--server", server, "list"], check=False, env=_compose_env(server))
        if result.returncode == 0:
            return time.monotonic() - started
        time.sleep(0.5)
    raise TimeoutError(f"{server} didn't answer within {timeout}s")


def load_state():
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {"current": None, "previous": None}


def save_state(state):
    """Replaced in one step, because jobs running beside a release read this while it's being changed."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    temporary.replace(STATE_FILE)


def record_timeline(entry):
    TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    with TIMELINE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": utc_now(), **entry}) + "\n")


def data_format():
    """The data pack version the running game expects, read from the game's own jar."""
    import zipfile

    for folder in ("prod", "shadow"):
        for jar in (RUNTIME / folder).glob("versions/*/server-*.jar"):
            with zipfile.ZipFile(jar) as archive:
                return json.loads(archive.read("version.json"))["pack_version"]["data_major"]
    raise RuntimeError("No server jar found. Start prod once first.")


def sync_tree(source, target, *excludes, exact=False):
    """exact compares what's in each file. Otherwise two edits of the same size in the same second look unchanged."""
    target.mkdir(parents=True, exist_ok=True)
    command = ["rsync", "-a", "--delete", *(["--checksum"] if exact else [])]
    for pattern in excludes:
        command += ["--exclude", pattern]
    run([*command, f"{source}/", f"{target}/"])


def apply_content(server, content):
    """Copies a release's content into a server's data folder."""
    data = server_folder(server)
    sync_tree(content / "pack", data / "live-assets")
    sync_tree(content / "datapack", data / "world" / "datapacks" / "gm_content")
    conduit_config = data / "config" / "conduit"
    conduit_config.mkdir(parents=True, exist_ok=True)
    # Other files live in this folder, such as tuning values, so it's copied over rather than mirrored.
    for source in (content / "config").glob("*.json"):
        (conduit_config / source.name).write_bytes(source.read_bytes())
    models = content / "config" / "models"
    if models.exists():
        sync_tree(models, conduit_config / "models")
    for side in ("server", "client"):
        source = content / "modules" / side
        source.mkdir(parents=True, exist_ok=True)
        sync_tree(source, data / "modules" / side)


def reload_content(server):
    """Makes a running server pick up what apply_content wrote, without a restart."""
    rcon(server, "reload")
    time.sleep(1.5)
    listed = rcon(server, "datapack", "list", "enabled")
    if "gm_content" not in listed:
        rcon(server, "datapack", "enable", '"file/gm_content"', check=False)
        time.sleep(1.5)
    pack = server_folder(server) / "polymer" / "resource_pack.zip"
    before = pack.stat().st_mtime if pack.exists() else 0
    rcon(server, "polymer", "generate-pack", "reload")
    # Polymer reports completion to the command's sender, not the log, so the file is what to watch.
    for _ in range(120):
        if pack.exists() and pack.stat().st_mtime != before:
            break
        time.sleep(0.25)
    rcon(server, "conduit", "retrogen", "reload")
    rcon(server, "conduit", "modules", "reload")
    rcon(server, "conduit", "module", "reload")


def vanilla_biome(name):
    """A biome's definition, read from the game's own jar, so new biomes start from what's really there."""
    import zipfile

    path = name.split(":", 1)[-1]
    for folder in ("prod", "shadow"):
        for jar in (RUNTIME / folder).glob("versions/*/server-*.jar"):
            with zipfile.ZipFile(jar) as archive:
                try:
                    return json.loads(archive.read(f"data/minecraft/worldgen/biome/{path}.json"))
                except KeyError as error:
                    raise ValueError(f"There's no vanilla biome called {name}") from error
    raise RuntimeError("No server jar found. Start prod once first.")
