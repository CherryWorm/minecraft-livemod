#!/usr/bin/env python3
"""Asks the game what the agent's bug investigator would see of a player, for m24_test. Runs in the agent's container, which is the only thing that holds the bridge's secret."""
import asyncio
import json
import sys

from orchestrator.bridge import Bridge


async def main():
    bridge = Bridge()
    await bridge.connect()
    reader = asyncio.create_task(bridge.run())
    for player in sys.argv[1:]:
        try:
            print(json.dumps({"asked": player, "found": await bridge.call("inspect_player", player=player)}), flush=True)
        except RuntimeError as error:
            print(json.dumps({"asked": player, "error": str(error)}), flush=True)
    reader.cancel()


asyncio.run(main())
