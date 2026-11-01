"""Puts a release on the live server, watches it, and rolls back on its own if it goes wrong."""
import hashlib
import json
import shutil
import time

from broker import runtime, sign
from broker.gates import mixins, shadow

CRASHED_MIXINS = runtime.BROKER / "crashed_mixins.json"
CRASHED_MIXINS_FOR_AGENT = runtime.RUNTIME / "agent-workspace" / "reports" / "crashed_mixins.json"
MIXIN_WATCH = runtime.BROKER / "mixin_watch.json"
MOST_CRASH_CHARACTERS = 4000
# A crash with no sign of any mixin may well be nothing to do with them, but one that keeps happening has to stop somehow.
CRASHES_BEFORE_ALL_MIXINS_GO = 3
CRASH_WINDOW_SECONDS = 600
HEALTH_SECONDS = {"T1": 10, "T2": 15, "T3": 40}
SAFE_WAIT_SECONDS = 60
BACKUPS_KEPT = 10
# Each by what the pack calls it, so each player's game says it in their language. What's changing is plain words from when it was built, which stay in English.
RELOADING = ("conduit.reloading", "Reloading the world for a moment. What's changing: %s.")
RESTARTING = ("conduit.restarting", "Restarting the server for a moment, and you'll be put back where you are. What's changing: %s.")
UNDOING = ("conduit.undoing", "Restarting the server for a moment to undo a change that went wrong, and you'll be put back where you are.")
NOTHING_NAMED = "an update to the game's engine"
MOST_WHY = 200
GAME_CODE = ("mods/conduit/src/main", "mods/companion/src/main")


class RolledBack(Exception):
    pass


def engine_reason(before):
    """What a restart for new engine code is for, from what's changed in the game's own code since this commit. Commit messages are public
    and only ever about what the engine can do, so they can't spoil anything in the world. New abilities first, because they're what players can look forward to."""
    log = runtime.run(["git", "log", "--format=%s", f"{before}..HEAD", "--", *GAME_CODE], check=False).stdout or ""
    changes = [line.split(", and ")[0] for line in log.splitlines() if line]
    if not changes:
        return ""
    changes.sort(key=lambda change: not change.startswith(("Add ", "Let ")))
    named = [change[0].lower() + change[1:] for change in changes[:2]]
    while len(named) > 1 and len("; ".join(named)) > MOST_WHY - 40:
        named.pop()
    more = len(changes) - len(named)
    return f"an engine update: {'; '.join(named)}" + (f", and {more} more" if more else "")


def tell_players(said, *values):
    """Said just before the game freezes or restarts, so nobody's left wondering why. Plain text with no model involved, because
    a model's answer would come after the reload it's explaining. If it can't be sent, the release goes ahead anyway."""
    key, english = said
    runtime.rcon("prod", "tellraw", "@a", json.dumps({"translate": key, "fallback": english, "color": "gray", **({"with": list(values)} if values else {})}), check=False)


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
        # Saving being off holds the chunks still, but mods replace their own small files beside them whenever they like. Tar says so by
        # exiting 1, and the copy is still good, so only a higher code means it failed.
        result = runtime.run(["tar", "--zstd", "-cf", str(target), "--exclude=session.lock", "-C",
                              str(runtime.RUNTIME / "prod"), "world"], check=False, timeout=600)
        if result.returncode > 1:
            raise RuntimeError(f"tar couldn't copy the world:\n{(result.stdout or '')[-2000:]}")
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


def deploy(tier, release_folder, why=""):
    """Applies a stored release to prod, first telling players why. Raises RolledBack if it had to be undone."""
    state = runtime.load_state()
    safe = wait_for_safe_moment()
    # Test runs in other lanes carry on meanwhile, so none of them can be copying the world while this changes or restarts it.
    with runtime.world_lock():
        tell_players(RESTARTING if tier == "T3" else RELOADING, (why or NOTHING_NAMED)[:MOST_WHY])
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
    tell_players(UNDOING)
    chaos =runtime.RUNTIME / "prod" / "config" / "conduit" / "chaos_crash_after_ticks"
    if chaos.exists():
        chaos.unlink()
    previous = state.get("current")
    if previous and (runtime.HISTORY / previous).exists():
        folder = runtime.HISTORY / previous
        _install_jars(folder)
        # Players may already have run the failed release's generation, and companions refuse anything older, so
        # the old code has to go out under a new generation. Signing trouble must never stop a rollback: the
        # server comes back either way, and at worst client modules stay off until the next release.
        try:
            sign.sign_release(folder / "content")
        except (sign.SigningError, OSError) as error:
            print(f"couldn't sign client modules for the rollback, so companions may refuse them: {error}", flush=True)
        runtime.apply_content("prod", folder / "content")
    else:
        # With no earlier release to go back to, the most this can do is take out what can stop a server from starting.
        for jar in (runtime.RELEASES / "current").glob(f"{mixins.JAR_PREFIX}*.jar"):
            jar.unlink()
    _restart_prod()


def crashed_mixins():
    """The mixins that have brought the live server down. These exact jars don't come back, and a changed one is a new try."""
    return json.loads(CRASHED_MIXINS.read_text(encoding="utf-8")) if CRASHED_MIXINS.exists() else {}


def _new_crash_reports(watch):
    """Crash reports not looked at yet, as (name, text). Reads nothing on the first look, because old ones were dealt with long ago."""
    reports = sorted((runtime.RUNTIME / "prod" / "crash-reports").glob("crash-*.txt"))
    seen = watch.get("seen")
    if seen is None:
        watch["seen"] = [path.name for path in reports]
        return []
    return [(path.name, path.read_text(encoding="utf-8", errors="replace")) for path in reports if path.name not in seen]


def _blamed(installed, text):
    """Which of these mixins a crash report points at, going by where the code was running. An exception's message could say anything."""
    frames = [line for line in text.splitlines() if line.lstrip().startswith("at ")]
    return sorted(feature_id for feature_id in installed if any(mark in frame for mark in mixins.crash_marks(feature_id) for frame in frames))


def _restarts_since(watch):
    """How many times Docker has started the live server again by itself since the last look. A server can stop with no crash report, by
    failing before there's any game to write one, or by being told to. Restarting it by hand starts the count again from nothing."""
    state = runtime.inspect_state("prod")
    now = state["RestartCount"] if state else watch.get("restarts", 0)
    since = max(0, now - watch.get("restarts", 0))
    watch["restarts"] = now
    return since


def _what_happened(text):
    """The part of a crash report that says what went wrong and where. What comes after it lists who's on and much else, and this goes to the agent."""
    return text.split("A detailed walkthrough", 1)[0][:MOST_CRASH_CHARACTERS]


def remove_mixins(state, feature_ids, reason, crash=""):
    """Takes mixins out of the release that's live and goes back through rollback, which puts it back without them. Only the mixin
    goes, because nothing else about what players have is at fault: its feature's blocks, items and modules stay."""
    current = runtime.HISTORY / state["current"]
    crashed = crashed_mixins()
    for feature_id in feature_ids:
        jar = current / "jars" / mixins.jar_name(feature_id)
        if jar.exists():
            crashed[feature_id] = {"sha256": hashlib.sha256(jar.read_bytes()).hexdigest(), "reason": reason[:400], "at": runtime.utc_now(), "crash": crash}
            jar.unlink()
    # Two copies: the broker only trusts its own, and the agent is told by the other, which is a bug to fix like any other.
    for path in (CRASHED_MIXINS, CRASHED_MIXINS_FOR_AGENT):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(crashed, indent=1) + "\n", encoding="utf-8")
    runtime.record_timeline({"release": state["current"], "stage": "mixin_removed", "features": feature_ids, "reason": reason[:400]})
    rollback(state, reason)


def check_for_mixin_crashes():
    """A release's health check only lasts a moment, and a mixin can be fine until someone first sits in a boat. Its code is part
    of the game's by then, so nothing can catch it the way the module host catches a module, and the server would go down again
    each time, perhaps every time it starts. So this keeps watching crash reports for as long as there are mixins on the server.
    Returns the features whose mixins it took out."""
    first_look = not MIXIN_WATCH.exists()
    watch = json.loads(MIXIN_WATCH.read_text(encoding="utf-8")) if not first_look else {}
    new = _new_crash_reports(watch)
    counted = watch.get("restarts")
    restarts = _restarts_since(watch)
    if first_look:
        restarts = 0
    removed = []
    if new or restarts:
        # A release might be under way, and it deals with a crash of its own. Then it's clear which release this crash belongs to.
        with runtime.world_lock():
            state = runtime.load_state()
            installed = sorted(filter(None, map(mixins.feature_of, (runtime.HISTORY / str(state.get("current")) / "jars").glob("*.jar"))))
            blamed = sorted({feature_id for _, text in new for feature_id in _blamed(installed, text)})
            reason = f"the server crashed, and {new[-1][0] if new else 'its log'} points to the mixins of {', '.join(blamed)}"
            now = time.time()
            recent = [at for at in watch.get("recent", []) if now - at < CRASH_WINDOW_SECONDS]
            if installed and not blamed:
                # Most crashes are a report and a restart, which is one crash.
                recent.extend(now for _ in range(max(len(new), restarts)))
                if len(recent) >= CRASHES_BEFORE_ALL_MIXINS_GO:
                    blamed = installed
                    reason = f"the server has stopped {len(recent)} times in {CRASH_WINDOW_SECONDS // 60} minutes with mixins on it, though no report points to one"
            watch["seen"] = [*watch["seen"], *(name for name, _ in new)]
            watch["recent"] = [] if blamed else recent
            # Written first, so that if this is what brings the broker down, it isn't done all over again.
            _save_watch(watch)
            if blamed:
                remove_mixins(state, blamed, reason, _what_happened(new[-1][1]) if new else "")
                removed = blamed
    elif first_look or watch["restarts"] != counted:
        _save_watch(watch)
    return removed


def _save_watch(watch):
    MIXIN_WATCH.parent.mkdir(parents=True, exist_ok=True)
    MIXIN_WATCH.write_text(json.dumps(watch) + "\n", encoding="utf-8")
