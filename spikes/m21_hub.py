#!/usr/bin/env python3
"""The main server's half of a builder on another machine, for broker/tests/m21_test.py: the real hub and the world's real
repository, with a stand-in for the broker that writes down what it's asked. Runs in the agent's container."""
import asyncio
import hashlib
import json
import os
import pathlib
import subprocess
import urllib.error
import urllib.request

from orchestrator import model_bridge, worker_hub, workshop

TOKEN = os.environ["M21_TOKEN"]
OUT = pathlib.Path("/workspace/hub-out.json")
BASE = f"http://127.0.0.1:{worker_hub.PORT}"


def call(path, body=None, token=TOKEN):
    request = urllib.request.Request(BASE + path, data=json.dumps(body or {}).encode(), method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


class Governor:
    def __init__(self):
        self.usage = 0

    def record_usage(self, estimate):
        self.usage += 1

    def record_rate_limit(self, status, resets_at):
        pass


async def run():
    worker_hub.MACHINES.parent.mkdir(parents=True, exist_ok=True)
    worker_hub.MACHINES.write_text(json.dumps({"tester": {"token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(), "slots": 1}}), encoding="utf-8")
    workshop.setup_repo()
    (workshop.REPO / "mods/genesis/features/.keep").write_text("", encoding="utf-8")
    workshop.commit_all("Something in the world")

    asked = []

    async def ask(kind, **fields):
        known = subprocess.run(["git", "cat-file", "-e", fields["commit"]], cwd=workshop.REPO).returncode == 0 if "commit" in fields else None
        asked.append({"kind": kind, "fields": sorted(fields), "commit_is_here": known})
        return {"result": "passed_lint", "output": "public class Fake"} if kind != "javap" else {"output": "public class Fake"}

    governor = Governor()
    hub = worker_hub.WorkerHub(workshop.REPO, ask, governor, lambda: ())
    serving = asyncio.create_task(model_bridge.serve(hub.app(), "0.0.0.0", worker_hub.PORT, "the hub"))
    await asyncio.sleep(1)

    outcome = {}
    outcome["nobody_without_a_token"] = (await asyncio.to_thread(call, "/worker/claim", None, "wrong-token"))[0]
    outcome["old_code_refused"] = (await asyncio.to_thread(call, "/worker/hello", {"code": "old", "slots": 1, "lane": "x"}))[0]

    for _ in range(120):
        if hub.free_slots() > 0:
            break
        await asyncio.sleep(1)
    outcome["machine_connected"] = hub.free_slots()

    shop = workshop.Workshop(governor, None, None)
    tree = shop._prepare_tree("demo")
    details = {"prompt": "Make the thing.", "system": "You build things.", "session": None, "small": False, "node": "e_one", "stage": "early", "max_turns": 25, "budget": 5.0}

    first = asyncio.create_task(hub.attempt("demo", tree, details))
    running = []
    for _ in range(600):
        running = [job for job in hub.jobs.values() if job.worker]
        if running:
            break
        await asyncio.sleep(0.1)
    job = running[0]
    outcome["cant_ask_for_a_release"] = (await asyncio.to_thread(call, f"/worker/job/{job.id}/ask", {"kind": "release", "fields": {}}))[0]
    outcome["cant_ask_for_gates"] = (await asyncio.to_thread(call, f"/worker/job/{job.id}/ask", {"kind": "gates", "fields": {}}))[0]
    outcome["cant_name_a_commit_it_didnt_send"] = (await asyncio.to_thread(call, f"/worker/job/{job.id}/ask", {"kind": "lint", "fields": {"commit": "0" * 40}}))[0]
    result = await asyncio.wait_for(first, 240)
    outcome["first"] = {"error": result.is_error, "stop": result.stop_reason, "text": result.text[:300], "session": bool(result.session_id)}
    outcome["asked"] = list(asked)
    folder = tree / "mods/genesis/features/demo"
    outcome["feature_arrived"] = (folder / "feature.json").exists()
    outcome["node_stamped"] = json.loads((folder / "feature.json").read_text(encoding="utf-8")).get("node") if outcome["feature_arrived"] else None
    outcome["nothing_else_came_with_it"] = not (tree / "rogue.txt").exists()

    # Something else ships while it's away, and the same conversation carries on with that in view.
    workshop.ready_commit("demo: back from the machine", tree, "demo", "e_one")
    (workshop.REPO / "mods/genesis/features/other").mkdir(parents=True, exist_ok=True)
    (workshop.REPO / "mods/genesis/features/other/feature.json").write_text("{}", encoding="utf-8")
    workshop.commit_all("Something else shipped")
    second = await asyncio.wait_for(hub.attempt("demo", tree, {**details, "prompt": "A reviewer found problems. Fix them.", "session": result.session_id}), 240)
    outcome["second"] = {"error": second.is_error, "stop": second.stop_reason, "text": second.text[:300]}

    outcome["refs_cleaned"] = subprocess.run(["git", "for-each-ref", "refs/workers"], cwd=workshop.REPO, capture_output=True, text=True).stdout.strip() == ""
    OUT.write_text(json.dumps(outcome), encoding="utf-8")
    serving.cancel()


asyncio.run(run())
