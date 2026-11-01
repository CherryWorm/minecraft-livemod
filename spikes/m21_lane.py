#!/usr/bin/env python3
"""One real builder on a self-hosted model, for broker/tests/m21_test.py. Runs in the agent's container, as the agent's user."""
import asyncio
import json
import pathlib
import urllib.error
import urllib.request

from claude_agent_sdk import AgentDefinition

from orchestrator import lanes, llm, workshop


class Counted:
    def __init__(self):
        self.usage = 0
        self.rate_limits = 0

    def record_usage(self, estimate):
        self.usage += 1

    def record_rate_limit(self, status, resets_at):
        self.rate_limits += 1


async def run():
    work = pathlib.Path("/workspace/lane")
    work.mkdir(parents=True, exist_ok=True)
    # The smallest real PNG, to see what happens when a builder looks at art.
    (work / "art.png").write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001"
                                                 "0001a5f645400000000049454e44ae426082"))
    self_hosted = lanes.SelfHosted()
    server = asyncio.create_task(self_hosted.serve())
    await asyncio.sleep(1)
    lane = self_hosted.lane

    def knock(token):
        request = urllib.request.Request(f"http://127.0.0.1:{self_hosted.bridge.port}/v1/messages", data=b"{}", method="POST", headers={"x-api-key": token, "Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(request, timeout=10).status
        except urllib.error.HTTPError as error:
            return error.code

    outcome = {"wrong_password": await asyncio.to_thread(knock, "not-the-password"), "lane_note": bool(lane.note)}
    meter = Counted()
    tools = ["Read", "Write", "Bash", "Agent", "Task"]
    agents = {"helper": AgentDefinition(description="A helper.", prompt="HELPER-MARKER", tools=["Read"], model=llm.WORKER["model"], effort=llm.WORKER["effort"])}
    result = await llm.ask(meter, "builder", "Make the thing.", system="You build things.", tools=tools, allowed_tools=tools, disallowed_tools=workshop.BUILDER_DENIED,
                           agents=agents, cwd=str(work), max_turns=20, budget=5.0, lane=lane)
    outcome.update({"text": result.text, "is_error": result.is_error, "stop": result.stop_reason, "session": bool(result.session_id), "hello": (work / "hello.txt").exists(),
                    "usage_calls": meter.usage, "rate_limit_calls": meter.rate_limits})
    pathlib.Path("/workspace/lane-out.json").write_text(json.dumps(outcome), encoding="utf-8")
    server.cancel()


asyncio.run(run())
