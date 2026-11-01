#!/usr/bin/env python3
"""A real builder on another model asks for art, and real Opus makes it, for broker/tests/m21_test.py. Uses a little of the plan."""
import asyncio
import json
import pathlib
import shutil
import subprocess
import time

from claude_agent_sdk import create_sdk_mcp_server

from orchestrator import lanes, llm, workshop
from orchestrator.governor import Governor

TREE = pathlib.Path("/workspace/trees/demo")
FEATURE = "demo"


def git(*args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=TREE, check=True, capture_output=True)


async def run():
    folder = TREE / "mods/genesis/features" / FEATURE
    (folder / "assets").mkdir(parents=True)
    (TREE / "bible").mkdir()
    (TREE / "bible/theme.md").write_text("A warm world of embers and old stone.\n", encoding="utf-8")
    shutil.copytree("/x/assetkit", TREE / "assetkit", ignore=shutil.ignore_patterns("__pycache__"))
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "first")

    self_hosted = lanes.SelfHosted()
    server = asyncio.create_task(self_hosted.serve())
    await asyncio.sleep(1)
    llm.MOVED.update(dict.fromkeys(self_hosted.roles, self_hosted.lane))
    shop = workshop.Workshop(Governor(), None, None)
    began = time.monotonic()
    result = await shop._attempt(FEATURE, TREE, "Make the thing.", None, False, None, "e_one", "early", 20, 5.0, workshop.BUILDER_TOOLS, create_sdk_mcp_server("web", tools=[]))
    seconds = round(time.monotonic() - began, 1)
    server.cancel()
    art = workshop._art_in(folder)
    calls = [json.loads(line) for line in llm.TIMELINE.read_text(encoding="utf-8").splitlines()]
    out = {"text": result.text, "is_error": result.is_error, "stop": result.stop_reason, "seconds": seconds, "art": sorted(art), "calls": calls,
           "made": sorted(shop.art_made.get(FEATURE, {})), "left": sorted(set(art) - set(shop.art_made.get(FEATURE, {})))}
    pathlib.Path("/workspace/art-out.json").write_text(json.dumps(out), encoding="utf-8")


asyncio.run(run())
