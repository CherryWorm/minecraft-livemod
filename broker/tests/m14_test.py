#!/usr/bin/env python3
"""The start of a world, as a player meets it: the small, safe, clearly walled opening, then a private talk with the
agent over /dm that carries on when the player or the agent comes back, then the world opening up. Uses the real agent
and the real interviewer, at a cost of about 0.2 usage units. Start with a blank world from reset-dev-world.sh.

Usage: python3 -m broker.tests.m14_test
"""
import json
import os
import pathlib
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib

from broker import runtime
from broker.tests.m8_test import CONTAINER

sys.path.insert(0, str(runtime.REPO / "scripts"))
import playtest_bot as bot  # noqa: E402
import smoketest_join as client  # noqa: E402

HOST, PORT = "127.0.0.1", 25565
OPENING = 128
CAMERA_ABOVE_GROUND = 14
MINING_TICKS = 60
GO_AHEAD_WAIT_SECONDS = 35
OUT = runtime.REPORTS / "m14"
STATE = runtime.RUNTIME / "agent-workspace" / "state"
results = []


def report(name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {str(detail)[:300]}", flush=True)
    results.append(bool(passed))
    return passed


class Player:
    """Stays connected on a thread of its own, keeping everything it hears for the test to read."""

    def __init__(self, name):
        self.name = name
        self.heard = []
        self.raw = bytearray()
        self.joined = threading.Event()
        self.conn = client.Connection(HOST, PORT)
        client.login(self.conn, HOST, PORT, name)
        client.configure(self.conn, require_pack=False)
        self.running = True
        threading.Thread(target=self._read, daemon=True).start()
        if not self.joined.wait(40):
            raise TimeoutError(f"{name} never reached the world")

    def _read(self):
        conn = self.conn
        conn.sock.settimeout(1)
        while self.running:
            try:
                packet_id, data = conn.receive()
            except TimeoutError:
                continue
            except (client.Failed, OSError, zlib.error, socket.timeout):
                return
            self.raw += data.data
            if packet_id == client.PLAY_LOGIN:
                conn.send(client.TO_PLAY_LOADED)
                self.joined.set()
            elif packet_id == bot.PLAY_SYSTEM_CHAT:
                self.heard.append(bot.flatten(bot.read_nbt(data)))
            elif packet_id == client.PLAY_KEEP_ALIVE:
                conn.send(client.TO_PLAY_KEEP_ALIVE, data.rest())
            elif packet_id == client.PLAY_PING:
                conn.send(client.TO_PLAY_PONG, data.rest())
            elif packet_id == client.PLAY_PACK_PUSH:
                client.accept_pack(conn, data, client.TO_PLAY_PACK_STATUS)

    def dm(self, text):
        self.conn.send(bot.TO_PLAY_COMMAND, client.string(f"dm {text}"))

    def say(self, text):
        payload = client.string(text) + struct.pack(">qq", int(time.time() * 1000), 1) + b"\x00" + bot.varint(0) + bytes(3) + b"\x00"
        self.conn.send(bot.TO_PLAY_CHAT, payload)

    def wait_for(self, pattern, seconds=60, since=0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for line in self.heard[since:]:
                if re.search(pattern, line):
                    return line
            time.sleep(0.25)
        return None

    def leave(self):
        self.running = False
        self.conn.sock.close()
        time.sleep(5)  # The proxy turns away a second login from one address within 3 seconds.


def rcon(*command):
    return runtime.rcon("prod", *command, check=False)


def restart_prod(env):
    runtime.stack("up", "-d", "--force-recreate", "--no-deps", "prod", env=env)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if "players online" in rcon("list"):
            return
        time.sleep(3)
    raise TimeoutError("prod didn't start")


def agent_up():
    runtime.run(["./scripts/agent-up.sh", "--no-build"], timeout=300)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if "agent running" in runtime.run(["docker", "logs", "livingmod-agent-1"], check=False).stdout:
            return
        time.sleep(2)
    raise TimeoutError("the agent didn't start")


def interviewer_calls():
    path = STATE / "llm.jsonl"
    return sum('"role": "interviewer"' in line for line in path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def number(text):
    found = re.search(r"-?\d+(\.\d+)?", text.rsplit(":", 1)[-1])
    return float(found.group()) if found else None


def food_after_hunger(name):
    rcon("effect", "give", name, "minecraft:hunger", "6", "250")
    time.sleep(7)
    return number(rcon("data", "get", "entity", name, "foodLevel"))


def zombie_stays(name):
    rcon("execute", "at", name, "run", "summon", "minecraft:zombie", "~3", "~", "~")
    time.sleep(4)
    answer = rcon("execute", "if", "entity", "@e[type=minecraft:zombie]")
    rcon("kill", "@e[type=minecraft:zombie]")
    return answer


class RealClient:
    ground = 64

    """A real game client that does as it's told, for what only a real one can show."""

    def __init__(self):
        self.log = runtime.REPORTS / "m14-client.log"
        runtime.REPORTS.mkdir(parents=True, exist_ok=True)
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
        with self.log.open("w", encoding="utf-8") as stream:
            self.process = subprocess.Popen(
                ["./scripts/stack.sh", "--profile", "tools", "run", "--rm", "-T", "--name", CONTAINER, "testclient",
                 "./gradlew", "--no-daemon", "--console=plain", ":companion:runClientGameTest"],
                cwd=runtime.REPO, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                env={**os.environ, "CLIENT_TEST": "scene", "TEST_SERVER": "localhost:25565"},
            )
        self.wait(r"\[SCENE\] joined", 420)
        time.sleep(6)

    def wait(self, pattern, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            text = self.log.read_text(encoding="utf-8", errors="replace")
            found = re.search(pattern, text)
            if found:
                return found
            if self.process.poll() is not None or re.search(r"BUILD FAILED|Game crashed|\.java:\d+: error:", text):
                raise RuntimeError(f"The client stopped waiting for {pattern}:\n{text[-1500:]}")
            time.sleep(0.25)
        raise TimeoutError(f"Timed out waiting for {pattern}")

    def tell(self, text):
        rcon("tellraw", "Player0", json.dumps({"text": f"SCENE {text}"}))

    def place(self, x, y, z, yaw=0, pitch=15):
        rcon("execute", "in", "minecraft:overworld", "run", "tp", "Player0", str(x), str(y), str(z), str(yaw), str(pitch))

    def shot(self, name, x, z, yaw, when="noon"):
        rcon("time", "set", when)
        # About where a player would see it from, a little above the trees.
        self.place(x, self.ground + CAMERA_ABOVE_GROUND, z, yaw)
        self.tell(f"shot {name}")
        self.wait(rf"\[SCENE\] took {name}", 90)

    def block_survives_mining(self, spawn):
        """Stands on a block in mid-air, looks straight down and really holds the attack key, as a player would."""
        x, y, z = spawn[0] + 3, 200, spawn[1] + 3
        rcon("gamemode", "spectator", "Player0")
        self.place(x + 0.5, y + 1, z + 0.5, 0, 90)
        time.sleep(4)
        rcon("setblock", str(x), str(y), str(z), "minecraft:dirt")
        rcon("gamemode", "survival", "Player0")
        time.sleep(2)
        self.tell(f"mine {MINING_TICKS}")
        self.wait(r"\[SCENE\] mined", 60)
        time.sleep(1)
        return "passed" in rcon("execute", "if", "block", str(x), str(y), str(z), "minecraft:dirt").lower()

    def finish(self):
        self.tell("done")
        try:
            self.process.wait(timeout=90)
        finally:
            if self.process.poll() is None:
                subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
                self.process.wait(timeout=30)


def film_the_wall(spawn):
    """A real client's view of the wall: from spawn, from close to it, and at night. Then it tries to break something."""
    camera = RealClient()
    try:
        rcon("gamemode", "spectator", "Player0")
        x, z = spawn
        half = OPENING // 2
        camera.shot("wall_from_spawn", x, z, 0)
        camera.tell("entities")
        print(camera.wait(r"\[SCENE\] entities.*", 30).group(0)[:600], flush=True)
        camera.shot("wall_from_spawn_other_way", x, z, 90)
        camera.shot("wall_up_close", x, z + half - 12, 0)
        camera.shot("wall_along_it", x - half + 6, z + half - 8, -60)
        camera.shot("wall_at_night", x, z, 0, "midnight")
        report("a real player can't break anything during the opening", camera.block_survives_mining(spawn))
    finally:
        camera.finish()
    shots = runtime.REPO / "mods" / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    OUT.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*scene_wall_*.png"):
        shutil.copy(path, OUT)
    report("a real client filmed the wall", len(list(OUT.glob("*wall_*.png"))) >= 5, sorted(path.name for path in OUT.glob("*.png")))
    time.sleep(6)


def test_opening_with_no_agent():
    report("the world is peaceful from its first boot, with no agent running", "Peaceful" in rcon("difficulty") or "peaceful" in rcon("difficulty"), rcon("difficulty"))
    report("and the border is small", number(rcon("worldborder", "get").replace("block(s) wide", "")) == OPENING or f"{OPENING} block" in rcon("worldborder", "get"), rcon("worldborder", "get"))
    logs = runtime.run(["docker", "logs", runtime.container("prod")], check=False).stdout
    found = re.search(r"a border \d+ wide around (-?\d+) (-?\d+)", logs)
    report("around spawn", found is not None, found.group(0) if found else "")
    spawn = (int(found.group(1)), int(found.group(2))) if found else (0, 0)

    dana = Player("Dana")
    before = len(dana.heard)
    dana.dm("is anyone there?")
    report("/dm says so when nobody's listening", dana.wait_for("isn't listening", 10, before), dana.heard[before:])
    report("no hunger", food_after_hunger("Dana") == 20, rcon("data", "get", "entity", "Dana", "foodLevel"))
    report("no hostile mobs", "failed" in zombie_stays("Dana").lower())

    rcon("tp", "Dana", str(spawn[0] + 900), "100", str(spawn[1]))
    time.sleep(1)
    dana.leave()
    dana = Player("Dana")
    position = rcon("data", "get", "entity", "Dana", "Pos")
    x, y = [float(value) for value in re.search(r"\[(-?[\d.]+)d, (-?[\d.]+)d", position).groups()]
    report("someone who's outside when they join is brought back in, not hurt", abs(x - spawn[0]) < OPENING / 2 and dana.wait_for("brought back", 10), position)
    report("and they land on the ground, not at the bottom of the world", y > 0, position)
    RealClient.ground = int(y)
    dana.leave()
    return spawn


def test_interview():
    agent_up()
    dana = Player("Dana")
    first = dana.wait_for(r"\[Agent\]", 90)
    report("the first thing a new player hears is the agent asking something", first, first)
    report("with how to answer it", dana.wait_for(r"/dm.*a space.*/dm I love exploring", 20), dana.heard)
    report("and what the opening is", dana.wait_for(r"64 blocks from spawn.*glowing wall.*no monsters and no hunger", 20))

    time.sleep(5)  # The proxy turns away a second login from one address within 3 seconds.
    eli = Player("Eli")
    report("a second player gets their own", eli.wait_for(r"\[Agent\]", 90))

    start = len(dana.heard)
    dana.say("hello everyone")
    dana.say("anyone around?")
    report("public chat in an interview gets a pointer to /dm", dana.wait_for("That went to everyone", 15, start))
    time.sleep(3)
    report("only once", sum("That went to everyone" in line for line in dana.heard[start:]) == 1)

    start = len(dana.heard)
    dana.dm("My favourite mod is Zorblatt, because of the gears.")
    report("/dm shows you what you sent", dana.wait_for("You to the agent: .*Zorblatt", 10, start))
    answer = dana.wait_for(r"\[Agent\]", 90, start)
    report("and the agent answers", answer, answer)
    time.sleep(2)
    report("nobody else sees any of it", b"Zorblatt" not in bytes(eli.raw))

    last = [line for line in dana.heard if "[Agent]" in line][-1]
    calls = interviewer_calls()
    dana.leave()
    dana = Player("Dana")
    report("coming back says so", dana.wait_for("Welcome back", 20), dana.heard)
    report("repeats where things had got to", dana.wait_for(re.escape(last), 10), last)
    report("and how to answer", dana.wait_for(r"/dm.*a space", 10))
    report("without using a model", interviewer_calls() == calls, f"{calls} calls before and {interviewer_calls()} after")

    # The agent's own memory is gone after this, so only what it saved can carry the talk on.
    start = len(dana.heard)
    runtime.run(["./scripts/agent-up.sh", "--no-build"], timeout=300)
    report("after the agent restarts, it picks up where it was", dana.wait_for("Welcome back", 90, start), dana.heard[start:])
    start = len(dana.heard)
    dana.dm("Before we go on: which mod did I say was my favourite? Please name it in your reply.")
    answer = dana.wait_for(r"\[Agent\]", 90, start)
    report("and it remembers what was said", answer and "zorblatt" in answer.lower(), answer)

    for attempt in range(6):
        start = len(dana.heard)
        dana.dm("That's everything, thanks. I'd like to get on with playing now, so please finish up.")
        if dana.wait_for("That's all I needed", 90, start):
            break
    report("the talk can end", (STATE / "briefs" / "Dana.json").exists(), attempt)
    state = json.loads((STATE / "opening.json").read_text(encoding="utf-8"))
    report("and nothing of it is left waiting", "Dana" not in state["interviews"] and "Eli" in state["interviews"], list(state["interviews"]))

    # A named player has finished, and nothing should come of it: only the owner's go-ahead starts anything.
    roster = runtime.RUNTIME / "control" / "roster.txt"
    roster.write_text("Dana\n", encoding="utf-8")
    time.sleep(GO_AHEAD_WAIT_SECONDS)
    roster.unlink()
    log = (STATE / "llm.jsonl").read_text(encoding="utf-8")
    state = json.loads((STATE / "opening.json").read_text(encoding="utf-8"))
    report("without the go-ahead, it doesn't choose a theme", '"role": "direction"' not in log and not state["direction_chosen"])

    start = len(dana.heard)
    dana.dm("Could the caves have more crystals in them?")
    report("/dm is still a private line afterwards", dana.wait_for("I've got that", 60, start), dana.heard[start:])
    time.sleep(2)
    report("that's private too", b"crystals" not in bytes(eli.raw))
    dana.leave()
    start = len(eli.heard)
    return eli, start


def test_opening_ends(eli, spawn):
    # The agent ends the opening after its first release. Saying one happened avoids spending a builder on it, and also
    # exercises what happens if the first try fails, because this is the retry that picks it up.
    runtime.run(["docker", "exec", "livingmod-agent-1", "python3", "-c",
                 "import json, pathlib; p = pathlib.Path('/workspace/state/opening.json'); s = json.loads(p.read_text()); s['release_count'] = 1; p.write_text(json.dumps(s))"])
    rcon("time", "set", "midnight")
    start = len(eli.heard)
    runtime.run(["./scripts/agent-up.sh", "--no-build"], timeout=300)
    report("the agent ends the opening after a release, and everyone's told", eli.wait_for("The world has opened", 90, start), eli.heard[start:])
    report("the border is gone", "59999968" in rcon("worldborder", "get"), rcon("worldborder", "get"))
    report("the difficulty is the real one", "ormal" in rcon("difficulty"), rcon("difficulty"))
    daytime = number(rcon("time", "query", "day"))
    report("it's morning", daytime is not None and 1000 <= daytime < 1600, daytime)
    report("hunger is back", food_after_hunger("Eli") < 20, rcon("data", "get", "entity", "Eli", "foodLevel"))
    report("so are monsters", "passed" in zombie_stays("Eli").lower())
    eli.leave()

    restart_prod({"OPENING_BORDER": str(OPENING)})
    report("and it stays that way after a restart", "ormal" in rcon("difficulty") and "59999968" in rcon("worldborder", "get"), rcon("difficulty"))
    logs = runtime.run(["docker", "logs", runtime.container("prod")], check=False).stdout
    report("with no second opening", "the opening is on" not in logs)
    report("the owner can end it by hand too, and doing it twice is harmless", "wasn't in its opening" in rcon("conduit", "open"))

    runtime.run(["./scripts/agent-down.sh"], check=False)
    camera = RealClient()
    try:
        report("a real player can break things now", not camera.block_survives_mining(spawn))
    finally:
        camera.finish()


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    env = {"OPENING_BORDER": str(OPENING)}
    os.environ.update(env)
    restart_prod(env)
    spawn = test_opening_with_no_agent()
    film_the_wall(spawn)
    if "--wall-only" in sys.argv:
        return
    eli, _ = test_interview()
    test_opening_ends(eli, spawn)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    runtime.run(["./scripts/agent-down.sh"], check=False)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
