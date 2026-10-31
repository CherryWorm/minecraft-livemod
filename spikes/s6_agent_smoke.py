#!/usr/bin/env python3
"""Checks the agent's container before spending anything on a real run: its code loads, it can reach the
game, and a file-tool deny rule really blocks a path, using a harmless test file rather than a secret.

Run inside the agent container: python3 /spikes/s6_agent_smoke.py
"""
import asyncio
import os
import pathlib
import subprocess
import sys
import urllib.request

from claude_agent_sdk import create_sdk_mcp_server, tool

from orchestrator import llm, main, voice, workshop  # noqa: F401 - loading them is part of the check
from orchestrator.bridge import Bridge
from orchestrator.governor import Governor


async def check():
    failures = []
    print(f"uid={os.getuid()} gid={os.getgid()}")
    if os.getuid() != 1001:
        failures.append("the agent should run as uid 1001")
    for path in ("/run/secrets/bridge", "/run/secrets/claude_token"):
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

    # The agent's only way out is the proxy, and the proxy only goes to Claude.
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
    blocked = pathlib.Path("/tmp/deny-test/note.txt")
    allowed = pathlib.Path("/tmp/allow-test/note.txt")
    for path in (blocked, allowed):
        path.parent.mkdir(exist_ok=True)
        path.write_text("harmless-note-7\n", encoding="utf-8")
    system = "You run small file checks. Use the Read tool as asked, then reply with what it returned, or CANNOT if it failed."
    for path, expected in ((allowed, True), (blocked, False)):
        result = await llm.ask(governor, "triage", f"Read {path} and reply with its contents.", system=system,
                               tools=["Read"], allowed_tools=["Read"], disallowed_tools=["Read(//tmp/deny-test/**)"], max_turns=3)
        saw = "harmless-note-7" in result.text
        print(f"read {path}: saw contents={saw}, estimate={result.estimate:.4f}, reply={result.text[:80]!r}")
        if saw != expected:
            failures.append(f"reading {path} should have {'worked' if expected else 'been blocked'}")

    # What a builder needs: an in-process tool, writing files in its folder, and running Python in the sandbox.
    @tool("stamp", "Returns the stamp for this check.", {})
    async def stamp(args):
        return {"content": [{"type": "text", "text": "stamp-4417"}]}

    folder = pathlib.Path("/workspace/state/s6")
    folder.mkdir(parents=True, exist_ok=True)
    tools_needed = ["Write", "Bash", "mcp__checks__stamp"]
    result = await llm.ask(
        governor, "triage",
        "Do these in order. 1: call the stamp tool. 2: use Write to save a file named stamp.txt in the current folder containing "
        "the stamp. 3: use Bash to run: python3 -c \"import PIL, numpy; print('pil-ok')\" . Reply with the stamp and the Bash output.",
        system="You run small checks exactly as asked.", tools=tools_needed, allowed_tools=tools_needed, cwd=str(folder), max_turns=8,
        mcp_servers={"checks": create_sdk_mcp_server("checks", tools=[stamp])})
    written = (folder / "stamp.txt").read_text(encoding="utf-8").strip() if (folder / "stamp.txt").exists() else None
    print(f"tools: stop={result.stop_reason} wrote={written!r} estimate={result.estimate:.4f} reply={result.text[:120]!r}")
    if written != "stamp-4417":
        failures.append("the in-process tool and Write should have produced the stamp file")
    if "pil-ok" not in result.text:
        failures.append("Bash should be able to run Python with Pillow and numpy")

    for failure in failures:
        print("FAIL:", failure)
    print("PASS" if not failures else "FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(check()))
