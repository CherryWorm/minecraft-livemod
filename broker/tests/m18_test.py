#!/usr/bin/env python3
"""The build board on a real client: nothing until someone turns it on, then what the agent says, keeping up as that
changes, saying so when the agent's gone, still on after a restart, and only ever sent to whoever asked for it.
Start with a world from reset-dev-world.sh and a baseline release.

Usage: python3 -m broker.tests.m18_test
"""
import json
import re
import shutil
import subprocess
import sys
import time

from broker import runtime
from broker.tests.m8_test import Client, PLAYER
from broker.tests.m14_test import Player, bot, client as bot_client, report, results

OBJECTIVE = b"gm_board"
AWAY_SECONDS = 95
FIRST = {"shipped": 7, "building": 2, "queued": 5, "now": [{"text": "a quicker way to climb", "tag": "early"}, {"text": "a minimap", "tag": "small"}]}
SECOND = {"shipped": 8, "building": 1, "queued": 5, "now": [{"text": "a tough new foe for late game", "tag": "late"}]}


def push(shown):
    result = subprocess.run(["./scripts/stack.sh", "--profile", "agent", "run", "--rm", "-T", "--no-deps", "agent", "python3", "/spikes/board_push.py", json.dumps(shown)],
                            cwd=runtime.REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    if "True" not in result.stdout:
        raise RuntimeError(f"Couldn't update the board:\n{result.stdout[-800:]}\n{result.stderr[-800:]}")


def sidebar(player):
    player.ask("sidebar")
    return re.findall(r"\[M8\] sidebar: (.*)$", player.text(), re.MULTILINE)[-1]


def back_online(seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        listed = runtime.rcon("prod", "list", check=False)
        if PLAYER in str(listed):
            return True
        time.sleep(1)
    return False


def main():
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    mods = runtime.WORK / "mods"
    player = Client(mods, runtime.REPORTS / "m18-client.log")
    other = None
    try:
        player.wait(r"\[M8\] joined as [A-Za-z0-9_]+$", 420)
        time.sleep(5)
        other = Player("Dana")

        report("nobody has a board until they ask for one", sidebar(player) == "none")

        player.ask("command board")
        player.wait(r"\[M8\] chat: .*The build board is on", 20)
        shown = sidebar(player)
        report("turning it on shows the board", shown.startswith("Build Progress"), shown)
        report("and until it hears from the agent it says so", "The agent is away" in shown, shown)

        push(FIRST)
        shown = sidebar(player)
        for text in ("Shipped = 7", "In the works = 2", "In the queue = 5", "a quicker way to climb = early", "a minimap = small"):
            report(f"it shows '{text}'", text in shown, shown)
        report("in the right order", shown.index("Shipped") < shown.index("In the works") < shown.index("In the queue") < shown.index("Being built now") < shown.index("a quicker"), shown)
        player.ask("shot board")

        push(SECOND)
        shown = sidebar(player)
        report("it keeps up", "Shipped = 8" in shown and "In the works = 1" in shown and "a tough new foe for late game = late" in shown, shown)
        report("and what's finished goes away", "a minimap" not in shown and "quicker" not in shown, shown)

        time.sleep(3)
        report("someone who didn't ask gets none of it", OBJECTIVE not in bytes(other.raw))
        third = Player("Finn")
        time.sleep(2)

        # The game's own stop skips every other player, and the proxy can't hold anyone who isn't told it's a restart.
        print("restarting the server with three players on, which should hold them all", flush=True)
        mark = runtime.utc_now()
        runtime.stack("restart", "prod", timeout=180)
        told = runtime.run(["docker", "logs", "--since", mark, "livingmod-velocity-1"]).stdout
        report("everyone is told it's a restart", told.count("kicked from server backend: multiplayer.disconnect.server_shutdown") == 3, told[-500:])
        report("and nobody just loses the connection", "internal server connection error" not in told, told[-500:])
        for bot_player in (other, third):
            bot_player.running = False
            bot_player.conn.sock.close()
        time.sleep(5)
        report("the player comes back after a restart", back_online())
        time.sleep(8)
        shown = sidebar(player)
        report("with the board still on", shown.startswith("Build Progress"), shown)
        push(FIRST)
        shown = sidebar(player)
        report("and still working", "Shipped = 7" in shown and "a minimap = small" in shown, shown)

        print(f"waiting {AWAY_SECONDS}s for the board to notice nobody's updating it", flush=True)
        time.sleep(AWAY_SECONDS)
        shown = sidebar(player)
        report("if the agent stops, it says so", "The agent is away" in shown and "a minimap" not in shown, shown)
        report("and keeps the last numbers", "Shipped = 7" in shown, shown)

        player.ask("command board")
        player.wait(r"\[M8\] chat: .*The build board is off", 20)
        report("turning it off removes it", sidebar(player) == "none")

        # Only proves anything if the other player could have seen it.
        other = Player("Erin")
        other.conn.send(bot.TO_PLAY_COMMAND, bot_client.string("board"))
        time.sleep(3)
        report("the same check does see a board that's sent", OBJECTIVE in bytes(other.raw))
    finally:
        player.stop()

    shots = mods / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    out = runtime.REPORTS / "m18"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m8_board*.png"):
        shutil.copy(path, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
