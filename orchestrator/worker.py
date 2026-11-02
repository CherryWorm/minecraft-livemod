"""A builder on another machine. It asks the main server for work, has a model write the feature here, and hands the
result back. It has no way to reach the game or to release anything, and it holds nothing of the server's but its token.

Usage, inside the agent's container: python3 -m orchestrator.worker
"""
import asyncio
import json
import os
import pathlib
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

from claude_agent_sdk import create_sdk_mcp_server, tool

from orchestrator import lanes, ledger, llm, research, scrub, worker_hub, workshop

HUB = os.environ.get("WORKER_HUB_URL", "").rstrip("/")
SLOTS = int(os.environ.get("WORKER_SLOTS", "1"))
LANE = os.environ.get("WORKER_LANE", lanes.SELF_HOSTED)
TOKEN_FD = 6
ALIVE_SECONDS = 30
RETRY_SECONDS = 15
HAND_BACK_TRIES = 8
WRONG_CODE_WAIT_SECONDS = 60  # It keeps being restarted until someone updates it, so it should do that slowly.
REQUEST_SECONDS = 900


class Meter:
    """Stands in for the governor, because the main server is what keeps count. What's used here goes back with the result."""

    def __init__(self):
        self.rate_limits = []

    def record_usage(self, estimate):
        pass

    def record_rate_limit(self, status, resets_at):
        self.rate_limits.append([status, resets_at])


class Hub:
    def __init__(self, token):
        self.token = token

    def _send(self, method, path, data=None, content_type="application/json"):
        request = urllib.request.Request(HUB + path, data=data, method=method, headers={"Authorization": f"Bearer {self.token}", "Content-Type": content_type})
        return urllib.request.urlopen(request, timeout=REQUEST_SECONDS)

    def post(self, path, body=None):
        """Returns the status and the answer, because some refusals are an answer the caller needs."""
        try:
            with self._send("POST", path, json.dumps(body or {}).encode()) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, _answer(error)

    def download(self, path, target):
        """Returns the response's headers. The file is only there if there was anything to send."""
        with self._send("GET", path) as response:
            headers = {name.lower(): value for name, value in response.headers.items()}
            if response.status != 204:
                with open(target, "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
        return headers

    def upload(self, path, source):
        with open(source, "rb") as stream:
            data = stream.read()
        try:
            with self._send("POST", path, data, "application/octet-stream") as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, _answer(error)


def _answer(error):
    """What a refusal said. While the main server restarts, what answers is the web server in front of it, which doesn't speak JSON."""
    body = error.read()
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return {"problem": f"The server said {error.code}."}


def _git(*args, cwd=None):
    return workshop._git(*args, cwd=cwd or workshop.REPO)


class Worker:
    def __init__(self, hub, lane):
        self.hub = hub
        self.lane = lane
        self.running = set()
        self.git_lock = asyncio.Lock()  # Git keeps one index and one set of refs for all of a repository's trees.

    def _ensure_repo(self):
        if not (workshop.REPO / ".git").exists():
            workshop.REPO.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", "-b", "main")
            _git("config", "user.name", "Living Mod builder")
            _git("config", "user.email", "builder@localhost")

    def _sync(self, job_id, feature_id):
        """Brings main and this feature's branch up to what the server has, and returns the feature's tree."""
        self._sync_branches(job_id, feature_id)
        tree = workshop.TREES / feature_id
        if not tree.exists():
            workshop.TREES.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "worktree", "prune"], cwd=workshop.REPO, check=False)
            _git("worktree", "add", "-q", str(tree), f"feature/{feature_id}")
        # The server's branch is the truth, because it's what came through its checks.
        subprocess.run(["git", "reset", "-q", "--hard", f"feature/{feature_id}"], cwd=tree, check=True, capture_output=True)
        (tree / "mods/genesis/features" / feature_id).mkdir(parents=True, exist_ok=True)
        return tree

    def _sync_branches(self, job_id, feature_id):
        have = subprocess.run(["git", "rev-parse", "--verify", "-q", "main"], cwd=workshop.REPO, capture_output=True, text=True).stdout.strip()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "repo.bundle")
            where = self.hub.download(f"/worker/job/{job_id}/bundle?have={have}", path)
            if os.path.exists(path):
                # Not straight onto the branches, because git won't update one that a tree has checked out.
                _git("fetch", "-q", path, "+refs/heads/*:refs/incoming/*")
        _git("update-ref", "refs/heads/main", where["x-main"])
        if feature_id:
            _git("update-ref", f"refs/heads/feature/{feature_id}", where["x-feature"])
        subprocess.run(["git", "reset", "-q", "--hard", "main"], cwd=workshop.REPO, check=True, capture_output=True)

    def _is_new(self, commit):
        return subprocess.run(["git", "merge-base", "--is-ancestor", commit, "main"], cwd=workshop.REPO, capture_output=True).returncode != 0

    def _upload(self, job_id, commit):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "up.bundle")
            _git("branch", "-f", "upload", commit)
            _git("bundle", "create", "-q", path, "upload", "--not", "main")
            status, answer = self.hub.upload(f"/worker/job/{job_id}/objects", path)
        if status != 200:
            raise RuntimeError(answer.get("problem", f"upload failed with {status}"))

    def _asker(self, job_id, feature_id):
        async def ask(kind, **fields):
            async with self.git_lock:
                commit = fields.get("commit")
                # Nothing new since main means there's nothing to send, and the server has main already.
                if commit and self._is_new(commit):
                    await asyncio.to_thread(self._upload, job_id, commit)
            status, answer = await asyncio.to_thread(self.hub.post, f"/worker/job/{job_id}/ask", {"kind": kind, "fields": fields})
            if status != 200:
                return {"result": "blocked", "gate": "broker", "reason": answer.get("problem", f"The server said {status}.")}
            # Something else may have shipped, and the next commit has to be built on it.
            async with self.git_lock:
                if answer.get("main") != _git("rev-parse", "main"):
                    await asyncio.to_thread(self._sync_branches, job_id, None)
            return answer["answer"]
        return ask

    def _world_server(self, job_id):
        @tool("world_index", "Lists everything built so far with its numbers, by where it sits in the progression, marking what players already have.", {})
        async def index(args):
            status, answer = await asyncio.to_thread(self.hub.post, f"/worker/job/{job_id}/world")
            return workshop._text(answer.get("text") or answer.get("problem", f"The server said {status}."))
        return create_sdk_mcp_server("world", tools=[index])

    async def run(self, job):
        job_id, feature_id = job["id"], job["feature_id"]
        print(f"{feature_id}: starting", flush=True)
        self.running.add(job_id)
        began = time.monotonic()
        meter = Meter()
        notes = ledger.Notebook()
        ledger.ACTIVE.set(notes)  # This job has a task of its own, so that's all this reaches.
        try:
            async with self.git_lock:
                tree = await asyncio.to_thread(self._sync, job_id, feature_id)
            ask = self._asker(job_id, feature_id)
            small = job.get("small", False)
            names = workshop.SMALL_TOOLS if small else [name for name in workshop.BUILDER_TOOLS if name != research.TOOL_NAME]
            prompt = (self.lane.note if self.lane and not job.get("session") else "") + job["prompt"]
            result = await llm.ask(meter, "small_builder" if small else "builder", prompt, system=job["system"], tools=names, allowed_tools=names,
                                   disallowed_tools=workshop.BUILDER_DENIED, agents=None if small else workshop.SUBAGENTS, cwd=str(tree),
                                   max_turns=job["max_turns"], resume=job.get("session"), budget=job.get("budget"), lane=self.lane,
                                   mcp_servers={"broker": workshop._tools_for(feature_id, tree, job["node"], ask=ask), "world": self._world_server(job_id)})
            async with self.git_lock:
                try:
                    commit = await asyncio.to_thread(workshop.ready_commit, f"{feature_id}: from this machine", tree, feature_id, job["node"])
                except workshop.Refused:  # It's committed as far as it can be, and the server's own checks will say what's wrong with it.
                    commit = _git("rev-parse", "HEAD", cwd=tree)
                if self._is_new(commit):
                    await asyncio.to_thread(self._upload, job_id, commit)
            body = {"commit": commit, "session_id": result.session_id, "is_error": result.is_error, "stop_reason": result.stop_reason, "text": result.text[:2000],
                    "seconds": round(time.monotonic() - began, 1), "estimate": result.estimate, "counted": self.lane is None, "rate_limits": meter.rate_limits, "handed_back": notes.handed_back()}
        except Exception as error:  # noqa: BLE001 - the server has to hear, so it doesn't wait for a job that's over
            print(f"{feature_id}: failed: {error}", flush=True)
            body = {"is_error": True, "stop_reason": "worker_failed", "text": str(error)[:500], "seconds": round(time.monotonic() - began, 1)}
        finally:
            self.running.discard(job_id)
        for _ in range(HAND_BACK_TRIES):
            try:
                status, answer = await asyncio.to_thread(self.hub.post, f"/worker/job/{job_id}/result", body)
                print(f"{feature_id}: handed back ({status}) {answer.get('problem', '')}", flush=True)
                if status < 500:
                    return
            except OSError as error:
                print(f"{feature_id}: couldn't hand it back yet: {error}", flush=True)
            await asyncio.sleep(RETRY_SECONDS)

    async def slot(self):
        while True:
            try:
                status, answer = await asyncio.to_thread(self.hub.post, "/worker/claim")
            except OSError as error:
                print(f"couldn't reach the server: {error}", flush=True)
                await asyncio.sleep(RETRY_SECONDS)
                continue
            if status == 200 and answer.get("job"):
                await self.run(answer["job"])
            elif status != 200:
                # It restarted and has forgotten this machine, or hasn't heard of it yet, or is still on its way back.
                try:
                    await self.say_hello()
                except OSError as error:
                    print(f"couldn't reach the server: {error}", flush=True)
                await asyncio.sleep(RETRY_SECONDS)

    async def say_hello(self):
        status, answer = await asyncio.to_thread(self.hub.post, "/worker/hello", {"code": worker_hub.code_version(), "slots": SLOTS, "lane": LANE})
        if status == 409:
            print(answer.get("problem"), flush=True)
            await asyncio.sleep(WRONG_CODE_WAIT_SECONDS)
            raise SystemExit(1)
        if status != 200:
            print(f"the server said {status}: {answer.get('problem', '')}", flush=True)
        return status == 200

    async def heartbeat(self):
        while True:
            await asyncio.sleep(ALIVE_SECONDS)
            try:
                status, _ = await asyncio.to_thread(self.hub.post, "/worker/alive", {"jobs": sorted(self.running)})
                if status == 409:
                    await self.say_hello()
            except OSError as error:
                print(f"couldn't reach the server: {error}", flush=True)

    def _fetch_reference(self):
        target = workshop.REFERENCE_TEXTURES
        if target.exists() and any(target.iterdir()):
            return
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "reference.tar.gz")
            self.hub.download("/worker/reference", path)
            with tarfile.open(path) as archive:
                archive.extractall(target, filter="data")

    async def main(self):
        self._ensure_repo()
        workshop.REPORTS.mkdir(parents=True, exist_ok=True)
        pathlib.Path("/workspace/state").mkdir(parents=True, exist_ok=True)
        while True:
            try:
                if await self.say_hello():
                    break
            except OSError as error:
                print(f"couldn't reach the server: {error}", flush=True)
            await asyncio.sleep(RETRY_SECONDS)
        await asyncio.to_thread(self._fetch_reference)
        print(f"ready, with {SLOTS} slots on {LANE}", flush=True)
        await asyncio.gather(self.heartbeat(), *(self.slot() for _ in range(SLOTS)), *([self_hosted.serve()] if self_hosted.bridge else []))


self_hosted = None


def start():
    global self_hosted
    with os.fdopen(TOKEN_FD) as stream:
        token = stream.read().strip()
    scrub.keep_out(token)
    self_hosted = lanes.SelfHosted()
    lane = self_hosted.lane if LANE == lanes.SELF_HOSTED else None
    if LANE == lanes.SELF_HOSTED and lane is None:
        raise SystemExit("This machine is set to use a self-hosted model, but none is set up.")
    asyncio.run(Worker(Hub(token), lane).main())


if __name__ == "__main__":
    start()
