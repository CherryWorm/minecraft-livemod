#!/usr/bin/env python3
"""Tells the game what the build board should show, the way the agent does, for broker/tests/m18_test.py.

Run inside the agent's container: python3 /spikes/board_push.py '{"shipped": 1, "building": 0, "queued": 0, "now": []}'
"""
import asyncio
import json
import sys

from orchestrator.bridge import Bridge


async def run():
    bridge = Bridge()
    await bridge.connect()
    reader = asyncio.create_task(bridge.run())
    print(await bridge.call("board", **json.loads(sys.argv[1])), flush=True)
    reader.cancel()


asyncio.run(run())
