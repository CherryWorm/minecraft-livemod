"""Builds one feature: a lead with parallel subagents, then review and gates side by side, then release.

The agent works in a git worktree, and only plain code commits, requests checks and asks for a release.
"""
import asyncio
import dataclasses
import hashlib
import inspect
import json
import os
import pathlib
import subprocess
import time
import uuid

from claude_agent_sdk import AgentDefinition, create_sdk_mcp_server, tool

from orchestrator import feedback, lanes, llm, others, preview, research, templates, translation, tuning, wording, world_index

REPO = pathlib.Path("/workspace/repo")
PROGRESSION = "bible/progression.json"
FEATURES = "mods/genesis/features"
TREES = pathlib.Path("/workspace/trees")
REQUESTS = pathlib.Path("/workspace/requests")
RESPONSES = pathlib.Path("/workspace/responses")
REPORTS = pathlib.Path("/workspace/reports")
REFERENCE_TEXTURES = pathlib.Path("/workspace/reference-textures")
FEATURE_RESEARCH = 4
TUNES_PER_HOUR = 6
REQUEST_TIMEOUT = {"lint": 300, "check": 300, "gates": 1800, "release": 1800, "javap": 300, "server_icon": 300, "set_rule": 300, "server_errors": 300}  # Generous, because they queue behind whatever's running.
KEEP_ASKING = ("gates", "release")  # A broker that's down or far behind isn't something a builder can fix, so these wait for it, which costs nothing.
RELEASE_TREE = TREES / "_release"
RELEASE_BRANCH = "release/next"
WENT_OUT = ("released", "nothing_to_release")
MOST_IN_A_RELEASE = 8  # Finding a bad one takes longer the more there are. Anything over this goes in the next release, straight after.
# Turns and usage for one attempt, and how many attempts. A feature is everything that has to arrive together, so these leave
# room for that, and most use far less. The later a stage is, the bigger its features can be, and
# nobody's waiting on them, because they're built in the background while people play. There's no limit on turns (the owner's
# call), because running out threw away the whole build. Usage only limits builders on Claude, so nothing limits one on another model.
STAGE_LIMITS = {"early": (None, 14.0, 3), "mid": (None, 24.0, 4), "end": (None, 40.0, 5)}
SMALL_LIMITS = (None, 3.0, 2)
FIX_LIMITS = (None, 6.0, 3)
FEATURE_ID = others.FEATURE_ID
STALE = "is in the ledger but no feature declares it"
STALE_RETRIES = 4
CONFLICT_MARKS = r"^(<<<<<<<|>>>>>>>) "
MOST_CONFLICTS = 3  # Two builders changing the same lines is nobody's mistake, so it doesn't use up a try, but it can't go on forever.
MOST_DIFF_SHOWN = 8000  # What a reviewer reads of a change to another feature. The rest is in its folder.
SMALL_NOTE = ("This is a small change a player just asked for, and they're waiting for it. Do it yourself, quickly, with no subagents and no research, "
              "and change as little as you can. If it changes something players already have, say why in `changes_reached`. If part of it belongs in another "
              "feature, change it there and say why in `changes_features`.\n\n")

FIX_NOTE = ("This is a bug a player reported in something that's already out, and it's being fixed ahead of everything else. Someone who looked into it wrote the "
            "brief below, so check it against the code, fix the cause and change nothing else: what it otherwise does, its art, names, recipes and balance all stay as "
            "they are. Do it yourself, with no subagents and no research, and say what changed in `changes_reached`. If the cause or part of the fix is in another "
            "feature, change it there and say why in `changes_features`.\n\n")

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
                "use no files, network or threads. Keep state where the docs say, so it survives the module being swapped. "
                "Write a mixin only if the builder asks for one, following the Mixins section of the docs."),
        tools=["Read", "Write", "Edit", "Glob", "Grep", "mcp__broker__java_api", research.TOOL_NAME],
        model=llm.WORKER["model"],
        effort=llm.WORKER["effort"],
    ),
}

# Art is made by Opus, whatever model a builder runs on. A subagent always runs on its builder's model, so on any other model
# these become a tool, and each runs as a session of its own on Claude.
ART_KINDS = ("artist", "modeller")
ART_TOOL = "mcp__art__make_art"
ART_TURNS = 60
ART_USAGE = 6.0
ART_MADE = pathlib.Path("/workspace/state/art_made.json")
ART_SCHEMA = {"type": "object", "required": ["jobs"], "properties": {"jobs": {"type": "array", "items": {
    "type": "object", "required": ["kind", "brief"], "properties": {"kind": {"type": "string", "enum": list(ART_KINDS)}, "brief": {"type": "string"}}}}}}
ART_NOTE = ("Claude Opus makes all of this world's art, so you don't: textures, sounds, models, panel images and shaders all come from the `make_art` tool. Ignore what "
            "follows about `artist` and `modeller` subagents, and instead give `make_art` one job for each piece of work, all in one call, so they run at the same time: "
            "`artist` for textures and sounds, and `modeller` for each creature or model block, with what the thing is and does and the name to save it under. Use the names "
            "and sizes they give back. Anything you draw or generate yourself, including what a template leaves behind, gets redone by Opus before testing, so only write "
            "feature.json, data and code yourself. The artists check how it looks, so you don't need to.\n\n")


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


class Refused(Exception):
    """Work that can't go further as it is, saying what to do about it. Nothing has broken, so it goes back to the builder like any gate's answer."""

    def __init__(self, gate, reason):
        super().__init__(reason)
        self.gate = gate
        self.reason = reason

    def answer(self):
        return {"result": "blocked", "gate": self.gate, "reason": self.reason}


def _differs(tree, commit):
    """Which features' folders aren't as they were at a commit, counting new files git hasn't been told about."""
    listed = (_git("diff", "--name-only", "--no-renames", "-z", commit, "--", FEATURES, cwd=tree) + "\0"
              + _git("ls-files", "--others", "--exclude-standard", "-z", "--", FEATURES, cwd=tree))
    return {path.split("/")[3] for path in listed.split("\0") if path.count("/") > 3}


def _on_main(feature, tree):
    return subprocess.run(["git", "cat-file", "-e", f"main:{FEATURES}/{feature}/feature.json"], cwd=tree, check=False, capture_output=True).returncode == 0


def _scope(tree, feature_id):
    """Which feature folders are this builder's to commit, and which it's changed without saying so. A feature that isn't out can't be
    listed, because that would be starting one nobody asked for. If its feature.json can't be read there's no telling, so the second is None."""
    manifest = tree / FEATURES / feature_id / "feature.json"
    declared = others.declared(manifest.read_text(encoding="utf-8")) if manifest.exists() else set()
    if declared is None:
        return {feature_id}, None
    declared = {name for name in declared if _on_main(name, tree)} | {feature_id}
    strays = _differs(tree, _git("merge-base", "main", "HEAD", cwd=tree)) - declared
    # A folder that's been put back how it was is in here as well, because committing that is what undoes an earlier commit.
    return (declared | _differs(tree, "HEAD")) - strays, strays


def _marked(tree, paths):
    """Which of these have a conflict's marker lines in them. It's only ever asked about what a builder's working on, so something odd elsewhere can't hold everyone up."""
    if not paths:
        return []
    found = subprocess.run(["git", "grep", "-lIE", "-z", CONFLICT_MARKS, "--", *paths], cwd=tree, check=False, capture_output=True, text=True)
    return sorted(path for path in found.stdout.split("\0") if path)


def _conflict(tree, feature_id, error):
    """Something that's gone out changes the same lines as this work. So that nobody's work is lost and this one doesn't have to start again, the merge
    is committed with both versions in the files, for its builder to settle. The markers can't go any further, because ready_commit stops at them."""
    conflicted = [path for path in _git("diff", "--name-only", "--diff-filter=U", "-z", cwd=tree).split("\0") if path]
    if not feature_id or not conflicted:
        subprocess.run(["git", "merge", "--abort"], cwd=tree, check=False, capture_output=True)
        return Refused("merge", f"This can't be brought up to date with what's gone out: {error.stderr or error}")
    yours = _git("rev-parse", "HEAD", cwd=tree)
    marked = _marked(tree, conflicted)
    replaced = [path for path in conflicted if path not in marked]
    for path in replaced:
        if subprocess.run(["git", "cat-file", "-e", f"main:{path}"], cwd=tree, check=False, capture_output=True).returncode == 0:
            _git("checkout", "main", "--", path, cwd=tree)
        else:
            _git("rm", "-qf", "--", path, cwd=tree)
    if marked:
        _git("add", "--", *marked, cwd=tree)
    _git("commit", "-q", "--no-edit", cwd=tree)
    reason = "Something that's gone out since you started changes the same things as your work, so they can't both stand as they are. Everything else has been brought up to date."
    if marked:
        reason += (f"\n\nThese have both versions in them now, between lines starting <<<<<<< and >>>>>>>, with yours first and what's out second: {', '.join(marked)}. "
                   "Keep what both need, take out those lines and the ======= between them, and check again.")
    if replaced:
        reason += (f"\n\nThese can't show both, because they're art or one side removed them, so they're as they are in what's out: {', '.join(replaced)}. "
                   f"If you still need yours, it's in `git show {yours}:<path>`.")
    return Refused("merge", reason)


def ready_commit(message, tree, feature_id=None, node=None):
    """Commits the work on top of whatever has shipped since it began. Without those, releasing it would look like removing
    them, so the broker would refuse. Most features stay in their own folders, so this doesn't normally conflict, and when
    it does, that's a refusal the builder can act on. Raises Refused for anything that has to go back to the builder."""
    if feature_id:
        _stamp_node(tree, feature_id, node)
        folders, strays = _scope(tree, feature_id)
        # A feature is its own folder and the ones it says it changes. Whatever a builder left elsewhere can only collide with other features.
        paths = [path for path in (f"{FEATURES}/{folder}" for folder in sorted(folders)) if (tree / path).exists() or _git("ls-files", "--", path, cwd=tree)]
        if paths:
            _git("add", "-A", "--", *paths, cwd=tree)
        _commit_staged(message, tree)
        if strays:
            names = sorted(strays)
            raise Refused("scope", f"You've changed {', '.join(names)} without saying so. If that's on purpose, list each in feature.json, like \"changes_features\": "
                                   f"{{\"{names[0]}\": \"why\"}}. Only a feature that's out can be listed, so anything new goes in your own folder. "
                                   "If it isn't on purpose, put it back as it was. Nothing has been thrown away.")
        if strays is not None:
            _git("checkout", "--", ".", cwd=tree)
        unsettled = _marked(tree, paths)
        if unsettled:
            raise Refused("merge", f"These still have a conflict's marker lines in them, so settle them first: {', '.join(unsettled)}.")
    else:
        commit_all(message, cwd=tree)
    try:
        _git("merge", "-q", "--no-edit", "main", cwd=tree)
    except subprocess.CalledProcessError as error:
        raise _conflict(tree, feature_id, error) from error
    # The gates hold a feature to the world's progression, so it has to be the real one and not an edited copy.
    if (REPO / PROGRESSION).exists():
        _git("checkout", "main", "--", PROGRESSION, cwd=tree)
        commit_all("Keep the world's progression", cwd=tree)
    return _git("rev-parse", "HEAD", cwd=tree)


def changes_to_others(tree, feature_id):
    """What this work really does to other features, beside what its builder says about that, for whoever's judging it."""
    listed = _git("diff", "--name-only", "--no-renames", "-z", "main...HEAD", "--", FEATURES, cwd=tree).split("\0")
    changed = sorted({path.split("/")[3] for path in listed if path.count("/") > 3} - {feature_id})
    own = f"{FEATURES}/{feature_id}/feature.json"
    manifest = (others.read_manifest((tree / own).read_text(encoding="utf-8")) if (tree / own).exists() else None) or {}
    shipped = subprocess.run(["git", "show", f"main:{own}"], cwd=tree, check=False, capture_output=True, text=True, errors="replace")
    before = (others.read_manifest(shipped.stdout) if shipped.returncode == 0 else None) or {}
    said = manifest.get("changes_features") or {}
    added = {target: places for target, places in (manifest.get("adds_to") or {}).items() if (before.get("adds_to") or {}).get(target) != places}
    parts = [f"It changes {target}, because: {said.get(target, '(no reason given)')}" for target in changed]
    parts += [f"It adds to {target} from its own folder: {json.dumps(places)}" for target, places in added.items()]
    if changed:
        folders = [f"{FEATURES}/{target}" for target in changed]
        diff = subprocess.run(["git", "diff", "--no-color", "main...HEAD", "--", *folders], cwd=tree, check=False, capture_output=True, text=True, errors="replace").stdout
        parts.append(diff[:MOST_DIFF_SHOWN] + ("\n(That's all that's shown here. The rest is in the folder.)" if len(diff) > MOST_DIFF_SHOWN else ""))
    return "\n\n".join(parts)


async def checked_against_main(kind, message, tree, feature_id, node, ask=None, **fields):
    """Something else can ship while this waits its turn, and then this looks like it's removing that. Nobody's made a
    mistake, so it catches up and asks again, rather than sending a builder off to fix something that isn't wrong."""
    for _ in range(STALE_RETRIES):
        try:
            commit = ready_commit(message, tree, feature_id, node)
        except Refused as refused:
            return refused.answer()
        answer = await (ask or request)(kind, commit=commit, **fields)
        if STALE not in str(answer.get("reason")):
            break
        await asyncio.sleep(10)
    return answer


async def request(kind, **fields):
    """Asks the broker, which runs outside this container, and waits for its answer."""
    REQUESTS.mkdir(parents=True, exist_ok=True)
    while True:
        request_id = uuid.uuid4().hex[:12]
        temporary = REQUESTS / f".{request_id}.tmp"
        temporary.write_text(json.dumps({"id": request_id, "kind": kind, **fields}), encoding="utf-8")
        temporary.rename(REQUESTS / f"{request_id}.json")
        answer = RESPONSES / f"{request_id}.json"
        deadline = time.monotonic() + REQUEST_TIMEOUT[kind]
        while time.monotonic() < deadline:
            if answer.exists():
                return json.loads(answer.read_text(encoding="utf-8"))
            await asyncio.sleep(0.5)
        # Nobody's waiting for it now, so it mustn't run later, and a release mustn't go out by surprise. If that release
        # had already started, asking again finds it's out, because there's then nothing left to release.
        (REQUESTS / f"{request_id}.json").unlink(missing_ok=True)
        print(f"the broker didn't answer a {kind} request in time", flush=True)
        if kind not in KEEP_ASKING:
            return {"result": "blocked", "gate": "broker", "reason": f"The broker didn't answer a {kind} request in time."}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _verdict(answer, passed, feature_id=None):
    if answer.get("result") not in passed:
        return f"Failed at {answer.get('gate')}: {answer.get('reason')}"
    # Older modules have words in their code too, and those aren't this builder's to change.
    notes = [note for note in answer.get("advice") or [] if wording.TEXT_IN_CODE not in note or note.startswith(f"{feature_id}'s ")]
    notes = [*notes, *(f"{feature_id}'s mixins are left out of every release until they change, because {why}."
                       for feature_id, why in (answer.get("withheld_mixins") or {}).items())]
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


def _tools_for(feature_id, tree, node, ask=None):
    folder = tree / "mods/genesis/features" / feature_id
    ask = ask or request

    @tool("lint_feature", "Instantly checks this feature against the release rules, with no compile, and gives advice. Use it as often as you like.", {})
    async def lint_feature(args):
        print(f"{feature_id}: used lint_feature", flush=True)
        return _text(_verdict(await checked_against_main("lint", f"{feature_id}: work in progress", tree, feature_id, node, ask=ask), ("passed_lint",), feature_id))

    @tool("check_feature", "Compiles this feature and runs the static checks. Takes about 10 seconds.", {})
    async def check_feature(args):
        return _text(_verdict(await checked_against_main("check", f"{feature_id}: work in progress", tree, feature_id, node, ask=ask), ("passed_gates", "nothing_to_release"), feature_id))

    @tool("preview_feature", "Draws this feature's art beside vanilla's in about a second, and says where the picture is, so read it with Read.", {})
    async def preview_feature(args):
        print(f"{feature_id}: used preview_feature", flush=True)
        out = REPORTS / f"preview-{feature_id}.png"
        result = await asyncio.to_thread(preview.render, folder, out, REFERENCE_TEXTURES)
        notes = "".join(f"\n- {note}" for note in result["notes"])
        return _text(f"Read {result['path']} to see it.{notes}")

    @tool("java_api", "Shows the real public methods and fields of a Minecraft or Fabric class. Pass the full class name. For writing a mixin, private: true "
                      "adds what's private, and code: \"methodName\" shows one method's bytecode, which is what an injection point has to match.",
          {"type": "object", "properties": {"class_name": {"type": "string"}, "private": {"type": "boolean"}, "code": {"type": "string"}}, "required": ["class_name"]})
    async def java_api(args):
        answer = await ask("javap", class_name=args["class_name"], private=args.get("private", False), code=args.get("code", ""))
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


def _art_in(folder):
    """Every piece of art in a feature's folder, with the hash git would give it, so it can be compared with what's shipped."""
    return {path.relative_to(folder).as_posix(): hashlib.sha1(b"blob %d\0" % path.stat().st_size + path.read_bytes(), usedforsecurity=False).hexdigest()
            for path in sorted((folder / "assets").rglob("*")) if path.is_file() and path.name != "lang.json"}


def _shipped_art(tree, feature_id):
    prefix = f"mods/genesis/features/{feature_id}/"
    lines = _git("ls-tree", "-r", "main", "--", f"{prefix}assets", cwd=tree).splitlines()
    return {line.split("\t")[1].removeprefix(prefix): line.split()[2] for line in lines}


@dataclasses.dataclass
class Ready:
    """A feature that's passed everything, waiting to go out."""
    feature_id: str
    tree: pathlib.Path
    node: str
    answer: asyncio.Future
    about: str = ""
    branch: str = ""


class Workshop:
    def __init__(self, governor, on_released, web_research, reached=lambda: ()):
        self.governor = governor
        self.on_released = on_released
        self.web_research = web_research
        self.reached = reached  # The names of what players already have.
        self.tune_times = []
        self.changes = 0  # So that plain code can tell whether something really was changed, whatever a model says.
        self.release_lock = asyncio.Lock()
        self.lanes = {}  # Models other than Claude that a builder can run on, by name.
        self.hub = None  # Other machines that can do a builder's work.
        self.ready = []  # What's passed everything and is waiting for the next release.
        self.releasing = None
        self.art_made = json.loads(ART_MADE.read_text(encoding="utf-8")) if ART_MADE.exists() else {}  # What Opus made, by feature and file.
        self.translator = translation.Translator(governor, REPO, commit_all)

    # Releases -----------------------------------------------------------------------------------------------

    async def _release(self, feature_id, tree, node, about="", fix=None):
        """Waits for the next release, which takes everything that's ready by then. A release costs about the same whatever's in it,
        and players get more at once. Returns what the broker said about the release that this feature's fate was settled in.
        A bug fix goes in the next one whatever else is waiting, so it's first in line for it."""
        ready = Ready(feature_id, tree, node, asyncio.get_running_loop().create_future(), about, f"fix/{fix}" if fix else f"feature/{feature_id}")
        self.ready.insert(sum(item.branch.startswith("fix/") for item in self.ready) if fix else len(self.ready), ready)
        if self.releasing is None or self.releasing.done():
            self.releasing = asyncio.create_task(self._run_releases())
        return await ready.answer

    async def _run_releases(self):
        while self.ready:
            batch, self.ready = self.ready[:MOST_IN_A_RELEASE], self.ready[MOST_IN_A_RELEASE:]
            await self._ship(batch)

    async def _ship(self, batch):
        """If a release of several fails, each half goes on its own, so one bad feature can't hold back the others, and
        it's that one that gets told. They've each passed the gates alone, so this is rare."""
        try:
            batch, answer = await self._release_together(batch)
        except Exception as error:  # noqa: BLE001 - everyone waiting has to hear, whatever went wrong
            answer = {"result": "blocked", "gate": "release", "reason": f"{type(error).__name__}: {error}"}
        if not batch:
            return
        if answer.get("result") in WENT_OUT or len(batch) == 1:
            for ready in batch:
                ready.answer.set_result(answer)
            return
        print(f"a release of {len(batch)} failed at {answer.get('gate')}, so trying them in smaller groups", flush=True)
        middle = len(batch) // 2
        await self._ship(batch[:middle])
        await self._ship(batch[middle:])

    async def _release_together(self, batch):
        """Asks for one release of all of them. Returns who was in it, because one that won't merge is told so and left out."""
        # One at a time, from a commit merged with everything already out. Without this, a release that's waiting
        # its turn would look like removing whatever the one ahead of it just shipped.
        async with self.release_lock:
            included = self._merge_into_release(batch)
            if not included:
                return [], {}
            names = ", ".join(ready.feature_id for ready in included)
            print(f"releasing together: {names}", flush=True)
            name = included[0].feature_id if len(included) == 1 else f"batch{len(included)}"
            answer = await request("release", commit=_git("rev-parse", "HEAD", cwd=RELEASE_TREE), release_id=f"{name}-{int(time.time())}",
                                   why=feedback.release_reason(ready.about for ready in included))
            if answer.get("result") in WENT_OUT:
                _git("checkout", "-q", "main")
                _git("merge", "-q", "--no-ff", "-m", f"Released {names}", RELEASE_BRANCH)
            return included, answer

    def _merge_into_release(self, batch):
        if not RELEASE_TREE.exists():
            TREES.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "worktree", "prune"], cwd=REPO, check=False)
            _git("worktree", "add", "-q", "-B", RELEASE_BRANCH, str(RELEASE_TREE), "main")
        _git("checkout", "-q", "-f", "-B", RELEASE_BRANCH, "main", cwd=RELEASE_TREE)
        included = []
        for ready in batch:
            try:
                ready_commit(f"{ready.feature_id}: ready to release", ready.tree, ready.feature_id, ready.node)
            except Refused as refused:
                ready.answer.set_result(refused.answer())
                continue
            except subprocess.CalledProcessError as error:
                ready.answer.set_result({"result": "blocked", "gate": "merge", "reason": f"This couldn't be got ready to go out: {error.stderr or error}"})
                continue
            try:
                _git("merge", "-q", "--no-edit", ready.branch, cwd=RELEASE_TREE)
                included.append(ready)
            except subprocess.CalledProcessError as error:
                subprocess.run(["git", "merge", "--abort"], cwd=RELEASE_TREE, check=False, capture_output=True)
                # It clashes with something ahead of it in this release, which may not go out. So it waits for the next one, and it's
                # measured against what really did, which either lets it through or shows its builder exactly what to settle.
                if included:
                    self.ready.insert(0, ready)
                else:
                    ready.answer.set_result({"result": "blocked", "gate": "merge", "reason": f"This couldn't be merged with what's out: {error.stderr or error}"})
        return included

    # Everything else ----------------------------------------------------------------------------------------

    def world_server(self, can_tune=False):
        """What the director, builders and tuner can ask about the world, and for the tuner, change."""
        @tool("world_index", "Lists everything built so far with its numbers, by where it sits in the progression, marking what players already have.", {})
        async def index(args):
            return _text(world_index.build(REPO / "mods/genesis/features", self.reached()))

        schema = {"type": "object", "required": ["feature", "table", "name", "field", "value", "reason"], "properties": {
            "feature": {"type": "string"}, "table": {"type": "string", "enum": ["items", "blocks", "mobs", "projectiles", "vehicles", "recipes", "ores", "plants"]},
            "name": {"type": "string"}, "field": {"type": "string"}, "value": {}, "reason": {"type": "string"}}}

        @tool("tune", ("Changes one number in something already released, and it reaches players in under a minute. Fields: "
                       f"items {sorted(tuning.ITEM_FIELDS)}, mobs {sorted(tuning.MOB_FIELDS)}, blocks {sorted(tuning.BLOCK_FIELDS)}, "
                       f"projectiles {sorted(tuning.PROJECTILE_FIELDS)}, vehicles {sorted(tuning.VEHICLE_FIELDS)}, "
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
                try:
                    commit = ready_commit(f"{feature_id}: {name} {field} to {value}", tree)
                except Refused as refused:
                    return f"Refused at {refused.gate}: {refused.reason}"
                answer = await request("release", commit=commit, release_id=f"{branch}-{int(now)}", why=feedback.balance_reason(table, field))
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

    def _prepare_tree(self, feature_id, fix=None):
        """A bug fix starts from what's out, in a folder and on a branch of its own, so it doesn't wait for or pick up whatever a builder is doing to the same feature."""
        tree = TREES / (fix or feature_id)
        if not tree.exists():
            TREES.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "worktree", "prune"], cwd=REPO, check=False)
            _git("worktree", "add", "-q", "-B", f"fix/{fix}" if fix else f"feature/{feature_id}", str(tree), "main")
        # It's been here before, for a released feature that's changing or a build a restart interrupted, so catch up.
        elif subprocess.run(["git", "merge", "-q", "--no-edit", "main"], cwd=tree, check=False, capture_output=True).returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=tree, check=False, capture_output=True)
        return tree

    def remove_fix(self, fix):
        subprocess.run(["git", "worktree", "remove", "--force", str(TREES / fix)], cwd=REPO, check=False, capture_output=True)
        subprocess.run(["git", "branch", "-D", f"fix/{fix}"], cwd=REPO, check=False, capture_output=True)

    async def _review(self, spec, feature_id, tree, screenshots):
        shots = "\n".join(f"- {path}" for path in screenshots) or "(none: this feature adds nothing visible)"
        prompt = (f"Spec:\n{llm.untrusted('spec', spec)}\n\nThe feature is in {tree}/mods/genesis/features/{feature_id}. "
                  f"The world's theme is in {tree}/bible/theme.md.\n\nScreenshots from a real game client:\n{shots}")
        reach = changes_to_others(tree, feature_id)
        if reach:
            prompt += f"\n\nIt reaches into other features too, which are in {tree}/mods/genesis/features, so judge that as well:\n{llm.untrusted('changes_to_other_features', reach)}"
        result = await llm.ask(self.governor, "reviewer", prompt, schema=VERDICT_SCHEMA, tools=["Read", "Glob", "Grep"],
                               allowed_tools=["Read", "Glob", "Grep"], cwd=str(tree), max_turns=12)
        if result.is_error or not isinstance(result.structured, dict):
            return {"approve": False, "problems": ["The review didn't complete, so it should run again."]}
        return result.structured

    async def _attempt(self, feature_id, tree, prompt, session, small, lane, node, stage, max_turns, usage, tools, web, fix=None):
        """One go at the feature, by a model here or on another machine. Either way, what it did ends up in this tree."""
        role = self._role(small, fix)
        if lane == lanes.REMOTE:
            # Being committed is what lets the machine see any earlier attempt's work.
            try:
                ready_commit(f"{feature_id}: before going to another machine", tree, feature_id, node)
            except Refused:
                pass  # It's committed as far as it can be, and sorting out the rest is what the machine's being asked to do.
            return await self.hub.attempt(feature_id, tree, {"prompt": prompt, "system": llm.prompt_text("builder"), "session": session, "small": small,
                                                             "node": node, "stage": stage, "max_turns": max_turns, "budget": usage})
        chosen = self._lane_for(role, lane)
        names = [*tools, ART_TOOL] if chosen else tools
        helpers = {name: helper for name, helper in SUBAGENTS.items() if not chosen or name not in ART_KINDS}
        return await llm.ask(self.governor, role, (ART_NOTE if chosen and not session else "") + prompt, system=llm.prompt_text("builder"), tools=names, allowed_tools=names,
                             disallowed_tools=BUILDER_DENIED, agents=None if small else helpers, cwd=str(tree), max_turns=max_turns, resume=session,
                             mcp_servers={"broker": _tools_for(feature_id, tree, node), "web": web, "world": self.world_server(),
                                          **({"art": self._art_server(feature_id, tree, node, web)} if chosen else {})},
                             budget=usage, lane=chosen)

    @staticmethod
    def _role(small, fix):
        return "bug_fixer" if fix else "small_builder" if small else "builder"

    def _lane_for(self, role, lane):
        return self.lanes.get(lane) or llm.moved(role)

    def _remember_art(self, feature_id, art):
        self.art_made.setdefault(feature_id, {}).update(art)
        ART_MADE.parent.mkdir(parents=True, exist_ok=True)
        ART_MADE.write_text(json.dumps(self.art_made), encoding="utf-8")

    async def _make_art(self, kind, brief, feature_id, tree, node, web):
        """One piece of work by Opus, in the builder's tree. Only what it really changes counts as made by it."""
        folder = tree / "mods/genesis/features" / feature_id
        helper = SUBAGENTS[kind]
        before = _art_in(folder)
        result = await llm.ask(self.governor, kind, f"The feature's folder is mods/genesis/features/{feature_id}/.\n\n{brief}", system=helper.prompt, tools=helper.tools,
                               allowed_tools=helper.tools, disallowed_tools=BUILDER_DENIED, cwd=str(tree), max_turns=ART_TURNS, budget=ART_USAGE,
                               mcp_servers={"broker": _tools_for(feature_id, tree, node), "web": web})
        self._remember_art(feature_id, {path: blob for path, blob in _art_in(folder).items() if before.get(path) != blob})
        return result

    def _art_server(self, feature_id, tree, node, web):
        @tool("make_art", "Has Claude Opus make art for this feature. Give it every job at once, and they run at the same time. This takes minutes, and it replies with what was made.", ART_SCHEMA)
        async def make_art(args):
            jobs = [job for job in args.get("jobs", []) if job.get("kind") in ART_KINDS and job.get("brief")]
            print(f"{feature_id}: asked for {len(jobs)} pieces of art", flush=True)
            results = await asyncio.gather(*(self._make_art(job["kind"], job["brief"], feature_id, tree, node, web) for job in jobs), return_exceptions=True)
            answers = [f"That one failed: {result}" if isinstance(result, Exception) else f"That one failed: {result.stop_reason}" if result.is_error else result.text for result in results]
            return _text("\n\n".join(f"{job['kind']}: {answer}" for job, answer in zip(jobs, answers)) or "Give each job a kind and a brief.")
        return create_sdk_mcp_server("art", tools=[make_art])

    async def _finish_art(self, feature_id, spec, tree, node, web):
        """A builder on another model may have drawn something itself or left what a template made, so Opus redoes it before anything
        tests it. What's already shipped isn't touched. False means it has to wait until Claude can do that."""
        folder = tree / "mods/genesis/features" / feature_id
        made, shipped = self.art_made.get(feature_id, {}), _shipped_art(tree, feature_id)
        left = sorted(path for path, blob in _art_in(folder).items() if blob not in (made.get(path), shipped.get(path)))
        if not left:
            return True
        print(f"{feature_id}: {len(left)} pieces of art going to Opus", flush=True)
        result = await self._make_art("artist", f"The builder of this feature made these without you: {', '.join(left)}. Read feature.json and redo each one, so that it's your own "
                                                f"work and does what's needed here. Keep the names.\n\n{llm.untrusted('spec', spec)}", feature_id, tree, node, web)
        if result.is_error:
            print(f"{feature_id}: Opus couldn't redo its art: {result.stop_reason}", flush=True)
            return not self.governor.why_not_build()  # A reviewer on Claude still looks at it, so this needn't stop it for good.
        # It's seen them all, so it isn't asked twice about whatever it chose to leave.
        self._remember_art(feature_id, {path: blob for path, blob in _art_in(folder).items() if path in left})
        return True

    async def build(self, feature_id, spec, node, stage, small=False, lane=None, about="", fix=None, on_released=None):
        """Takes one feature from spec to released. Returns True if it reached players, False if it couldn't be done,
        and None if it had to stop for now and should be picked up again later. With fix, it's the name of a bug fix to an
        existing feature rather than the feature itself being built."""
        started = time.monotonic()
        tree = self._prepare_tree(feature_id, fix)
        (tree / "mods/genesis/features" / feature_id).mkdir(parents=True, exist_ok=True)
        session = None
        feedback = None
        last_problem = ""
        timings = {}
        web = self.web_research.server(FEATURE_RESEARCH)
        max_turns, usage, attempts = FIX_LIMITS if fix else SMALL_LIMITS if small else STAGE_LIMITS[stage]
        tools = SMALL_TOOLS if small else BUILDER_TOOLS
        attempt = conflicts = 0
        while attempt - conflicts < attempts:
            attempt += 1
            reason = self.governor.why_not_build()
            if reason:
                print(f"{feature_id}: pausing: {reason}", flush=True)
                return None

            prompt = feedback or ((FIX_NOTE if fix else SMALL_NOTE if small else "") + f"Build this feature, with id `{feature_id}`, in node `{node}`, which is in the {stage} game. Its place "
                                  f"in the world is in bible/progression.json.\n\n{llm.untrusted('spec', spec)}\n\n"
                                  f"Your feature folder is mods/genesis/features/{feature_id}/.")
            began = time.monotonic()
            chosen = self._lane_for(self._role(small, fix), lane)
            try:
                result = await self._attempt(feature_id, tree, prompt, session, small, lane, node, stage, max_turns, usage, tools, web, fix)
            except Exception:
                # Claude Code raises when its model turns it away, and then the only thing wrong is the model. The work so far stays in the folder.
                if not chosen or not chosen.in_trouble():
                    raise
                print(f"{feature_id}: its model isn't answering, which says nothing about the feature, so it's going back in the queue", flush=True)
                return None
            if result.stop_reason in lanes.MACHINE_GONE:
                print(f"{feature_id}: the machine it was on has gone, so it's going back in the queue", flush=True)
                return None
            timings[f"build_{attempt}"] = round(time.monotonic() - began, 1)
            session = result.session_id or session
            if result.is_error:
                print(f"{feature_id}: builder failed: {result.stop_reason} {result.text[:200]}", flush=True)
                if chosen and chosen.in_trouble():
                    print(f"{feature_id}: its model isn't answering, which says nothing about the feature, so it's going back in the queue", flush=True)
                    return None
                last_problem = f"The builder stopped: {result.stop_reason}"
                continue

            if (chosen or lane == lanes.REMOTE) and not await self._finish_art(feature_id, spec, tree, node, web):
                print(f"{feature_id}: pausing until Claude can finish its art", flush=True)
                return None
            timings[f"art_{attempt}"] = round(time.monotonic() - began - timings[f"build_{attempt}"], 1)
            # Goes to main, so the commit just below picks it up, and it goes out with this feature.
            began = time.monotonic()
            await self.translator.feature(tree / "mods/genesis/features" / feature_id)
            timings[f"translate_{attempt}"] = round(time.monotonic() - began, 1)

            began = time.monotonic()
            gates = await checked_against_main("gates", f"{feature_id}: attempt {attempt}", tree, feature_id, node, release_id=f"{fix or feature_id}-{attempt}", hurry=small, first=bool(fix))
            timings[f"gates_{attempt}"] = round(time.monotonic() - began, 1)
            if gates.get("result") not in ("passed_gates", "nothing_to_release"):
                conflicts = min(MOST_CONFLICTS, conflicts + (gates.get("gate") == "merge"))
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
                if verdict.get("serious", True) or attempt - conflicts < attempts:
                    feedback = "A reviewer found problems:\n- " + "\n- ".join(verdict.get("problems", [])) + "\n\nFix them."
                    continue
                print(f"{feature_id}: shipping anyway: the problems aren't serious and the gates passed", flush=True)

            began = time.monotonic()
            released = await self._release(feature_id, tree, node, about, fix)
            timings["release"] = round(time.monotonic() - began, 1)
            if released.get("result") not in WENT_OUT:
                conflicts = min(MOST_CONFLICTS, conflicts + (released.get("gate") == "merge"))
                feedback = f"Release failed at {released.get('gate')}: {released.get('reason')}\n\nFix it."
                last_problem = f"Release: {str(released.get('reason'))[:300]}"
                print(f"{feature_id}: release failed: {released.get('reason')}", flush=True)
                continue

            if not fix:
                self.governor.record_gate_result(True)
            timings["total"] = round(time.monotonic() - started, 1)
            self._log_timing(feature_id, timings, released)
            print(f"{feature_id}: released in {timings['total']}s: {timings}", flush=True)
            await (on_released or self.on_released)(feature_id, tree)
            return True
        print(f"{feature_id}: giving up after {attempts} attempts", flush=True)
        # What players report shouldn't be able to stop everything else, or send the director off after something it never asked for.
        if fix:
            return False
        # Only a whole feature failing counts, because builders getting a check wrong on the way is just how they work,
        # and with several at once, five of those in a row is nothing to stop for.
        self.governor.record_gate_result(False)
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
