#!/usr/bin/env python3
"""The password test: nobody gets anything from the game or the website without the one password, and with it a real
client gets in. Runs on a local stack, because its bots and its test client need a proxy with login checks off, so it
turns the gate on by itself and turns it off again when it finishes.

Usage: python3 -m broker.tests.m13_test
"""
import base64
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from broker import runtime

sys.path.insert(0, str(runtime.REPO / "scripts"))
import password_hash  # noqa: E402
import smoketest_join as client  # noqa: E402
from ping import varint  # noqa: E402

HOST, PORT = "127.0.0.1", 25565
SITE = "http://127.0.0.1:8080"
PASSWORD = "m13-the-right-one"
NEW_PASSWORD = "m13-a-new-one"
# From the server's own --reports packets.json. A new Minecraft version needs these regenerated.
CONFIG_SHOW_DIALOG, TO_CONFIG_CLICK = 19, 8
HASH_FILE = runtime.RUNTIME / "secrets" / "m13_game_password.secret"
APPROVED = runtime.RUNTIME / "prod" / "config" / "conduit" / "password_approved.txt"
CONTAINER = "livingmod-m13-client"
BETWEEN_LOGINS = 4  # The proxy turns away a second login from one address within 3 seconds.
results = []


def report(name, passed, detail=""):
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    results.append(bool(passed))


def click(password):
    field, value = b"password", password.encode()
    nbt = b"\x0a\x08" + len(field).to_bytes(2, "big") + field + len(value).to_bytes(2, "big") + value + b"\x00"
    return client.string("conduit:password_enter") + varint(len(nbt)) + nbt


class Visit:
    """One connection, played by hand so the test can see what arrives, and in what order."""

    def __init__(self, name, answers=()):
        self.answers = list(answers)
        self.dialogs = 0
        self.pack = False
        self.pack_before_dialog = False
        self.finished_config = False
        self.joined = False
        self.kicked = None
        self.conn = client.Connection(HOST, PORT)
        client.login(self.conn, HOST, PORT, name)

    def until_settled(self, seconds=15):
        """Runs until it's in the world or kicked, or there's nothing more to do than wait."""
        conn = self.conn
        conn.sock.settimeout(1)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.joined and self.kicked is None:
            try:
                packet_id, data = conn.receive()
            except TimeoutError:
                continue
            except (client.Failed, OSError) as error:
                self.kicked = str(error)
                break
            if self.finished_config:
                if packet_id == client.PLAY_LOGIN:
                    self.joined = True
                    conn.send(client.TO_PLAY_LOADED)
                elif packet_id == client.PLAY_DISCONNECT:
                    self.kicked = client.readable(data.rest())
                elif packet_id == client.PLAY_KEEP_ALIVE:
                    conn.send(client.TO_PLAY_KEEP_ALIVE, data.rest())
                elif packet_id == client.PLAY_PING:
                    conn.send(client.TO_PLAY_PONG, data.rest())
                continue
            if packet_id == CONFIG_SHOW_DIALOG:
                self.dialogs += 1
                self.pack_before_dialog = self.pack_before_dialog or self.pack
                if self.answers:
                    conn.send(TO_CONFIG_CLICK, click(self.answers.pop(0)))
            elif packet_id == client.CONFIG_DISCONNECT:
                self.kicked = client.readable(data.rest())
            elif packet_id == client.CONFIG_FINISH:
                conn.send(client.TO_CONFIG_FINISH)
                self.finished_config = True
            elif packet_id == client.CONFIG_KEEP_ALIVE:
                conn.send(client.TO_CONFIG_KEEP_ALIVE, data.rest())
            elif packet_id == client.CONFIG_PING:
                conn.send(client.TO_CONFIG_PONG, data.rest())
            elif packet_id == client.CONFIG_KNOWN_PACKS:
                conn.send(client.TO_CONFIG_KNOWN_PACKS, varint(0))
            elif packet_id == client.CONFIG_COOKIE:
                conn.send(client.TO_CONFIG_COOKIE, client.string(data.string()) + b"\x00")
            elif packet_id == client.CONFIG_PACK_PUSH:
                self.pack = True
                client.accept_pack(conn, data, client.TO_CONFIG_PACK_STATUS)
        return self

    def close(self):
        self.conn.sock.close()
        time.sleep(BETWEEN_LOGINS)


def visit(name, answers=(), seconds=15):
    time.sleep(BETWEEN_LOGINS)
    seen = Visit(name, answers).until_settled(seconds)
    seen.close()
    return seen


def online():
    answer = runtime.rcon("prod", "list", check=False)
    return re.sub(r".*online: ?", "", answer)


def fetch(path, password=None):
    request = urllib.request.Request(SITE + path)
    if password:
        request.add_header("Authorization", "Basic " + base64.b64encode(f"player:{password}".encode()).decode())
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def restart_prod(password_file):
    env = {"GAME_PASSWORD_FILE": str(password_file)} if password_file else {"GAME_PASSWORD_FILE": "/dev/null"}
    runtime.stack("up", "-d", "--force-recreate", "--no-deps", "prod", env=env)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if "players online" in runtime.rcon("prod", "list", check=False):
            return
        time.sleep(3)
    raise TimeoutError("prod didn't start")


def wait_log(log, process, pattern, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = log.read_text(encoding="utf-8", errors="replace")
        found = re.search(pattern, text, re.MULTILINE)
        if found:
            return found
        if re.search(r"BUILD FAILED|Game crashed|\.java:\d+: error:", text) or process.poll() is not None:
            raise RuntimeError(f"The client stopped waiting for {pattern}:\n{text[-1500:]}")
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {pattern}:\n{log.read_text(encoding='utf-8', errors='replace')[-800:]}")


def test_game():
    stranger = visit("M13Stranger", seconds=8)
    report("a stranger is asked for the password", stranger.dialogs == 1, f"{stranger.dialogs} dialog(s)")
    report("and gets no resource pack first", not stranger.pack)
    report("and never reaches the world", not stranger.joined and not stranger.finished_config)

    held = Visit("M13Waiting").until_settled(6)
    report("nobody's in the game while they're being asked", held.dialogs == 1 and "M13Waiting" not in online(), online())
    held.close()

    wrong = visit("M13Wrong", ["no", "still no", "not this either"])
    report("three wrong answers get you disconnected", wrong.kicked is not None and not wrong.joined, wrong.kicked or "")
    report("still with no resource pack", not wrong.pack)
    report("each wrong answer asks again", wrong.dialogs == 3, f"{wrong.dialogs} dialogs")

    right = Visit("M13Friend", [PASSWORD]).until_settled(40)
    report("the right password gets you in", right.joined, right.kicked or "")
    report("with the pack coming after the password", right.pack and not right.pack_before_dialog)
    report("and you're really in the game", "M13Friend" in online(), online())
    right.close()

    again = visit("M13Friend", seconds=40)
    report("you're only asked once", again.joined and again.dialogs == 0, f"{again.dialogs} dialogs")

    restart_prod(HASH_FILE)
    after_restart = visit("M13Friend", seconds=40)
    report("a server restart doesn't ask again", after_restart.joined and after_restart.dialogs == 0, f"{after_restart.dialogs} dialogs")
    someone_else = visit("M13Other", seconds=8)
    report("but it hasn't let anyone else in", someone_else.dialogs == 1 and not someone_else.joined)

    for attempt in range(3):
        visit("M13Guesser", ["a", "b", "c"])
    visit("M13Guesser", ["d"], seconds=6)
    locked = visit("M13Guesser", [PASSWORD], seconds=10)
    report("too many wrong answers lock an account out for a while, even with the right one", not locked.joined and locked.dialogs == 0, locked.kicked or "")
    report("and being locked out doesn't get it into the game", "M13Guesser" not in online(), online())

    # Written in place, the way scripts/set-password.sh does it, because the container has this exact file mounted.
    with HASH_FILE.open("w", encoding="utf-8") as stream:
        stream.write(password_hash.hash_password(NEW_PASSWORD))
    changed = visit("M13Friend", seconds=8)
    report("a new password needs no restart, and everyone's asked again", changed.dialogs == 1 and not changed.joined, f"{changed.dialogs} dialogs")
    old = visit("M13Friend2", [PASSWORD], seconds=8)
    report("the old password stops working", not old.joined and old.dialogs >= 1)
    new = visit("M13Friend", [NEW_PASSWORD], seconds=40)
    report("the new one works", new.joined, new.kicked or "")
    with HASH_FILE.open("w", encoding="utf-8") as stream:
        stream.write(password_hash.hash_password(PASSWORD))

    logs = runtime.run(["docker", "logs", runtime.container("prod")], check=False).stdout + runtime.run(["docker", "logs", runtime.container("velocity")], check=False).stdout
    report("no answer ever reaches a log", not any(word in logs for word in (PASSWORD, NEW_PASSWORD, "still no", "not this either")))
    report("only the hash is in the server", PASSWORD not in runtime.run(["docker", "exec", runtime.container("prod"), "cat", "/run/secrets/game_password"]).stdout)


def test_real_client():
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    log = runtime.REPORTS / "m13-client.log"
    APPROVED.unlink(missing_ok=True)
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            ["./scripts/stack.sh", "--profile", "tools", "run", "--rm", "-T", "--name", CONTAINER, "testclient",
             "./gradlew", "--no-daemon", "--console=plain", ":companion:runClientGameTest"],
            cwd=runtime.REPO, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            env={**os.environ, "CLIENT_TEST": "password", "TEST_SERVER": "localhost:25565", "LIVINGMOD_TEST_PASSWORD": PASSWORD},
        )
    try:
        found = wait_log(log, process, r"\[M13\] asked, in the world already: (\w+)", 420)
        report("a real client shows the password dialog, outside the world", found.group(1) == "false", found.group(0))
        wait_log(log, process, r"\[M13\] asked again after a wrong answer", 60)
        report("a wrong answer typed into it asks again", True)
        wait_log(log, process, r"\[M13\] joined", 180)
        report("the right answer typed into it joins the game", True)
        found = wait_log(log, process, r"\[M13\] second join asked: (\w+)", 180)
        report("and the next join doesn't ask", found.group(1) == "false", found.group(0))
        wait_log(log, process, r"\[M13\] finished", 120)
        process.wait(timeout=90)
    finally:
        if process.poll() is None:
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)
            process.wait(timeout=30)
    shots = runtime.REPO / "mods" / "companion" / "build" / "run" / "clientGameTest" / "screenshots"
    out = runtime.REPORTS / "m13"
    out.mkdir(parents=True, exist_ok=True)
    for path in shots.glob("*m13_*.png"):
        shutil.copy(path, out)
    print("screenshots:", sorted(path.name for path in out.glob("*.png")), flush=True)


def test_site():
    status, _ = fetch("/")
    report("the website wants a password", status == 401, str(status))
    status, _ = fetch("/LivingMod.zip")
    report("so does the download", status == 401, str(status))
    status, _ = fetch("/", "wrong")
    report("and a wrong one is refused", status == 401, str(status))
    site_password = (runtime.RUNTIME / "secrets" / "password.secret").read_text(encoding="utf-8").strip()
    status, body = fetch("/", site_password)
    report("the right one opens the page", status == 200 and b"Living Mod" in body, str(status))
    report("which fills in the address", b"{{" not in body and b"localhost" in body)
    zip_file = pathlib.Path(runtime.RUNTIME / "friend-pack" / "LivingMod.zip")
    if zip_file.exists():
        status, body = fetch("/LivingMod.zip", site_password)
        report("and the download", status == 200 and body[:2] == b"PK", f"{status}, {len(body)} bytes")
    status, _ = fetch("/pack/guess/anything", None)
    report("guessing at the pack's address gets the password prompt", status == 401, str(status))


def main():
    HASH_FILE.write_text(password_hash.hash_password(PASSWORD), encoding="utf-8")
    APPROVED.unlink(missing_ok=True)
    try:
        test_site()
        restart_prod(HASH_FILE)
        test_game()
        test_real_client()
    finally:
        restart_prod(None)
        HASH_FILE.unlink(missing_ok=True)
        APPROVED.unlink(missing_ok=True)
    failed = [result for result in results if not result]
    print(f"{len(results) - len(failed)} of {len(results)} checks passed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
