"""What's kept about each build for the website: its prompt, what it used, how far it's got, what became of it and what it said along the way.

Builder sessions live in the agent's container, and that's replaced by every deploy, so this keeps its own copy as things happen. Only what's already
been scrubbed gets written here, because the website's process reads this folder and nothing else of the agent's. Everything in here is about the
page and nothing depends on it, so a problem writing it can only ever cost a line in the log, and never a build.
"""
import contextvars
import dataclasses
import functools
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import time

from orchestrator import feedback, scrub

FOLDER = pathlib.Path(os.environ.get("LEDGER_FOLDER", "/workspace/state/ledger"))
ACTIVE = contextvars.ContextVar("ledger_run", default=None)
# What a builder can say it's doing where a spoiler-free page can see it. A fixed list, so that no word of a feature can slip through this way.
PHASES = ("planning", "writing code", "making art", "checking its work", "fixing problems", "finishing up")
BUILDING, ART, TRANSLATING, TESTING, REVIEWING, RELEASING, WAITING = "building", "art", "translating", "testing", "reviewing", "releasing", "waiting"
GATE, REVIEW, RELEASE, BUILDER, CRASHED, REFUSED = "gate", "review", "release", "builder", "crashed", "refused"
BUILDER_ROLES = ("builder", "small_builder", "bug_fixer")
# The only conversations that can ever go in a record. A voice talking to a player can run from inside a build, when one reaches them with news of it, and what's said there is theirs.
RECORDED_ROLES = (*BUILDER_ROLES, "reviewer", "artist", "modeller", "translator", "researcher")
KINDS = {"Gate": GATE, "Review": REVIEW, "Release": RELEASE, "The builder stopped": BUILDER}
SAVE_SECONDS = 3
LONGEST_PROMPT = 20000
LONGEST_SAID = 8000
LONGEST_THOUGHT = 3000
LONGEST_INPUT = 2000
LONGEST_RESULT = 3000
LONGEST_REASON = 4000
LONGEST_STATUS = 200
LONGEST_SPEC = 20000
MOST_TRANSCRIPT_BYTES = 30 * 1024 * 1024
MOST_SCREENSHOTS = 40
SCRUBBER_SECONDS = 60
# A tool call that goes near any of these may have read something private, whatever it got back, so what it got back isn't kept. See Call._result.
PRIVATE_PLACES = re.compile(r"/workspace/state|opening\.json|intents\.jsonl|bugs\.jsonl|\bbriefs/|private_chats|/run/secrets|/proc/|\.credentials|\.claude/|/control\b|\benviron\b|\bprintenv\b|(?:^|[\"';&|]\s*)(?:env|set|export -p|declare -x)\s*(?:$|[\"';&|])", re.MULTILINE)
PRIVATE_MARKS = re.compile(r"private_chats|\"briefs\"|\"interviews\"|OAUTH_TOKEN|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_API_KEY")
NOT_SHOWN = "(This looked at somewhere private, so what came back isn't kept.)"

_private_sources = lambda: ((), ())  # noqa: E731 - who plays, and what's been said in private
_scrubber = None
_scrubber_built = 0.0
_open = {}  # What's being worked on or waiting to carry on, by feature or fix.
_loaded = False


def _careful(function):
    """Nothing about the page may ever stop a build."""
    @functools.wraps(function)
    def run(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001
            print(f"the page's record: {function.__name__} failed: {type(error).__name__}: {error}", flush=True)
            return None
    return run


def configure(private_sources):
    global _private_sources, _scrubber
    _private_sources = private_sources
    _scrubber = None


def scrubber():
    """Built afresh now and then, because someone new can join or say something at any time."""
    global _scrubber, _scrubber_built
    if _scrubber is None or time.monotonic() - _scrubber_built > SCRUBBER_SECONDS:
        _scrubber = scrub.Scrubber(*_private_sources())
        _scrubber_built = time.monotonic()
    return _scrubber


def _write(path, data):
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    temporary.write_bytes(data)
    temporary.replace(path)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, json.dumps(value, indent=1).encode("utf-8"))


def page_id(name):
    """What a page's address uses, because a feature's name in an address would be a spoiler. It can't be worked back from the name without this salt."""
    path = FOLDER / "salt"
    if not path.exists():
        FOLDER.mkdir(parents=True, exist_ok=True)
        _write(path, secrets.token_bytes(32))
    return hmac.new(path.read_bytes(), name.encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def _totals(usage):
    usage = usage or {}
    return {"input": int(usage.get("input_tokens") or usage.get("inputTokens") or 0), "output": int(usage.get("output_tokens") or usage.get("outputTokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or usage.get("cacheReadInputTokens") or 0),
            "cache_write": int(usage.get("cache_creation_input_tokens") or usage.get("cacheCreationInputTokens") or 0)}


def _final_totals(final):
    """What a whole call used. Per model, when it says, because that counts its subagents too."""
    models = final.model_usage or {}
    if not models:
        return _totals(final.usage)
    summed = {}
    for usage in models.values():
        for name, value in _totals(usage).items():
            summed[name] = summed.get(name, 0) + value
    return summed


class Run:
    """One go at getting something out, from the first time it's started to whatever became of it, however many restarts come in between."""

    def __init__(self, data):
        self.data = data
        self.saved_at = 0.0
        self.path = FOLDER / "runs" / f"{data['run']}.json"
        self.transcript = FOLDER / "runs" / f"{data['run']}.transcript.jsonl"
        self.transcript_full = False
        self.active = False

    @_careful
    def save(self, soon=False):
        """A long build says a great deal, so most of it can wait a moment."""
        now = time.monotonic()
        if soon and now - self.saved_at < SAVE_SECONDS:
            return
        self.saved_at = now
        _write_json(self.path, self.data)

    @_careful
    def details(self, **details):
        self.data.update(details)
        self.save()

    @_careful
    def stage(self, name, attempt=None):
        """Where plain code has got to with it. Always true and always safe to show, which is what a spoiler-free page goes by."""
        self.data.update(stage_now=name, active_at=time.time())
        if attempt is not None:
            self.data["attempt"] = attempt
        self.save()

    @_careful
    def status(self, phase, doing):
        """What its builder says it's doing. It can write anything at all here, so only the fixed phase is ever safe to show."""
        self.data["status"] = {"phase": phase if phase in PHASES else None, "doing": scrubber()(str(doing or "").replace("\n", " "), LONGEST_STATUS), "at": time.time()}
        self.data["active_at"] = time.time()
        self.save()

    @_careful
    def problem(self, reason):
        """Why an attempt went back to its builder, or why it was all given up on, if it's the last one."""
        kind = next((kind for word, kind in KINDS.items() if reason.startswith(word)), None)
        self.data.setdefault("attempts", []).append({"attempt": self.data.get("attempt"), "kind": kind, "reason": scrubber()(reason, LONGEST_REASON), "at": time.time()})
        self.save()

    @_careful
    def screenshots(self, paths):
        """What the reviewer will look at. Only ever the last pass counts."""
        self.data["screenshots"] = [path for path in paths if isinstance(path, str)][:MOST_SCREENSHOTS]
        self.save()

    @_careful
    def finish(self, outcome, kind=None, reason=None, timings=None, **details):
        now = time.time()
        attempts = self.data.get("attempts") or []
        if outcome != "released":
            reason = reason or (attempts[-1]["reason"] if attempts else "")
            kind = kind or (attempts[-1]["kind"] if attempts else None)
            self.data["failure"] = {"kind": kind, "reason": scrubber()(reason, LONGEST_REASON)}
        self._stop_the_clock(now)
        self.data.update(outcome=outcome, finished_at=now, stage_now=None, timings=timings or self.data.get("timings"), **details)
        self.active = False
        _open.pop(self.data["key"], None)
        self.save()

    @_careful
    def pause(self):
        """It's going back in the queue or waiting for a model, and it'll carry on with this same record."""
        self.active = False
        self._stop_the_clock(time.time())
        self.data.update(stage_now=WAITING, active_at=time.time())
        self.save()

    def _stop_the_clock(self, now):
        """How long it's run is only ever the time it was really being worked on, and not time it spent waiting in the queue."""
        began = self.data.pop("resumed_at", None)
        if began:
            self.data["seconds"] = round(self.data.get("seconds", 0.0) + max(0.0, now - began), 1)

    @_careful
    def took(self, name, seconds):
        """Time spent at each step, across every go at it. The name's like build_2, and attempts start again from 1 after a restart, so these add up by step."""
        phases = self.data.setdefault("phases", {})
        step = name.split("_")[0]
        phases[step] = round(phases.get(step, 0.0) + seconds, 1)
        self.save()

    def _add(self, entry):
        if self.transcript_full:
            return
        line = (json.dumps({"at": round(time.time(), 1), **entry}) + "\n").encode("utf-8")
        size = self.transcript.stat().st_size if self.transcript.exists() else 0
        if size + len(line) > MOST_TRANSCRIPT_BYTES:
            self.transcript_full = True
            line = (json.dumps({"at": round(time.time(), 1), "kind": "note", "text": "That's as much of this transcript as is kept."}) + "\n").encode("utf-8")
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        with self.transcript.open("ab") as stream:
            stream.write(line)
        self.data["entries"] = self.data.get("entries", 0) + 1

    def _count(self, role, change):
        tokens = self.data.setdefault("tokens", {}).setdefault(role, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
        for name, value in change.items():
            tokens[name] = tokens.get(name, 0) + value

    @_careful
    def add_entries(self, entries, usage=None, role="builder"):
        """What a builder on another machine sends back when it's done. That machine's been running a builder's shell, so it's scrubbed again here."""
        clean = scrubber()
        for entry in entries or []:
            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                self._add({"kind": str(entry.get("kind"))[:10], "role": str(entry.get("role") or role)[:30], "name": str(entry.get("name") or "")[:80], "text": clean(entry["text"], LONGEST_RESULT)})
        if isinstance(usage, dict):
            self._count(role, {name: int(usage.get(name) or 0) for name in ("input", "output", "cache_read", "cache_write")})
        self.save()


class Nothing:
    """What a call outside any build gets, so that the code around it stays the same."""

    def heard(self, message):
        pass

    def answered(self, final, estimate=0.0):
        pass


@dataclasses.dataclass
class Call:
    """One conversation with a model, as part of a build. A few of these can be going at once, which a run's subagents and art can do."""
    run: Run
    role: str
    seen: dict = dataclasses.field(default_factory=dict)  # What each message has said it used, because a long one reports more than once.
    counted: dict = dataclasses.field(default_factory=dict)
    hidden: set = dataclasses.field(default_factory=set)  # The tool calls whose results aren't to be kept.

    @_careful
    def heard(self, message):
        kind = type(message).__name__
        if kind == "AssistantMessage":
            self._assistant(message)
        elif kind == "UserMessage":
            self._user(message)
        self.run.save(soon=True)

    def _entry(self, kind, text, limit, sub=None, **extra):
        self.run._add({"kind": kind, "role": self.role, **({"sub": True} if sub else {}), "text": scrubber()(text, limit), **extra})

    def _assistant(self, message):
        self.run.data["active_at"] = time.time()
        sub = bool(message.parent_tool_use_id)
        for block in message.content:
            name = type(block).__name__
            if name == "TextBlock" and block.text.strip():
                self._entry("say", block.text, LONGEST_SAID, sub)
            elif name == "ThinkingBlock" and block.thinking.strip():
                self._entry("think", block.thinking, LONGEST_THOUGHT, sub)
            elif name == "ToolUseBlock":
                said = json.dumps(block.input, ensure_ascii=False)
                if PRIVATE_PLACES.search(said):
                    self.hidden.add(block.id)
                self._entry("use", said, LONGEST_INPUT, sub, name=scrubber()(block.name, 80), id=block.id)
        self._usage(message)

    def _usage(self, message):
        if not message.usage:
            return
        totals = _totals(message.usage)
        key = message.message_id or message.uuid or id(message)
        before = self.seen.get(key, {})
        self.seen[key] = totals
        change = {name: max(0, value - before.get(name, 0)) for name, value in totals.items()}
        for name, value in change.items():
            self.counted[name] = self.counted.get(name, 0) + value
        self.run._count(self.role, change)

    def _user(self, message):
        if not isinstance(message.content, list):
            return
        sub = bool(message.parent_tool_use_id)
        for block in message.content:
            if type(block).__name__ == "ToolResultBlock":
                self._result(block, sub)

    def _result(self, block, sub):
        content = block.content
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") if part.get("type") == "text" else f"({part.get('type')})" for part in content if isinstance(part, dict))
        text = content or ""
        # Worked out before the scrubbing, because this is about what it is and that's about what's in it.
        if block.tool_use_id in self.hidden or PRIVATE_MARKS.search(text):
            text = NOT_SHOWN
        self._entry("got", text, LONGEST_RESULT, sub, id=block.tool_use_id, **({"error": True} if block.is_error else {}))

    @_careful
    def answered(self, final, estimate=0.0):
        """The last word on what it used. Messages may have under-reported, so this only ever adds."""
        totals = _final_totals(final)
        self.run._count(self.role, {name: max(0, value - self.counted.get(name, 0)) for name, value in totals.items()})
        self.run.data["estimate"] = round(self.run.data.get("estimate", 0.0) + (estimate or 0.0), 6)
        self.run._add({"kind": "end", "role": self.role, "text": f"Finished: {final.stop_reason or final.subtype}", **({"error": True} if final.is_error else {})})
        self.run.save()


NOTHING = Nothing()


class Nowhere:
    """What a build gets if its record couldn't even be started. It'd be a shame to stop the build over that."""
    def __init__(self):
        self.data = {}

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Notebook(Run):
    """For a builder on another machine, which has nowhere to keep this. It goes back with the result, and the main server takes it from there."""
    MOST_ENTRIES = 3000

    def __init__(self):
        self.data = {}
        self.entries = []
        self.transcript_full = False
        self.active = True

    def save(self, soon=False):
        pass

    def _add(self, entry):
        self.entries.append(entry)
        del self.entries[:-self.MOST_ENTRIES]

    def handed_back(self):
        totals = {}
        for used in self.data.get("tokens", {}).values():
            for name, value in used.items():
                totals[name] = totals.get(name, 0) + value
        return {"transcript": self.entries, "usage": totals}


@_careful
def _call_for(role, prompt):
    run = ACTIVE.get()
    if run is None or role not in RECORDED_ROLES:
        return None
    call = Call(run, role)
    text = scrubber()(prompt, LONGEST_PROMPT)
    if role in BUILDER_ROLES:
        run.data.setdefault("prompts", []).append({"at": time.time(), "text": text})
    run._add({"kind": "prompt", "role": role, "text": text})
    run.save(soon=True)
    return call


def call(role, prompt):
    return _call_for(role, prompt) or NOTHING


def _load():
    """Whatever was going on when the agent last stopped carries on, if it's started again, in the same record."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    for path in (FOLDER / "runs").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # Its name decides where it's saved, and a builder's shell may have been in here, so it has to be what the file's already called.
        if data.get("outcome") is None and data.get("key") and data.get("run") == path.stem:
            run = Run(data)
            # Nothing marked when it stopped, so the last thing it was heard to do is as near as this can get.
            run._stop_the_clock(data.get("active_at") or time.time())
            data["stage_now"] = WAITING
            _open[data["key"]] = run


def open_run(key, feature, **details):
    return _open_run(key, feature, **details) or Nowhere()


@_careful
def _open_run(key, feature, **details):
    """Starts recording a build, or picks up where one left off. The spec goes through the scrubber, because the director has seen everyone's briefs."""
    _load()
    clean = scrubber()
    details = {name: value for name, value in details.items() if value is not None}
    if "spec" in details:
        details["spec"] = clean(details["spec"], LONGEST_SPEC)
    for name in ("title", "safe_name"):
        if name in details:
            details[name] = clean(details[name], 200)
    now = time.time()
    run = _open.get(key)
    if run is None:
        name = f"{key}-{int(now)}"
        run = Run({"run": name, "page": page_id(name), "key": key, "feature": feature, "started_at": now, "outcome": None})
        _open[key] = run
    run.data.update(details)
    run.data.update(stage_now=BUILDING, active_at=now, resumed_at=now)
    run.active = True
    run.save()
    return run


@_careful
def refused(feature, why):
    """Something the director asked for that never got as far as a builder."""
    name = feature.get("id") if isinstance(feature.get("id"), str) and re.fullmatch(r"[a-z0-9_]{1,60}", feature["id"]) else "unnamed"
    run = open_run(name, name, spec=feature.get("spec"), node=feature.get("node"), category=feature.get("category"), title=feature.get("title"), queued_at=feature.get("queued_at"),
                   kind="small" if feature.get("small") else "feature", safe_name=feedback.describe({**feature, "teaser": None}, None))
    run.finish("failed", kind=REFUSED, reason=why)


def find(key):
    _load()
    return _open.get(key)


@_careful
def status_of(key, phase, doing):
    """For a builder on another machine, whose tool can't reach its run from there."""
    run = find(key)
    if run:
        run.status(phase, doing)


@_careful
def named(key, **details):
    """A line for the sidebar can arrive after the build's begun."""
    run = find(key)
    if run and any(run.data.get(name) != value for name, value in details.items()):
        run.details(**details)


# The whole picture ----------------------------------------------------------------------------------------------------------------------

def _queued(feature, graph):
    clean = scrubber()
    run = _open.get(feature.get("id"))
    node = (graph or {}).get("nodes", {}).get(feature.get("node")) or {}
    return {"key": feature.get("id"), "page": page_id(f"queue {feature.get('id')}"), "run_page": run.data["page"] if run else None, "kind": "small" if feature.get("small") else "feature",
            "safe_name": clean(feedback.about(feature, graph), 200), "title": clean(feature.get("title") or "", 200), "category": feature.get("category"), "stage": node.get("stage"),
            "node": clean(node.get("name") or "", 200), "spec": clean(feature.get("spec") or "", LONGEST_SPEC), "queued_at": feature.get("queued_at")}


def _roadmap(graph):
    clean = scrubber()
    return {"goal": clean((graph or {}).get("goal") or "", 2000), "nodes": [
        {"id": node_id, "stage": node.get("stage"), "name": clean(node.get("name") or "", 200), "holds": clean(node.get("holds") or "", 1000),
         "opens_with": clean(node.get("opens_with") or "", 500), "requires": [str(item) for item in node.get("requires") or []]}
        for node_id, node in (graph or {}).get("nodes", {}).items()]}


@_careful
def write_board(chosen, queue, graph, planning=False, shipped=0, theme=""):
    """What's true right now. It's a list of named fields, so nothing from the agent's saved state reaches the website unless it's written here."""
    _load()
    clean = scrubber()
    _write_json(FOLDER / "board.json", {"at": time.time(), "chosen": bool(chosen), "planning": bool(planning), "shipped": shipped,
                                        "building": [run.data["page"] for run in _open.values() if run.active],
                                        **({"queue": [_queued(feature, graph) for feature in queue], "roadmap": _roadmap(graph), "theme": clean(theme, 3000)} if chosen else {})})


# What came before all this --------------------------------------------------------------------------------------------------------------

def _manifest(*paths):
    for path in paths:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def _category_of(manifest):
    """Builds from before this was kept didn't record one, so it's worked out from what it holds, in the same few words /plan uses."""
    for tables, category in ((("mobs",), "mob"), (("biomes", "dimensions"), "biome"), (("ruins",), "structure")):
        if any(manifest.get(table) for table in tables):
            return category
    return None


def _old_row(feature_id, finished, features, trees, graph):
    manifest = _manifest(features / feature_id / "feature.json", trees / feature_id / "mods/genesis/features" / feature_id / "feature.json")
    node = manifest.get("node")
    category = _category_of(manifest)
    stage = ((graph or {}).get("nodes", {}).get(node) or {}).get("stage")
    safe = feedback.describe({"node": node, "category": category}, graph)
    safe = f"{safe} feature" if not category and stage else safe
    clean = scrubber()
    return {"page": page_id(f"old {feature_id} {finished}"), "key": feature_id, "feature": feature_id, "old": True, "kind": "feature", "finished_at": finished, "category": category,
            "stage": stage, "node": node if isinstance(node, str) else None, "safe_name": clean(safe, 200), "summary": clean(manifest.get("summary") if isinstance(manifest.get("summary"), str) else "", 2000),
            "shown": clean(", ".join(str(thing["display"]) for table in ("blocks", "items", "mobs") for thing in (manifest.get(table) or {}).values() if isinstance(thing, dict) and thing.get("display")), 1000)}


@_careful
def bring_in_the_past(features_log, unfinished_log, features, trees, graph):
    """Once, the first time this runs: what's already been built and given up on, from the logs that were all there was. Those have no prompt and no transcript."""
    target = FOLDER / "old_builds.json"
    if target.exists():
        return
    rows = []
    if features_log.exists():
        for line in features_log.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            timings = {name: value for name, value in (entry.get("timings") or {}).items() if isinstance(value, (int, float))}
            rows.append({**_old_row(entry["feature"], entry.get("at"), features, trees, graph), "outcome": "released", "timings": timings, "seconds": timings.get("total")})
    if unfinished_log.exists():
        clean = scrubber()
        for line in unfinished_log.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            problem = entry.get("problem") or ""
            kind = next((kind for word, kind in KINDS.items() if problem.startswith(word)), None)
            rows.append({**_old_row(entry["feature"], entry.get("at"), features, trees, graph), "outcome": "failed", "failure": {"kind": kind, "reason": clean(problem, LONGEST_REASON)}})
    _write_json(target, rows)
