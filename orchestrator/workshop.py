"""Builds one feature: a lead with parallel subagents, then review and gates side by side, then release.

The agent works in a git worktree, and only plain code commits, requests checks and asks for a release.
"""
import asyncio
import inspect
import json
import os
import pathlib
import subprocess
import time
import uuid

from claude_agent_sdk import AgentDefinition, create_sdk_mcp_server, tool

from orchestrator import llm, preview, research, templates, tuning, world_index

REPO = pathlib.Path("/workspace/repo")
PROGRESSION = "bible/progression.json"
TREES = pathlib.Path("/workspace/trees")
REQUESTS = pathlib.Path("/workspace/requests")
RESPONSES = pathlib.Path("/workspace/responses")
REPORTS = pathlib.Path("/workspace/reports")
REFERENCE_TEXTURES = pathlib.Path("/workspace/reference-textures")
FEATURE_RESEARCH = 4
TUNES_PER_HOUR = 6
REQUEST_TIMEOUT = {"lint": 300, "check": 300, "gates": 1800, "release": 1800, "javap": 300, "server_icon": 300, "set_rule": 300}  # Generous, because they queue behind whatever's running.
# Turns and usage for one attempt, and how many attempts. The later a stage is, the bigger its features can be, and
# nobody's waiting on them, because they're built in the background while people play.
STAGE_LIMITS = {"early": (60, 8.0, 3), "mid": (120, 16.0, 4), "end": (200, 30.0, 5)}
SMALL_LIMITS = (40, 3.0, 2)
SMALL_NOTE = ("This is a small change a player just asked for, and they're waiting for it. Do it yourself, quickly, with no subagents and no research, "
              "and change as little as you can. If it changes something players already have, say why in `changes_reached`.\n\n")

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"approve": {"type": "boolean"}, "serious": {"type": "boolean"},
                   "problems": {"type": "array", "items": {"type": "string"}}},
    "required": ["approve", "serious", "problems"],
}

SUBAGENTS = {
    "artist": AgentDefinition(
        description="Makes a feature's art with assetkit: textures, mob models and sounds. Give it the names and what each should be like.",
        prompt=("You make Minecraft art. Read assetkit/README.md and bible/theme.md. Write PNGs to the feature's assets/textures "
                "folder, .bbmodel files to assets/models and .ogg files to assets/sounds. Look at what you made by reading the "
                "contact sheet or the model preview, and fix anything muddy, noisy or flat. Textures are 16x16, with a small "
                "palette and soft contrast, and they should look at home next to vanilla blocks."),
        tools=["Read", "Write", "Edit", "Glob", "Bash", "mcp__broker__preview_feature", research.TOOL_NAME],
        model=llm.WORKER["model"],
        effort=llm.WORKER["effort"],
    ),
    "modeller": AgentDefinition(
        description=("Models one creature or machine in 3D from nothing, so it looks like itself and like nothing else. Give it what the thing "
                     "is and does, and the name to save it under. Start one per model, in parallel."),
        prompt=("You model creatures and machines for Minecraft. Read the Mobs section of assetkit/README.md. Write a Python script that builds "
                "your model with assetkit/sculpt.py, and keep it as assets/models/<name>.py beside the assets/models/<name>.bbmodel it saves. "
                "Nothing is premade: shape every part of this one thing, so it's unmistakably itself. Run the script, read the preview image, "
                "and fix what's wrong. Most models need several rounds, and the first is never the last. Judge it like this: could a stranger "
                "name it from its outline alone? Does its face have character? Do its proportions match what it's meant to be? Does it move "
                "with weight, the way it really would, rather than swinging like a pendulum? A creature needs idle, walk, hurt and death, plus "
                "attack if it fights, and a machine needs whatever it does at work. If it's based on something that exists, use the research tool for what it really "
                "looks like: colours, markings and proportions. Keep to about 5 to 12 parts, because each part is something players' computers "
                "have to draw. Reply with what you made, its name, and the width and height that sculpt.stats gives."),
        tools=["Read", "Write", "Edit", "Glob", "Bash", research.TOOL_NAME],
        model=llm.WORKER["model"],
        effort="medium",
    ),
    "coder": AgentDefinition(
        description="Writes a feature's Java modules. Give it the behaviour needed and the names in feature.json.",
        prompt=("You write Java modules for a Minecraft 26.3 mod. Read docs/feature-format.md and /reference for the API. Many "
                "Minecraft APIs were renamed recently, so check real signatures with the java_api tool. Keep tick work small, and "
                "use no files, network or threads. Keep state where the docs say, so it survives the module being swapped."),
        tools=["Read", "Write", "Edit", "Glob", "Grep", "mcp__broker__java_api", research.TOOL_NAME],
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
    (REPO / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    for name in ("docs", "assetkit"):
        target = REPO / name
        source = pathlib.Path("/reference") / name
        if source.exists():
            subprocess.run(["rsync", "-a", "--delete", f"{source}/", f"{target}/"], check=False)
    # Feature worktrees start from main, so anything they should see has to be committed there.
    commit_all("Reference material")


def _commit_staged(message, cwd):
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=cwd, check=False).returncode != 0:
        _git("commit", "-q", "-m", message, cwd=cwd)


def commit_all(message, cwd=REPO):
    _git("add", "-A", cwd=cwd)
    _commit_staged(message, cwd)
    return _git("rev-parse", "HEAD", cwd=cwd)


def _stamp_node(tree, feature_id, node):
    """A feature's place in the progression comes from the director, so it can't drift while it's being built."""
    path = tree / "mods/genesis/features" / feature_id / "feature.json"
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return  # The checks will say what's wrong with it, in a way a builder can act on.
        if manifest.get("node") != node:
            manifest["node"] = node
            path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")


def ready_commit(message, tree, feature_id=None, node=None):
    """Commits the work on top of whatever has shipped since it began. Without those, releasing it would look like
    removing them, so the broker would refuse. Features live in their own folders, so this doesn't normally conflict."""
    if feature_id:
        _stamp_node(tree, feature_id, node)
        # A feature is its own folder and nothing else. Whatever a builder left elsewhere can only collide with other features.
        _git("add", "-A", "--", f"mods/genesis/features/{feature_id}", cwd=tree)
        _commit_staged(message, tree)
        _git("checkout", "--", ".", cwd=tree)
    else:
        commit_all(message, cwd=tree)
    try:
        _git("merge", "-q", "--no-edit", "main", cwd=tree)
    except subprocess.CalledProcessError:
        subprocess.run(["git", "merge", "--abort"], cwd=tree, check=False)
        raise
    # The gates hold a feature to the world's progression, so it has to be the real one and not an edited copy.
    if (REPO / PROGRESSION).exists():
        _git("checkout", "main", "--", PROGRESSION, cwd=tree)
        commit_all("Keep the world's progression", cwd=tree)
    return _git("rev-parse", "HEAD", cwd=tree)


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


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _verdict(answer, passed):
    if answer.get("result") not in passed:
        return f"Failed at {answer.get('gate')}: {answer.get('reason')}"
    notes = answer.get("advice") or []
    return "All checks passed." + ("\n\nWorth another look, though these won't stop it:\n- " + "\n- ".join(notes) if notes else "")


def _template_tool(name, function, folder):
    """Offers a template as a tool, taking its parameters from the function so the two can't disagree."""
    parameters = [parameter for parameter in inspect.signature(function).parameters.values() if parameter.name != "folder"]
    schema = {"type": "object", "properties": {parameter.name: {} for parameter in parameters},
              "required": [parameter.name for parameter in parameters if parameter.default is inspect.Parameter.empty]}
    description = f"{inspect.cleandoc(function.__doc__ or name)}\nParameters: {inspect.signature(function)}"

    @tool(name, description, schema)
    async def run_template(args):
        print(f"{folder.name}: used {name}", flush=True)
        try:
            return _text(json.dumps(function(folder, **args)))
        except (templates.TemplateError, TypeError, ValueError) as error:
            return _text(f"That didn't work: {error}")

    return run_template


def _tools_for(feature_id, tree, node):
    folder = tree / "mods/genesis/features" / feature_id

    @tool("lint_feature", "Instantly checks this feature against the release rules, with no compile, and gives advice. Use it as often as you like.", {})
    async def lint_feature(args):
        print(f"{feature_id}: used lint_feature", flush=True)
        commit = ready_commit(f"{feature_id}: work in progress", tree, feature_id, node)
        return _text(_verdict(await request("lint", commit=commit), ("passed_lint",)))

    @tool("check_feature", "Compiles this feature and runs the static checks. Takes about 10 seconds.", {})
    async def check_feature(args):
        commit = ready_commit(f"{feature_id}: work in progress", tree, feature_id, node)
        return _text(_verdict(await request("check", commit=commit), ("passed_gates", "nothing_to_release")))

    @tool("preview_feature", "Draws this feature's art beside vanilla's in about a second, and says where the picture is, so read it with Read.", {})
    async def preview_feature(args):
        print(f"{feature_id}: used preview_feature", flush=True)
        out = REPORTS / f"preview-{feature_id}.png"
        result = await asyncio.to_thread(preview.render, folder, out, REFERENCE_TEXTURES)
        notes = "".join(f"\n- {note}" for note in result["notes"])
        return _text(f"Read {result['path']} to see it.{notes}")

    @tool("java_api", "Shows the real public methods and fields of a Minecraft or Fabric class. Pass the full class name.",
          {"class_name": str})
    async def java_api(args):
        answer = await request("javap", class_name=args["class_name"])
        return _text(answer.get("output") or answer.get("reason", "Not found."))

    made = [_template_tool(name, function, folder) for name, function in templates.TEMPLATES.items()]
    return create_sdk_mcp_server("broker", tools=[lint_feature, check_feature, preview_feature, java_api, *made])


BUILDER_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Agent", "Task", "mcp__broker__lint_feature",
                 "mcp__broker__check_feature", "mcp__broker__preview_feature", "mcp__broker__java_api",
                 "mcp__world__world_index", research.TOOL_NAME, *(f"mcp__broker__{name}" for name in templates.TEMPLATES)]
# Only Bash runs in the sandbox, so file tools need their own limits on where secrets could be found. Builders can run
# things and write code, so they never read a web page themselves: they ask the research tool.
SMALL_TOOLS = [name for name in BUILDER_TOOLS if name not in ("Agent", "Task", research.TOOL_NAME)]
BUILDER_DENIED = ["Read(//proc/**)", "Read(//run/**)", "Read(//home/agent/.claude/**)", "Read(//workspace/state/**)",
                  "Grep(//proc/**)", "Grep(//run/**)", "Grep(//workspace/state/**)",
                  "Glob(//workspace/state/**)", "WebFetch", "WebSearch"]


class Workshop:
    def __init__(self, governor, on_released, web_research, reached=lambda: ()):
        self.governor = governor
        self.on_released = on_released
        self.web_research = web_research
        self.reached = reached  # The names of what players already have.
        self.tune_times = []
        self.changes = 0  # So that plain code can tell whether something really was changed, whatever a model says.
        self.release_lock = asyncio.Lock()

    def world_server(self, can_tune=False):
        """What the director, builders and tuner can ask about the world, and for the tuner, change."""
        @tool("world_index", "Lists everything built so far with its numbers, by where it sits in the progression, marking what players already have.", {})
        async def index(args):
            return _text(world_index.build(REPO / "mods/genesis/features", self.reached()))

        schema = {"type": "object", "required": ["feature", "table", "name", "field", "value", "reason"], "properties": {
            "feature": {"type": "string"}, "table": {"type": "string", "enum": ["items", "blocks", "mobs", "recipes", "ores", "plants"]},
            "name": {"type": "string"}, "field": {"type": "string"}, "value": {}, "reason": {"type": "string"}}}

        @tool("tune", ("Changes one number in something already released, and it reaches players in under a minute. Fields: "
                       f"items {sorted(tuning.ITEM_FIELDS)}, mobs {sorted(tuning.MOB_FIELDS)}, blocks {sorted(tuning.BLOCK_FIELDS)}, "
                       f"recipes {sorted(tuning.RECIPE_FIELDS)}, ores veinsPerChunk, plants perChunk. A drops.count is [lowest, highest]. "
                       "For ores and plants, name is the entry's id and the value can only go up."), schema)
        async def tune(args):
            return _text(await self.tune(args["feature"], args["table"], args["name"], args["field"], args["value"], args["reason"]))

        @tool("set_rule", ("Changes a server rule for everyone, straight away. Rules: players_sleeping_percentage (0 to 100, how many players must "
                           "sleep to skip the night), spawn_phantoms (true or false), keep_inventory (true or false)."),
              {"type": "object", "required": ["rule", "value", "reason"], "properties": {"rule": {"type": "string"}, "value": {}, "reason": {"type": "string"}}})
        async def set_rule(args):
            return _text(await self.set_rule(args["rule"], args["value"], args["reason"]))

        return create_sdk_mcp_server("world", tools=[index, *([tune, set_rule] if can_tune else [])])

    async def set_rule(self, rule, value, reason):
        blocked = self.governor.why_not_build()
        if blocked:
            return f"Not now: {blocked}."
        answer = await request("set_rule", rule=rule, value=value)
        if answer.get("result") != "set":
            return f"Refused: {answer.get('reason')}"
        self.changes += 1
        with pathlib.Path("/workspace/state/tunes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "rule": rule, "value": value, "reason": reason}) + "\n")
        print(f"set the rule {rule} to {value}", flush=True)
        return "Done: it's live."

    async def tune(self, feature_id, table, name, field, value, reason):
        """Plain code makes the change on its own branch, and the normal gates decide whether it goes out."""
        now = time.time()
        self.tune_times = [stamp for stamp in self.tune_times if now - stamp < 3600]
        blocked = self.governor.why_not_build()
        if blocked or len(self.tune_times) >= TUNES_PER_HOUR:
            return f"Not now: {blocked or 'that is enough changes for one hour'}."
        path = REPO / "mods/genesis/features" / feature_id / "feature.json"
        if not path.exists():
            return f"There's no released feature called {feature_id}."
        started = time.monotonic()
        branch = f"tune-{uuid.uuid4().hex[:8]}"
        tree = TREES / branch
        TREES.mkdir(parents=True, exist_ok=True)
        _git("worktree", "add", "-q", "-b", branch, str(tree), "main")
        try:
            target = tree / "mods/genesis/features" / feature_id / "feature.json"
            manifest = json.loads(target.read_text(encoding="utf-8"))
            try:
                tuning.apply(manifest, table, name, field, value, reason)
            except tuning.TuneError as error:
                return str(error)
            target.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
            async with self.release_lock:
                commit = ready_commit(f"{feature_id}: {name} {field} to {value}", tree)
                answer = await request("release", commit=commit, release_id=f"{branch}-{int(now)}")
                if answer.get("result") not in ("released", "nothing_to_release"):
                    return f"Refused at {answer.get('gate')}: {answer.get('reason')}"
                _git("checkout", "-q", "main")
                _git("merge", "-q", "--no-ff", "-m", f"Tuned {feature_id}: {reason[:80]}", branch)
            self.tune_times.append(now)
            self.changes += 1
            seconds = round(time.monotonic() - started, 1)
            with pathlib.Path("/workspace/state/tunes.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": now, "feature": feature_id, "name": name, "field": field, "value": value,
                                         "reason": reason, "seconds": seconds}) + "\n")
            print(f"tuned {feature_id}/{name} {field} to {value} in {seconds}s", flush=True)
            return f"Done: it's live, {seconds} seconds after you asked."
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO, check=False, capture_output=True)
            subprocess.run(["git", "branch", "-D", branch], cwd=REPO, check=False, capture_output=True)

    def _prepare_tree(self, feature_id):
        tree = TREES / feature_id
        if not tree.exists():
            TREES.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "worktree", "prune"], cwd=REPO, check=False)
            _git("worktree", "add", "-q", "-B", f"feature/{feature_id}", str(tree), "main")
        # It's been here before, for a released feature that's changing or a build a restart interrupted, so catch up.
        elif subprocess.run(["git", "merge", "-q", "--no-edit", "main"], cwd=tree, check=False, capture_output=True).returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=tree, check=False, capture_output=True)
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

    async def build(self, feature_id, spec, node, stage, small=False):
        """Takes one feature from spec to released. Returns True if it reached players, False if it couldn't be done,
        and None if it had to stop for now and should be picked up again later."""
        started = time.monotonic()
        tree = self._prepare_tree(feature_id)
        (tree / "mods/genesis/features" / feature_id).mkdir(parents=True, exist_ok=True)
        session = None
        feedback = None
        last_problem = ""
        timings = {}
        web = self.web_research.server(FEATURE_RESEARCH)
        max_turns, usage, attempts = SMALL_LIMITS if small else STAGE_LIMITS[stage]
        tools = SMALL_TOOLS if small else BUILDER_TOOLS
        for attempt in range(1, attempts + 1):
            reason = self.governor.why_not_build()
            if reason:
                print(f"{feature_id}: pausing: {reason}", flush=True)
                return None

            prompt = feedback or ((SMALL_NOTE if small else "") + f"Build this feature, with id `{feature_id}`, in node `{node}`, which is in the {stage} game. Its place "
                                  f"in the world is in bible/progression.json.\n\n{llm.untrusted('spec', spec)}\n\n"
                                  f"Your feature folder is mods/genesis/features/{feature_id}/.")
            began = time.monotonic()
            result = await llm.ask(self.governor, "small_builder" if small else "builder", prompt, system=llm.prompt_text("builder"), tools=tools, allowed_tools=tools,
                                   disallowed_tools=BUILDER_DENIED, agents=None if small else SUBAGENTS, cwd=str(tree), max_turns=max_turns, resume=session,
                                   mcp_servers={"broker": _tools_for(feature_id, tree, node), "web": web, "world": self.world_server()},
                                   budget=usage)
            timings[f"build_{attempt}"] = round(time.monotonic() - began, 1)
            session = result.session_id or session
            if result.is_error:
                print(f"{feature_id}: builder failed: {result.stop_reason} {result.text[:200]}", flush=True)
                self.governor.record_gate_result(False)
                last_problem = f"The builder stopped: {result.stop_reason}"
                continue

            commit = ready_commit(f"{feature_id}: attempt {attempt}", tree, feature_id, node)
            began = time.monotonic()
            gates = await request("gates", commit=commit, release_id=f"{feature_id}-{attempt}", hurry=small)
            timings[f"gates_{attempt}"] = round(time.monotonic() - began, 1)
            if gates.get("result") not in ("passed_gates", "nothing_to_release"):
                self.governor.record_gate_result(False)
                feedback = f"The automated gates stopped this at {gates.get('gate')}:\n{gates.get('reason')}\n\nFix it."
                last_problem = f"Gate {gates.get('gate')}: {str(gates.get('reason'))[:300]}"
                print(f"{feature_id}: blocked at {gates.get('gate')}", flush=True)
                continue

            began = time.monotonic()
            verdict = await self._review(spec, feature_id, tree, gates.get("screenshots", []))
            timings[f"review_{attempt}"] = round(time.monotonic() - began, 1)
            if not verdict.get("approve"):
                # Not a failure of the machinery, so this doesn't count towards the breaker. Every automated gate has
                # passed, so on the last try anything short of harmful ships: something real today beats perfect later.
                print(f"{feature_id}: review rejected it: {verdict.get('problems')}", flush=True)
                last_problem = "Review: " + "; ".join(verdict.get("problems", []))[:300]
                if verdict.get("serious", True) or attempt < attempts:
                    feedback = "A reviewer found problems:\n- " + "\n- ".join(verdict.get("problems", [])) + "\n\nFix them."
                    continue
                print(f"{feature_id}: shipping anyway: the problems aren't serious and the gates passed", flush=True)

            began = time.monotonic()
            # One at a time, from the commit that's merged with everything already out. Without this, a release that's
            # waiting its turn would look like removing whatever the one ahead of it just shipped.
            async with self.release_lock:
                commit = ready_commit(f"{feature_id}: ready to release", tree, feature_id, node)
                released = await request("release", commit=commit, release_id=f"{feature_id}-{int(time.time())}")
                went_out = released.get("result") in ("released", "nothing_to_release")
                if went_out:
                    _git("checkout", "-q", "main")
                    _git("merge", "-q", "--no-ff", "-m", f"Released {feature_id}", f"feature/{feature_id}")
            timings["release"] = round(time.monotonic() - began, 1)
            if not went_out:
                self.governor.record_gate_result(False)
                feedback = f"Release failed at {released.get('gate')}: {released.get('reason')}\n\nFix it."
                last_problem = f"Release: {str(released.get('reason'))[:300]}"
                print(f"{feature_id}: release failed: {released.get('reason')}", flush=True)
                continue

            self.governor.record_gate_result(True)
            timings["total"] = round(time.monotonic() - started, 1)
            self._log_timing(feature_id, timings, released)
            print(f"{feature_id}: released in {timings['total']}s: {timings}", flush=True)
            await self.on_released(feature_id, tree)
            return True
        print(f"{feature_id}: giving up after {attempts} attempts", flush=True)
        # So the director knows, instead of asking for the same thing in the same way.
        with pathlib.Path("/workspace/state/unfinished.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "feature": feature_id, "problem": last_problem}) + "\n")
        return False

    @staticmethod
    def _log_timing(feature_id, timings, released):
        path = pathlib.Path("/workspace/state/features.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "feature": feature_id, "timings": timings,
                                     "tier": released.get("tier"), "broker_stages": released.get("stages")}) + "\n")
