#!/usr/bin/env python3
"""The agent's minds and nothing else, for broker/tests/m12_test.py: answers mob events the way the real agent does, and
also carries out requests from a file, so that the test can try what a model should never be allowed to do.

Run inside the agent's container: python3 /spikes/minds_loop.py
"""
import asyncio
import json
import pathlib

from orchestrator import minds
from orchestrator.bridge import Bridge
from orchestrator.governor import Governor

ASK = pathlib.Path("/workspace/m12/ask.json")
ANSWER = pathlib.Path("/workspace/m12/answer.json")
LAST_EVENT = pathlib.Path("/workspace/m12/events.jsonl")


async def answer_requests(bridge):
    while True:
        if ASK.exists():
            request = json.loads(ASK.read_text(encoding="utf-8"))
            ASK.unlink()
            try:
                answer = await bridge.call("mob_act", **request)
            except RuntimeError as error:
                answer = {"error": str(error)}
            ANSWER.write_text(json.dumps(answer), encoding="utf-8")
        await asyncio.sleep(0.2)


async def run():
    bridge = Bridge()
    await bridge.connect()
    reader = asyncio.create_task(bridge.run())
    governor = Governor()
    mind = minds.Minds(governor, bridge, lambda: (set(), []))
    asyncio.create_task(answer_requests(bridge))
    print("minds running", flush=True)
    while True:
        event = await bridge.events.get()
        if event.get("event") == "mob":
            with LAST_EVENT.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({key: value for key, value in event.items() if key != "mind"}) + "\n")
            asyncio.create_task(mind.handle(event))
    reader.cancel()


if __name__ == "__main__":
    asyncio.run(run())
