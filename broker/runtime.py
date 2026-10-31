"""Talking to the stack: paths, compose, server commands and logs."""
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
WORK = BROKER / "work"
REPORTS = BROKER / "reports"
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
    return run(["./scripts/stack.sh", "--profile", "shadow", "--profile", "tools", *args], env=env, check=check, timeout=timeout)


def rcon(server, *command, check=True):
    result = run(["./scripts/mc.sh", "--server", server, *command], check=check)
    return (result.stdout or "").strip()


def container(server):
    return f"livingmod-{server}-1"


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
        result = run(["./scripts/mc.sh", "--server", server, "list"], check=False)
        if result.returncode == 0:
            return time.monotonic() - started
        time.sleep(0.5)
    raise TimeoutError(f"{server} didn't answer within {timeout}s")


def load_state():
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {"current": None, "previous": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")


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
    data = RUNTIME / server
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
    pack = RUNTIME / server / "polymer" / "resource_pack.zip"
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
