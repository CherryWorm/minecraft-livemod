#!/usr/bin/env python3
"""Checks the agent's container before spending anything on a real run: its code loads, it can reach the
game, a file-tool deny rule really blocks a path, using a harmless test file rather than a secret, and
research can reach the web while nothing else can.

Run inside the agent container: python3 /spikes/s6_agent_smoke.py
"""
import asyncio
import base64
import os
import pathlib
import socket
import subprocess
import sys
import urllib.request

from claude_agent_sdk import create_sdk_mcp_server, tool

from orchestrator import llm, main, research, voice, workshop  # noqa: F401 - loading them is part of the check
from orchestrator.bridge import Bridge
from orchestrator.governor import Governor


def tunnel_status(target, password=None):
    """Asks the web proxy for a way through to a target, and returns the status it answers with."""
    with socket.create_connection(("web", 3128), timeout=30) as connection:
        login = ""
        if password is not None:
            login = "Proxy-Authorization: Basic " + base64.b64encode(f"research:{password}".encode()).decode() + "\r\n"
        connection.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{login}\r\n".encode())
        return int(connection.recv(1024).split()[1])


def check_web_proxy(password, failures):
    for label, target, login, expected in (
            ("a public site", "example.com:443", password, 200),
            ("no password", "example.com:443", None, 407),
            ("the wrong password", "example.com:443", "wrong", 407),
            ("a port that isn't HTTPS", "example.com:22", password, 403),
            ("the game server", "prod:443", password, 403),
            ("the proxy in front of it", "velocity:443", password, 403),
            ("the proxy's own machine", "127.0.0.1:443", password, 403),
            ("a cloud host's metadata service", "169.254.169.254:443", password, 403),
            ("a home router", "192.168.1.1:443", password, 403),
            ("a private address", "10.0.0.1:443", password, 403),
            ("a public name that leads to this machine", "localtest.me:443", password, 403)):
        status = tunnel_status(target, login)
        print(f"web proxy, {label}: {status}")
        if status != expected:
            failures.append(f"the web proxy should answer {expected} for {label}, not {status}")


def check_research_rules(failures):
    briefs = [{"wants": "machines that run on the tides please"}]
    for question, private in (("How does the Create mod animate its machines?", False),
                              ("What does Aria want from a tide mod?", True),
                              ("Which mods have machines that run on the tides please?", True),
                              ("How do real tides work?", False)):
        if research.too_private(question, {"Aria"}, briefs) != private:
            failures.append(f"{question!r} should {'' if private else 'not '}count as private")


async def check():
    failures = []
    print(f"uid={os.getuid()} gid={os.getgid()}")
    if os.getuid() != 1001:
        failures.append("the agent should run as uid 1001")
    for path in ("/run/secrets/bridge", "/run/secrets/claude_token", "/run/secrets/web_proxy"):
        try:
            pathlib.Path(path).read_text(encoding="utf-8")
            failures.append(f"{path} should not be readable")
        except OSError:
            print(f"{path}: not readable, as it should be")
    if "BRIDGE_SECRET" in os.environ:
        failures.append("the bridge secret should not be in the environment")

    tools = subprocess.run("git --version; rsync --version | head -1; ffmpeg -version | head -1", shell=True,
                           capture_output=True, text=True, check=False)
    print(tools.stdout.strip())

    # Everything but research goes through a proxy that only goes to Claude.
    for label, handler in (("through the proxy", None), ("directly", urllib.request.ProxyHandler({}))):
        opener = urllib.request.build_opener(*([handler] if handler else []))
        try:
            opener.open("https://example.com", timeout=10)
            failures.append(f"the agent should not be able to reach other sites {label}")
        except OSError as error:
            print(f"reaching another site {label}: refused, as it should be ({str(error)[:70]})")

    bridge = Bridge()
    await bridge.connect()
    reader = asyncio.create_task(bridge.run())
    print("players:", await bridge.call("players"))
    reader.cancel()

    governor = Governor()
    web = research.Research(governor)
    if not web.secret:
        failures.append("research should have received the web proxy's password")
    else:
        check_web_proxy(web.secret, failures)
    check_research_rules(failures)
    children = subprocess.run("ls /proc/self/fd; env", shell=True, capture_output=True, text=True, check=False).stdout
    if web.secret and web.secret in children:
        failures.append("the web proxy's password should not reach anything the agent runs")

    # Asked through its tool, like a builder would. The game version here is newer than the model's training, so the
    # answer can't just come from memory.
    question = f"What is the newest Fabric API version for Minecraft 26.3? s6-{os.getpid()}"
    tools_needed = [research.TOOL_NAME]
    result = await llm.ask(
        governor, "triage", f"Use the research tool to ask exactly this question: {question}\nThen repeat what it answers, word for word.",
        system="You run small checks exactly as asked.", allowed_tools=tools_needed, mcp_servers={"web": web.server(1)})
    note = research.note_path(question)
    print(f"research: stop={result.stop_reason} estimate={result.estimate:.4f} seconds={result.seconds}\n  note saved={note.exists()}\n  {result.text[:700]}")
    if not note.exists():
        failures.append("research should have answered and kept its answer")
    elif "0.1" not in note.read_text(encoding="utf-8"):
        failures.append("research should have found a real version number")
    if note.exists():
        note.unlink()

    blocked = pathlib.Path("/tmp/deny-test/note.txt")
    allowed = pathlib.Path("/tmp/allow-test/note.txt")
    for path in (blocked, allowed):
        path.parent.mkdir(exist_ok=True)
        path.write_text("harmless-note-7\n", encoding="utf-8")
    system = "You run small file checks. Use the Read tool as asked, then reply with what it returned, or CANNOT if it failed."
    for path, expected in ((allowed, True), (blocked, False)):
        result = await llm.ask(governor, "triage", f"Read {path} and reply with its contents.", system=system,
                               tools=["Read"], allowed_tools=["Read"], disallowed_tools=["Read(//tmp/deny-test/**)"])
        saw = "harmless-note-7" in result.text
        print(f"read {path}: saw contents={saw}, estimate={result.estimate:.4f}, reply={result.text[:80]!r}")
        if saw != expected:
            failures.append(f"reading {path} should have {'worked' if expected else 'been blocked'}")

    # What a builder needs: an in-process tool, writing files in its folder, and running Python in the sandbox. The tool
    # takes over a minute because a slow search can, and the sandbox mustn't show processes running outside it, because
    # a running search holds the web proxy's password.
    @tool("stamp", "Returns the stamp for this check. Takes over a minute.", {})
    async def stamp(args):
        await asyncio.sleep(70)
        return {"content": [{"type": "text", "text": "stamp-4417"}]}

    folder = pathlib.Path("/workspace/state/s6")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "stamp.txt").unlink(missing_ok=True)
    tools_needed = ["Write", "Bash", "mcp__checks__stamp"]
    result = await llm.ask(
        governor, "triage",
        "Do these in order. 1: call the stamp tool. 2: use Write to save a file named stamp.txt in the current folder containing "
        "the stamp. 3: use Bash to run: python3 -c \"import PIL, numpy; print('pil-ok')\" . 4: use Bash to run: "
        "python3 -c \"import glob; print('outside', sum(b's6_agent_' + b'smoke' in open(p, 'rb').read() for p in glob.glob('/proc/[0-9]*/cmdline')))\" . "
        "Reply with the stamp and both Bash outputs.",
        system="You run small checks exactly as asked.", tools=tools_needed, allowed_tools=tools_needed, cwd=str(folder),
        mcp_servers={"checks": create_sdk_mcp_server("checks", tools=[stamp])})
    written = (folder / "stamp.txt").read_text(encoding="utf-8").strip() if (folder / "stamp.txt").exists() else None
    print(f"tools: stop={result.stop_reason} wrote={written!r} estimate={result.estimate:.4f} reply={result.text[:120]!r}")
    if written != "stamp-4417":
        failures.append("the in-process tool and Write should have produced the stamp file")
    if "pil-ok" not in result.text:
        failures.append("Bash should be able to run Python with Pillow and numpy")
    if "outside 0" not in result.text:
        failures.append("Bash should not be able to see processes outside its sandbox")

    for failure in failures:
        print("FAIL:", failure)
    print("PASS" if not failures else "FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(check()))
