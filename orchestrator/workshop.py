"""Builds one feature: a lead with parallel subagents, then review and gates side by side, then release.

The agent works in a git worktree, and only plain code commits, requests checks and asks for a release.
"""
import asyncio
import json
import os
import pathlib
import subprocess
import time
import uuid

from claude_agent_sdk import AgentDefinition, create_sdk_mcp_server, tool

from orchestrator import llm

REPO = pathlib.Path("/workspace/repo")
TREES = pathlib.Path("/workspace/trees")
REQUESTS = pathlib.Path("/workspace/requests")
RESPONSES = pathlib.Path("/workspace/responses")
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = {"check": 300, "gates": 900, "release": 900, "javap": 60}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"approve": {"type": "boolean"}, "problems": {"type": "array", "items": {"type": "string"}}},
    "required": ["approve", "problems"],
}

SUBAGENTS = {
    "artist": AgentDefinition(
        description="Makes a feature's textures with assetkit. Give it the texture names and what each should look like.",
        prompt=("You make Minecraft textures. Read assetkit/README.md and bible/theme.md, write the PNGs to the feature's "
                "assets/textures folder, then look at them by reading the contact sheet, and fix anything muddy, noisy or flat. "
                "16x16, small palette, soft contrast, and they should look at home next to vanilla blocks."),
        tools=["Read", "Write", "Edit", "Glob", "Bash"],
        model=llm.WORKER["model"],
        effort=llm.WORKER["effort"],
    ),
    "coder": AgentDefinition(
        description="Writes a feature's Java modules. Give it the behaviour needed and the names in feature.json.",
        prompt=("You write Java modules for a Minecraft 26.3 mod. Read docs/feature-format.md and /reference for the API. Many "
                "Minecraft APIs were renamed recently, so check real signatures with the java_api tool. Keep tick work small, and "
                "use no files, network or threads. Keep state where the docs say, so it survives the module being swapped."),
        tools=["Read", "Write", "Edit", "Glob", "Grep", "mcp__broker__java_api"],
        model=llm.WORKER["model"],
        effort=llm.WORKER["effort"],
    ),
}


def _git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def setup_repo():
    """The agent's own repository. It holds features and the design documents, and nothing else that runs."""
    (REPO / "mods" / "genesis" / "features").mkdir(parents=True, exist_ok=True)
    (REPO / "bible").mkdir(parents=True, exist_ok=True)
    if not (REPO / ".git").exists():
        _git("init", "-q", "-b", "main")
        _git("config", "user.name", "Living Mod agent")
        _git("config", "user.email", "agent@localhost")
        _git("commit", "-q", "--allow-empty", "-m", "Start of this world")
    for name in ("docs", "assetkit"):
        target = REPO / name
        source = pathlib.Path("/reference") / name
        if source.exists():
            subprocess.run(["rsync", "-a", "--delete", f"{source}/", f"{target}/"], check=False)


def commit_all(message, cwd=REPO):
    _git("add", "-A", cwd=cwd)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=cwd, check=False).returncode != 0:
        _git("commit", "-q", "-m", message, cwd=cwd)
    return _git("rev-parse", "HEAD", cwd=cwd)


async def request(kind, **fields):
    """Asks the broker, which runs outside this container, and waits for its answer."""
    request_id = uuid.uuid4().hex[:12]
    REQUESTS.mkdir(parents=True, exist_ok=True)
    temporary = REQUESTS / f".{request_id}.tmp"
    temporary.write_text(json.dumps({"id": request_id, "kind": kind, **fields}), encoding="utf-8")
    temporary.rename(REQUESTS / f"{request_id}.json")
    answer = RESPONSES / f"{request_id}.json"
    deadline = time.monotonic() + REQUEST_TIMEOUT[kind]
    while time.monotonic() < deadline:
        if answer.exists():
            return json.loads(answer.read_text(encoding="utf-8"))
        await asyncio.sleep(0.5)
    return {"result": "blocked", "gate": "broker", "reason": f"The broker didn't answer a {kind} request in time."}


def _tools_for(feature_id, tree):
    @tool("check_feature", "Compiles this feature and runs the static checks. Takes about 15 seconds.", {})
    async def check_feature(args):
        commit = commit_all(f"{feature_id}: work in progress", cwd=tree)
        answer = await request("check", commit=commit)
        text = "All checks passed." if answer.get("result") in ("passed_gates", "nothing_to_release") \
            else f"Failed at {answer.get('gate')}: {answer.get('reason')}"
        return {"content": [{"type": "text", "text": text}]}

    @tool("java_api", "Shows the real public methods and fields of a Minecraft or Fabric class. Pass the full class name.",
          {"class_name": str})
    async def java_api(args):
        answer = await request("javap", class_name=args["class_name"])
        return {"content": [{"type": "text", "text": answer.get("output") or answer.get("reason", "Not found.")}]}

    return create_sdk_mcp_server("broker", tools=[check_feature, java_api])


BUILDER_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Agent", "Task",
                 "mcp__broker__check_feature", "mcp__broker__java_api"]


class Workshop:
    def __init__(self, governor, on_released):
        self.governor = governor
        self.on_released = on_released

    def _prepare_tree(self, feature_id):
        tree = TREES / feature_id
        if not tree.exists():
            TREES.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "worktree", "prune"], cwd=REPO, check=False)
            _git("worktree", "add", "-q", "-B", f"feature/{feature_id}", str(tree), "main")
        return tree

    async def _review(self, spec, feature_id, tree, screenshots):
        shots = "\n".join(f"- {path}" for path in screenshots) or "(none: this feature adds nothing visible)"
        prompt = (f"Spec:\n{llm.untrusted('spec', spec)}\n\nThe feature is in {tree}/mods/genesis/features/{feature_id}. "
                  f"The world's theme is in {tree}/bible/theme.md.\n\nScreenshots from a real game client:\n{shots}")
        result = await llm.ask(self.governor, "reviewer", prompt, schema=VERDICT_SCHEMA, tools=["Read", "Glob", "Grep"],
                               allowed_tools=["Read", "Glob", "Grep"], cwd=str(tree), max_turns=12)
        if result.is_error or not isinstance(result.structured, dict):
            return {"approve": False, "problems": ["The review didn't complete, so it should run again."]}
        return result.structured

    async def build(self, feature_id, spec, phase=1):
        """Takes one feature from spec to released. Returns True if it reached players."""
        started = time.monotonic()
        tree = self._prepare_tree(feature_id)
        (tree / "mods/genesis/features" / feature_id).mkdir(parents=True, exist_ok=True)
        session = None
        feedback = None
        timings = {}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            reason = self.governor.why_not_build()
            if reason:
                print(f"{feature_id}: pausing: {reason}", flush=True)
                return False

            prompt = feedback or (f"Build this feature, with id `{feature_id}`, phase {phase}.\n\n"
                                  f"{llm.untrusted('spec', spec)}\n\nYour feature folder is mods/genesis/features/{feature_id}/.")
            began = time.monotonic()
            result = await llm.ask(self.governor, "builder", prompt, tools=BUILDER_TOOLS, allowed_tools=BUILDER_TOOLS,
                                   agents=SUBAGENTS, cwd=str(tree), max_turns=60, resume=session,
                                   mcp_servers={"broker": _tools_for(feature_id, tree)}, budget=8.0)
            timings[f"build_{attempt}"] = round(time.monotonic() - began, 1)
            session = result.session_id or session
            if result.is_error:
                print(f"{feature_id}: builder failed: {result.stop_reason} {result.text[:200]}", flush=True)
                self.governor.record_gate_result(False)
                continue

            commit = commit_all(f"{feature_id}: attempt {attempt}", cwd=tree)
            began = time.monotonic()
            gates = await request("gates", commit=commit, release_id=f"{feature_id}-{attempt}")
            timings[f"gates_{attempt}"] = round(time.monotonic() - began, 1)
            if gates.get("result") not in ("passed_gates", "nothing_to_release"):
                self.governor.record_gate_result(False)
                feedback = f"The automated gates stopped this at {gates.get('gate')}:\n{gates.get('reason')}\n\nFix it."
                print(f"{feature_id}: blocked at {gates.get('gate')}", flush=True)
                continue

            began = time.monotonic()
            verdict = await self._review(spec, feature_id, tree, gates.get("screenshots", []))
            timings[f"review_{attempt}"] = round(time.monotonic() - began, 1)
            if not verdict.get("approve"):
                self.governor.record_gate_result(False)
                feedback = "A reviewer found problems:\n- " + "\n- ".join(verdict.get("problems", [])) + "\n\nFix them."
                print(f"{feature_id}: review rejected it: {verdict.get('problems')}", flush=True)
                continue

            began = time.monotonic()
            released = await request("release", commit=commit, release_id=f"{feature_id}-{int(time.time())}")
            timings["release"] = round(time.monotonic() - began, 1)
            if released.get("result") not in ("released", "nothing_to_release"):
                self.governor.record_gate_result(False)
                feedback = f"Release failed at {released.get('gate')}: {released.get('reason')}\n\nFix it."
                print(f"{feature_id}: release failed: {released.get('reason')}", flush=True)
                continue

            self.governor.record_gate_result(True)
            _git("checkout", "-q", "main")
            _git("merge", "-q", "--no-ff", "-m", f"Released {feature_id}", f"feature/{feature_id}")
            timings["total"] = round(time.monotonic() - started, 1)
            self._log_timing(feature_id, timings, released)
            print(f"{feature_id}: released in {timings['total']}s: {timings}", flush=True)
            await self.on_released(feature_id, tree)
            return True
        print(f"{feature_id}: giving up after {MAX_ATTEMPTS} attempts", flush=True)
        return False

    @staticmethod
    def _log_timing(feature_id, timings, released):
        path = pathlib.Path("/workspace/state/features.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "feature": feature_id, "timings": timings,
                                     "tier": released.get("tier"), "broker_stages": released.get("stages")}) + "\n")
