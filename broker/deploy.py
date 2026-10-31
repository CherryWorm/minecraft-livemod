"""Puts a release on the live server, watches it, and rolls back on its own if it goes wrong."""
import shutil
import time

from broker import runtime
from broker.gates import shadow

HEALTH_SECONDS = {"T1": 10, "T2": 15, "T3": 40}
SAFE_WAIT_SECONDS = 60
BACKUPS_KEPT = 10


class RolledBack(Exception):
    pass


def wait_for_safe_moment():
    """Waits up to a minute for everyone to be out of danger, then goes ahead regardless."""
    deadline = time.monotonic() + SAFE_WAIT_SECONDS
    while time.monotonic() < deadline:
        status = runtime.rcon("prod", "conduit", "unsafe", check=False)
        if status.endswith(": 0") or "Unknown" in status or "Incorrect" in status or not status:
            return True
        time.sleep(2)
    return False


def backup():
    """A compressed copy of the world, kept out of the agent's reach."""
    backups = runtime.RUNTIME / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"world-{time.strftime('%Y%m%d-%H%M%S')}.tar.zst"
    prod = runtime.inspect_state("prod")
    running = bool(prod and prod.get("Running"))
    if running:
        runtime.rcon("prod", "save-off")
        runtime.rcon("prod", "save-all", "flush")
    try:
        runtime.run(["tar", "--zstd", "-cf", str(target), "--exclude=session.lock", "-C",
                     str(runtime.RUNTIME / "prod"), "world"], timeout=600)
    finally:
        if running:
            runtime.rcon("prod", "save-on")
    for old in sorted(backups.glob("world-*.tar.zst"))[:-BACKUPS_KEPT]:
        old.unlink()
    return target


def store_release(release_id, jars, content, ledger_path):
    """Keeps a full copy of each release, which is what rollback restores."""
    folder = runtime.HISTORY / release_id
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "jars").mkdir(parents=True)
    for jar in jars:
        shutil.copy(jar, folder / "jars")
    shutil.copytree(content, folder / "content")
    shutil.copy(ledger_path, folder / "registry-ledger.json")
    return folder


def _install_jars(folder):
    current = runtime.RELEASES / "current"
    current.mkdir(parents=True, exist_ok=True)
    for old in current.glob("*.jar"):
        old.unlink()
    for jar in (folder / "jars").glob("*.jar"):
        shutil.copy(jar, current)


def _restart_prod():
    runtime.run(["./scripts/stack.sh", "restart", "prod"], timeout=180)
    runtime.wait_ready("prod", timeout=180)
    runtime.rcon("prod", "datapack", "enable", '"file/gm_content"', check=False)


def health_check(tier, mark):
    """Returns a reason if the server looks unwell during the watch period, otherwise None."""
    before = runtime.inspect_state("prod")
    restarts = before["RestartCount"] if before else 0
    deadline = time.monotonic() + HEALTH_SECONDS.get(tier, 15)
    while time.monotonic() < deadline:
        state = runtime.inspect_state("prod")
        if state is None or not state.get("Running"):
            return "the server stopped running"
        if state["RestartCount"] != restarts:
            return "the server crashed and restarted"
        problems = shadow.scan_logs(runtime.logs_since("prod", mark))
        if problems:
            return "the server logged problems: " + "; ".join(problems[:4])
        time.sleep(2)
    if runtime.run(["./scripts/mc.sh", "list"], check=False).returncode != 0:
        return "the server stopped answering commands"
    return None


def deploy(tier, release_folder):
    """Applies a stored release to prod. Raises RolledBack if it had to be undone."""
    state = runtime.load_state()
    safe = wait_for_safe_moment()
    mark = runtime.utc_now()
    content = release_folder / "content"
    backup_file = None
    if tier == "T3":
        backup_file = backup()
        _install_jars(release_folder)
        runtime.apply_content("prod", content)
        # A crash during the restart has to count as this release's failure, so the watch starts first.
        try:
            _restart_prod()
        except (TimeoutError, RuntimeError) as error:
            reason = f"the server didn't come back: {error}"
            rollback(state, reason)
            raise RolledBack(reason) from error
    else:
        runtime.apply_content("prod", content)
        runtime.reload_content("prod")

    reason = health_check(tier, mark)
    if reason:
        rollback(state, reason)
        raise RolledBack(reason)

    state["previous"] = state.get("current")
    state["current"] = release_folder.name
    runtime.save_state(state)
    return {"safe_moment": safe, "backup": str(backup_file) if backup_file else None}


def rollback(state, reason):
    """Restores the last good release. Blocks and items keep their slots, so nothing leaves the world."""
    print(f"rolling back: {reason}", flush=True)
    chaos = runtime.RUNTIME / "prod" / "config" / "conduit" / "chaos_crash_after_ticks"
    if chaos.exists():
        chaos.unlink()
    previous = state.get("current")
    if previous and (runtime.HISTORY / previous).exists():
        folder = runtime.HISTORY / previous
        _install_jars(folder)
        runtime.apply_content("prod", folder / "content")
    _restart_prod()
