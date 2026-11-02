"""Test runs and compile checks on another machine, so that they don't use the memory and cores of the one people are playing on.

The broker stays in charge. It sends what a job needs over SSH, runs the same broker code there, and brings back the report and pictures.
That machine holds no key or secret of this one's, so unchecked work that gets loose there has no way back here. A pass from there is only
ever kept there, so it can't let a release skip its tests, and the most a machine that's gone wrong could do is mislead a builder.

Each lane here is a lane of the same name there, where the live server isn't running, so the gates copy the world they're sent as if it
were the live one and need no changes. Set one up with scripts/add-test-machine.sh.
"""
import json
import re
import shlex
import subprocess
import threading
import time

from broker import runtime
from broker.gates import shadow

MACHINE = runtime.ENV.get("TEST_MACHINE", "")
HOME = runtime.ENV.get("TEST_MACHINE_HOME", "/srv/livingmod")
LANES = {"gates": int(runtime.ENV.get("FAR_LANES", "0")) if MACHINE else 0, "check": int(runtime.ENV.get("FAR_CHECK_LANES", "0")) if MACHINE else 0}
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4", "-o", "StrictHostKeyChecking=accept-new"]
WORLD_MOST_STALE_SECONDS = 600  # A test only needs a recent world, and this is what saving being turned off and the transfer cost.
DOWN_SECONDS = 300  # How long to leave a machine alone after it's let a job down.
RUN_SECONDS = 1100  # Less than the broker gives a job anywhere, so this gives up first and it can still run here.
SEND_SECONDS = 1800  # Long enough to send the whole world the first time.
AGAIN_SECONDS = 2  # A busy machine can drop a connection now and then, which shouldn't send everything back here for 5 minutes.
KEEP_DAYS = 2  # Old releases and pictures there, which nothing uses again.
RESULTS = ("passed_gates", "nothing_to_release", "blocked")
MOST_REASON_CHARACTERS = 4000
MOST_PICTURE_SIZE = "20m"

down_until = 0
world_sent = None
records_sent = None
sending_world = threading.Lock()
sending_records = threading.Lock()


class Gone(Exception):
    """The machine couldn't do the job, which says nothing about the work, so whoever asked shouldn't hear about it. It runs here instead."""


def is_far(lane):
    return lane.startswith("far-")


def lanes(kind):
    """Empty if there's no machine, or it let a job down a moment ago."""
    return [f"far-{kind}-{number}" for number in range(1, LANES[kind] + 1)] if time.monotonic() >= down_until else []


def mark_down():
    global down_until
    down_until = time.monotonic() + DOWN_SECONDS


def _run(command, timeout):
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise Gone(f"{command[0]} took over {timeout}s") from error


def _ssh(command, timeout=60, again=True):
    """Only something that's safe to do twice can go again, because a job's connection dropping doesn't stop the job."""
    result = _run([*SSH, MACHINE, command], timeout)
    if result.returncode == 255 and again:
        time.sleep(AGAIN_SECONDS)
        result = _run([*SSH, MACHINE, command], timeout)
    if result.returncode == 255:
        raise Gone(f"can't reach it: {result.stderr[-300:]}")
    return result


def _rsync(*arguments, timeout=SEND_SECONDS):
    command = ["rsync", "-a", "-e", " ".join(SSH), *arguments]
    result = _run(command, timeout)
    if result.returncode != 0:
        time.sleep(AGAIN_SECONDS)
        result = _run(command, timeout)
    if result.returncode != 0:
        raise Gone(f"rsync failed: {result.stderr[-300:]}")


def prepare_folders(*others):
    _ssh(f"mkdir -p {HOME}/runtime/broker {HOME}/runtime/cache {HOME}/runtime/releases/history {HOME}/runtime/prod/world {' '.join(others)}")


def send_release_records():
    """What this release was built from, because a test run is compared with it, and everything's built on what it's used up. It's only sent when
    it's changed, which saves several connections for every job. The lock's held throughout, so nothing can start on the old one's records."""
    global records_sent
    with sending_records:
        current = runtime.load_state().get("current")
        if records_sent is not None and current == records_sent:
            return
        if runtime.STATE_FILE.exists():
            _rsync(str(runtime.STATE_FILE), f"{MACHINE}:{HOME}/runtime/broker/state.json")
        if current and (runtime.HISTORY / current).exists():
            _rsync("--delete", f"{runtime.HISTORY / current}/", f"{MACHINE}:{HOME}/runtime/releases/history/{current}/")
        # The game's own jar, which says what format the game expects.
        _rsync("--delete", f"{runtime.RUNTIME / 'prod' / 'versions'}/", f"{MACHINE}:{HOME}/runtime/prod/versions/")
        _ssh(f"find {HOME}/runtime/releases/history {HOME}/runtime/broker/reports -mindepth 1 -maxdepth 1 -mtime +{KEEP_DAYS} ! -name {shlex.quote(str(current))} -exec rm -rf {{}} + 2>/dev/null; true")
        records_sent = current


def send_world():
    """Copied here with saving off, because that's quick, and only then sent, so that saving isn't off for as long as the network takes. It holds
    the lock the machine's own copying uses while it's arriving, so that a test can't start from a world that's half here."""
    global world_sent
    with sending_world:
        if world_sent is not None and time.monotonic() - world_sent < WORLD_MOST_STALE_SECONDS:
            return
        snapshot = runtime.lane_folder("far-world") / "world"
        try:
            shadow.copy_live_world(snapshot)
        except (RuntimeError, OSError) as error:
            raise Gone(f"couldn't copy the world to send it: {error}") from error
        _rsync("--delete", f"--rsync-path=flock {HOME}/runtime/broker/world.lock rsync", f"{snapshot}/", f"{MACHINE}:{HOME}/runtime/prod/world/")
        world_sent = time.monotonic()


def _bring_back_pictures(report, release_id):
    """Only pictures, only from where they should be, and only so big."""
    allowed = re.compile(rf"{re.escape(HOME)}/runtime/broker/reports/[\w.-]+/[\w.-]+\.png")
    wanted = [path for path in report.get("screenshots", []) if isinstance(path, str) and allowed.fullmatch(path)]
    if not wanted:
        return []
    target = runtime.REPORTS / release_id
    target.mkdir(parents=True, exist_ok=True)
    _rsync(f"--max-size={MOST_PICTURE_SIZE}", *(f"{MACHINE}:{path}" for path in wanted), f"{target}/")
    return [str(target / path.rsplit("/", 1)[-1]) for path in wanted]


def _bring_back_diagnostics(report, release_id):
    allowed = re.compile(rf"{re.escape(HOME)}/runtime/broker/reports/[\w-][\w.-]*/(?:shadow(?:-proxy)?\.log|client\.log|registry-ledger\.json|crash-[\w.-]+\.txt)")
    wanted = [path for path in report.get("diagnostics", []) if isinstance(path, str) and allowed.fullmatch(path)][:20]
    if not wanted:
        return []
    target = runtime.REPORTS / release_id
    target.mkdir(parents=True, exist_ok=True)
    _rsync("--max-size=16m", *(f"{MACHINE}:{path}" for path in wanted), f"{target}/")
    return [str(target / path.rsplit("/", 1)[-1]) for path in wanted]


def _believed(report, release_id):
    """That machine runs unchecked work, so it's not taken at its word about anything but how a test went."""
    if not isinstance(report, dict) or report.get("result") not in RESULTS:
        raise Gone(f"it sent back a report that makes no sense: {str(report)[:200]}")
    kept = {key: report[key] for key in ("result", "gate", "tier", "stages", "shadow", "total_seconds", "advice") if key in report}
    if "reason" in report:
        kept["reason"] = str(report["reason"])[:MOST_REASON_CHARACTERS]
    if report.get("diagnostics"):
        kept["diagnostics"] = _bring_back_diagnostics(report, release_id)
    return {**kept, "release": release_id, "screenshots": _bring_back_pictures(report, release_id)}


def run(source, release_id, flags, lane):
    """Runs one test run or compile check there. Raises Gone if the machine can't, having marked it down so that nothing else tries it for a while."""
    if not {"--no-deploy", "--check-only"} & set(flags):
        raise ValueError("Only test runs and compile checks go to another machine. A release has to be proved here.")
    there = lane.removeprefix("far-")
    repo = f"{HOME}/repo-{there}"
    last = f"{HOME}/runtime/lanes/{there}/last.json"
    arguments = " ".join(shlex.quote(part) for part in ("--source", repo, "--release-id", release_id, *flags))
    # A lock, because if the broker here restarts, the job there carries on, and the next one in this lane has to wait for it to finish.
    command = (f". {HOME}/environment && mkdir -p {HOME}/runtime/lanes/{there} && cd {repo} && ln -sf {HOME}/machine.env .env && rm -f {last} && "
               f"BROKER_LANE={there} PYTHONDONTWRITEBYTECODE=1 flock -w {RUN_SECONDS} {HOME}/runtime/lanes/{there}.lock "
               f"timeout {RUN_SECONDS} python3 -m broker.promote {arguments} >/dev/null 2>&1; cat {last}")
    try:
        prepare_folders(repo)
        send_release_records()
        send_world()
        _rsync("--delete", "--checksum", "--exclude=.env", "--exclude=build/", "--exclude=.gradle/", "--exclude=run/", f"{source}/", f"{MACHINE}:{repo}/")
        result = _ssh(command, timeout=RUN_SECONDS * 2 + 60, again=False)
        try:
            report = json.loads(result.stdout)
        except ValueError as error:
            raise Gone(f"it finished with no report: {result.stderr[-300:]}") from error
        return _believed(report, release_id)
    except Gone:
        mark_down()
        raise
