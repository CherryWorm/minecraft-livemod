#!/usr/bin/env python3
"""The M3 exit test: records survive a restart, modules hot-swap, and an in-game crash holds players.

Usage: python3 -m broker.tests.m3_test
"""
import os
import pathlib
import re
import subprocess
import sys
import time

from broker import runtime


def report(name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    return passed


def test_touched_blocks_survive_restart():
    """Changes a block, restarts, then reads the raw chunk data for the record."""
    sys.path.insert(0, str(runtime.REPO / "broker" / "gates"))
    from world_diff import read_chunks, touched_blocks

    runtime.rcon("prod", "forceload", "add", "96", "96")
    runtime.rcon("prod", "setblock", "96", "100", "96", "minecraft:gold_block")
    runtime.rcon("prod", "setblock", "97", "100", "96", "minecraft:gold_block")
    runtime.run(["./scripts/stack.sh", "restart", "prod"], timeout=180)
    runtime.wait_ready("prod")
    runtime.rcon("prod", "save-all", "flush")
    time.sleep(3)
    regions = next(path for path in sorted((runtime.RUNTIME / "prod" / "world").rglob("region")))
    count = 0
    for path in regions.glob("*.mca"):
        for x, z, chunk in read_chunks(path):
            if (x, z) == (6, 6):
                count = touched_blocks(chunk)
    runtime.rcon("prod", "setblock", "96", "100", "96", "minecraft:air")
    runtime.rcon("prod", "setblock", "97", "100", "96", "minecraft:air")
    runtime.rcon("prod", "forceload", "remove", "96", "96")
    return report("changed blocks are still recorded after a restart", count >= 2, f"touched={count}")


def test_module_hot_swap():
    """Replaces a running server module's jar and checks it swaps without a restart."""
    modules = runtime.RUNTIME / "prod" / "modules" / "server"
    jar = modules / "ember.jar"
    if not jar.exists():
        return report("server module hot-swaps", False, "no ember module on prod: run the M2 test first")
    before = runtime.inspect_state("prod")
    mark = runtime.utc_now()
    original = jar.read_bytes()
    # Adding bytes after the end of a zip leaves it readable but makes it a different file.
    jar.write_bytes(original + b"\0")
    reply = runtime.rcon("prod", "conduit", "modules", "reload")
    logs = runtime.logs_since("prod", mark)
    jar.write_bytes(original)
    runtime.rcon("prod", "conduit", "modules", "reload")
    after = runtime.inspect_state("prod")
    swapped = "server module ember unloaded" in logs and "server module ember enabled" in logs
    same_run = before["StartedAt"] == after["StartedAt"]
    return report("server module hot-swaps with no restart", swapped and same_run, reply[:90])


def test_crash_holds_players():
    """Crashes the server from inside its tick loop, with a client connected through the proxy."""
    marker = runtime.RUNTIME / "prod" / "config" / "conduit" / "chaos_crash_after_ticks"
    log = runtime.BROKER / "m3_bot.log"
    time.sleep(4)
    marker.write_text("400\n", encoding="utf-8")
    runtime.run(["./scripts/stack.sh", "restart", "prod"], timeout=180)
    runtime.wait_ready("prod")
    # The marker has done its job once the server has read it, so the restart after the crash is clean.
    marker.unlink()
    with log.open("w", encoding="utf-8") as stream:
        bot = subprocess.Popen([sys.executable, "-u", "scripts/smoketest_join.py", "--name", "crashbot", "--stay", "120"],
                               cwd=runtime.REPO, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and "JOINED" not in log.read_text(encoding="utf-8"):
            time.sleep(0.5)
        first_start = runtime.inspect_state("prod")["StartedAt"]
        deadline = time.monotonic() + 120
        rejoined = False
        while time.monotonic() < deadline:
            if bot.poll() is not None:
                break
            if log.read_text(encoding="utf-8").count("JOINED") >= 2:
                rejoined = True
                break
            time.sleep(1)
        crashed = runtime.inspect_state("prod")["StartedAt"] != first_start or rejoined
        tail = log.read_text(encoding="utf-8")[-160:].replace("\n", " ")
        return report("an in-game crash holds the player", rejoined and bot.poll() is None and crashed,
                      f"crashed={crashed} rejoined={rejoined} still_connected={bot.poll() is None} log: {tail}")
    finally:
        if bot.poll() is None:
            bot.kill()
        if marker.exists():
            marker.unlink()
        runtime.wait_ready("prod")


def main():
    results = [test_touched_blocks_survive_restart(), test_module_hot_swap(), test_crash_holds_players()]
    print("M3 PASS" if all(results) else "M3 FAIL", flush=True)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
