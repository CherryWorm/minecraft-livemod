"""Lets builders run on other machines. They connect out to this over HTTPS, so one can be behind a home router, and they
only ever do the part that's a model writing code. Everything that decides what ships stays here: a machine's work
goes through the same gates, review and release as anyone's, and only its feature's own folder and the ones it declares are taken from it.

A machine has a token, and the agent only keeps its hash, so nothing a builder here could read would let it pose as one.
"""
import asyncio
import dataclasses
import hashlib
import hmac
import json
import os
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from orchestrator import lanes, ledger, llm, model_bridge, others, world_index

PORT = 8790
MACHINES = pathlib.Path(os.environ.get("CONTROL_DIR", "/control")) / "workers.json"
CODE = pathlib.Path(__file__).parent
SEEN_WITHIN_SECONDS = 90
SILENT_JOB_SECONDS = 180
CLAIM_WAIT_SECONDS = 20
MOST_UPLOAD_BYTES = 300 * 1024 * 1024
ASKABLE = ("lint", "check", "javap", "status")  # Never gates or a release. Those only ever start from the main server's own code.


def code_version():
    """Both ends have to run the same code, or a machine could quietly build against rules that have changed."""
    digest = hashlib.sha256()
    for path in sorted(CODE.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".md") and "__pycache__" not in path.parts:
            digest.update(path.relative_to(CODE).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@dataclasses.dataclass
class Job:
    id: str
    feature_id: str
    tree: pathlib.Path
    details: dict
    future: asyncio.Future
    worker: str = ""  # Who has it, or who has to get it, because only they have its conversation so far.
    last_heard: float = 0.0


class WorkerHub:
    def __init__(self, repo, ask, governor, reached):
        self.repo = repo
        self.ask = ask
        self.governor = governor
        self.reached = reached
        self.waiting = []
        self.jobs = {}
        self.machines = {}  # What's connected, by name: its slots and when it was last heard from.
        self.sessions = {}  # Which machine holds which feature's conversation.
        self.wake = asyncio.Event()

    # What the workshop uses --------------------------------------------------------------------------------

    def free_slots(self):
        now = time.time()
        total = sum(machine["slots"] for machine in self.machines.values() if now - machine["seen"] < SEEN_WITHIN_SECONDS)
        return max(0, total - len(self.jobs))

    async def attempt(self, feature_id, tree, details):
        """Has another machine do one attempt, and comes back when it's done, or as a failed attempt if it's gone quiet."""
        session = details.get("session")
        holder = self.sessions.get(feature_id, "")
        if session and not self._alive(holder):
            details = {**details, "session": None}  # That conversation is out of reach, so this one starts over.
            holder = ""
        job = Job(uuid.uuid4().hex[:12], feature_id, tree, details, asyncio.get_running_loop().create_future(), holder if session else "", time.time())
        self.waiting.append(job)
        self.jobs[job.id] = job
        self.wake.set()
        try:
            return await job.future
        finally:
            self.jobs.pop(job.id, None)
            if job in self.waiting:
                self.waiting.remove(job)
            subprocess.run(["git", "update-ref", "-d", f"refs/workers/{job.id}"], cwd=self.repo, check=False, capture_output=True)

    def _alive(self, name):
        machine = self.machines.get(name)
        return bool(machine) and time.time() - machine["seen"] < SEEN_WITHIN_SECONDS

    async def sweep(self):
        """A machine can vanish at any moment, so a silent job becomes a failed attempt, and the next one can run elsewhere."""
        while True:
            await asyncio.sleep(30)
            self.check_silent()

    def check_silent(self):
        now = time.time()
        for job in list(self.jobs.values()):
            if now - job.last_heard <= SILENT_JOB_SECONDS or job.future.done():
                continue
            # If it was never picked up, nobody's coming for it, so it shouldn't hold up the feature either.
            print(f"{job.feature_id}: {job.worker or 'no machine'} has gone quiet", flush=True)
            job.future.set_result(llm.Result("", None, "", 0.0, True, lanes.MACHINE_GONE[0 if job in self.waiting else 1], 0.0))

    # Asking who's who ---------------------------------------------------------------------------------------

    def _who(self, request):
        """The machine's name if its token is right. The file is read every time, so adding one needs no restart."""
        header = request.headers.get("authorization", "")
        offered = header.removeprefix("Bearer ")
        if offered == header or not offered or not MACHINES.exists():
            return None
        digest = hashlib.sha256(offered.encode()).hexdigest()
        for name, machine in json.loads(MACHINES.read_text(encoding="utf-8")).items():
            if hmac.compare_digest(digest, machine.get("token_sha256", "")):
                return name
        return None

    def _job(self, request, who):
        job = self.jobs.get(request.path_params["job"])
        return job if job and job.worker == who and not job.future.done() else None

    def _git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.repo, check=check, capture_output=True, text=True).stdout.strip()

    def _known(self, job, commit):
        """A commit this job uploaded, or one the world's main branch already has."""
        return any(subprocess.run(["git", "merge-base", "--is-ancestor", commit, ref], cwd=self.repo, capture_output=True).returncode == 0
                   for ref in (f"refs/workers/{job.id}", "main"))

    # Routes -------------------------------------------------------------------------------------------------

    async def hello(self, request, who):
        body = await request.json()
        ours = code_version()
        if body.get("code") != ours:
            return JSONResponse({"problem": "This machine's code doesn't match the server's. Update its checkout and start it again.", "server_code": ours}, status_code=409)
        self.machines[who] = {"slots": int(body.get("slots", 1)), "lane": body.get("lane"), "seen": time.time()}
        print(f"builder machine {who} connected with {self.machines[who]['slots']} slots on {body.get('lane')}", flush=True)
        self.wake.set()
        return JSONResponse({"name": who})

    async def alive(self, request, who):
        if who not in self.machines:
            return JSONResponse({"problem": "Say hello first."}, status_code=409)
        self.machines[who]["seen"] = time.time()
        body = await request.json()
        for job_id in body.get("jobs", []):
            job = self.jobs.get(job_id)
            if job and job.worker == who:
                job.last_heard = time.time()
        return JSONResponse({"jobs": [job_id for job_id in body.get("jobs", []) if job_id in self.jobs]})

    async def claim(self, request, who):
        if who not in self.machines:
            return JSONResponse({"problem": "Say hello first."}, status_code=409)
        self.machines[who]["seen"] = time.time()
        deadline = time.monotonic() + CLAIM_WAIT_SECONDS
        while time.monotonic() < deadline:
            for job in self.waiting:
                if job.worker in ("", who):
                    self.waiting.remove(job)
                    job.worker = who
                    job.last_heard = time.time()
                    self.sessions[job.feature_id] = who
                    print(f"{job.feature_id}: going to {who}", flush=True)
                    return JSONResponse({"job": {"id": job.id, "feature_id": job.feature_id, **job.details}})
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), 2)
            except TimeoutError:
                pass
        return JSONResponse({"job": None})

    async def bundle(self, request, who):
        """The world's repository, or just what's new since what the machine says it has."""
        job = self._job(request, who)
        if job is None:
            return JSONResponse({"problem": "That job is over."}, status_code=404)
        have = request.query_params.get("have", "")
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "repo.bundle")

        def make():
            refs = ["main", f"feature/{job.feature_id}"]
            known = subprocess.run(["git", "cat-file", "-e", f"{have}^{{commit}}"], cwd=self.repo, capture_output=True).returncode == 0 if have else False
            result = subprocess.run(["git", "bundle", "create", path, *refs, *(["--not", have] if known else [])], cwd=self.repo, capture_output=True, text=True)
            return result.returncode == 0

        # A bundle leaves out any branch with nothing new on it, so the machine is always told where they both are.
        where = {"x-main": self._git("rev-parse", "main"), "x-feature": self._git("rev-parse", f"feature/{job.feature_id}")}
        if not await asyncio.to_thread(make):
            shutil.rmtree(folder, ignore_errors=True)
            return Response(status_code=204, headers=where)
        return FileResponse(path, headers=where, background=BackgroundTask(shutil.rmtree, folder, True))

    async def objects(self, request, who):
        """Commits from the machine, kept off to one side, where the gates can read them but nothing treats them as the world's."""
        job = self._job(request, who)
        if job is None:
            return JSONResponse({"problem": "That job is over."}, status_code=404)
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "up.bundle")
        size = 0
        try:
            with open(path, "wb") as stream:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MOST_UPLOAD_BYTES:
                        return JSONResponse({"problem": "That's too big."}, status_code=413)
                    stream.write(chunk)
            result = await asyncio.to_thread(subprocess.run, ["git", "fetch", "-q", path, f"+refs/heads/upload:refs/workers/{job.id}"],
                                             cwd=self.repo, capture_output=True, text=True)
            if result.returncode != 0:
                return JSONResponse({"problem": result.stderr[-400:]}, status_code=400)
            return JSONResponse({"commit": self._git("rev-parse", f"refs/workers/{job.id}")})
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    async def ask_broker(self, request, who):
        job = self._job(request, who)
        if job is None:
            return JSONResponse({"problem": "That job is over."}, status_code=404)
        body = await request.json()
        kind = body.get("kind")
        fields = body.get("fields") or {}
        if kind not in ASKABLE:
            return JSONResponse({"problem": f"{kind} isn't something a machine can ask for."}, status_code=403)
        commit = fields.get("commit")
        if commit and not self._known(job, commit):
            return JSONResponse({"problem": "That commit hasn't been uploaded for this job."}, status_code=400)
        job.last_heard = time.time()
        if kind == "status":
            ledger.status_of(job.feature_id, fields.get("phase"), fields.get("doing"))
            return JSONResponse({"answer": {"result": "noted"}, "main": self._git("rev-parse", "main")})
        answer = await self.ask(kind, **{key: value for key, value in fields.items() if key in ("commit", "class_name", "private", "code")})
        return JSONResponse({"answer": answer, "main": self._git("rev-parse", "main")})

    async def world(self, request, who):
        job = self._job(request, who)
        if job is None:
            return JSONResponse({"problem": "That job is over."}, status_code=404)
        job.last_heard = time.time()
        return JSONResponse({"text": world_index.build(self.repo / "mods/genesis/features", self.reached())})

    async def reference(self, request, who):
        """Vanilla's art, to compare with in previews. It comes from the server's own copy of the game."""
        source = self.repo.parent / "reference-textures"
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "reference.tar.gz")

        def make():
            with tarfile.open(path, "w:gz") as archive:
                if source.exists():
                    archive.add(source, arcname=".")

        await asyncio.to_thread(make)
        return FileResponse(path, background=BackgroundTask(shutil.rmtree, folder, True))

    async def result(self, request, who):
        job = self._job(request, who)
        if job is None:
            return JSONResponse({"problem": "That job is over."}, status_code=404)
        body = await request.json()
        commit = body.get("commit")
        if commit:
            problem = await asyncio.to_thread(self._take_feature, job, commit)
            if problem:
                job.future.set_result(llm.Result(problem, None, body.get("session_id", ""), 0.0, True, "bad_upload", 0.0))
                return JSONResponse({"problem": problem}, status_code=400)
        if body.get("counted"):
            self.governor.record_usage(body.get("estimate"))
            for status, resets_at in body.get("rate_limits", []):
                self.governor.record_rate_limit(status, resets_at)
        job.future.set_result(llm.Result(body.get("text", ""), None, body.get("session_id", ""), float(body.get("estimate") or 0), bool(body.get("is_error")),
                                         body.get("stop_reason", ""), float(body.get("seconds") or 0), body.get("handed_back")))
        return JSONResponse({"ok": True})

    def _take_feature(self, job, commit):
        """Only the feature's own folder and the ones it declares are taken, as they are at that commit, so nothing else a machine did can come along."""
        if not self._known(job, commit):
            return "That commit hasn't been uploaded for this job."
        manifest = subprocess.run(["git", "show", f"{commit}:mods/genesis/features/{job.feature_id}/feature.json"], cwd=job.tree, capture_output=True, text=True, errors="replace")
        declared = (others.declared(manifest.stdout) or set()) if manifest.returncode == 0 else set()
        for feature in (job.feature_id, *sorted(declared - {job.feature_id})):
            folder = f"mods/genesis/features/{feature}"
            listed = subprocess.run(["git", "cat-file", "-e", f"{commit}:{folder}"], cwd=job.tree, capture_output=True)
            if listed.returncode != 0:
                continue  # It made nothing yet, and the gates will say so.
            shutil.rmtree(job.tree / folder, ignore_errors=True)
            subprocess.run(["git", "checkout", commit, "--", folder], cwd=job.tree, check=True, capture_output=True)
        return None

    def app(self):
        def guarded(handler):
            async def route(request):
                who = self._who(request)
                if who is None:
                    return JSONResponse({"problem": "Who are you?"}, status_code=401)
                return await handler(request, who)
            return route

        return Starlette(routes=[
            Route("/worker/hello", guarded(self.hello), methods=["POST"]),
            Route("/worker/alive", guarded(self.alive), methods=["POST"]),
            Route("/worker/claim", guarded(self.claim), methods=["POST"]),
            Route("/worker/reference", guarded(self.reference), methods=["GET"]),
            Route("/worker/job/{job}/bundle", guarded(self.bundle), methods=["GET"]),
            Route("/worker/job/{job}/objects", guarded(self.objects), methods=["POST"]),
            Route("/worker/job/{job}/ask", guarded(self.ask_broker), methods=["POST"]),
            Route("/worker/job/{job}/world", guarded(self.world), methods=["POST"]),
            Route("/worker/job/{job}/result", guarded(self.result), methods=["POST"]),
        ])

    async def serve(self):
        await asyncio.gather(model_bridge.serve(self.app(), "0.0.0.0", PORT, "the builder hub"), self.sweep())
