"""What players report with /bug. An agent looks into each one straight away and tells the player what it found, and whatever can be
fixed is fixed ahead of everything else. None of this goes near the job queue or the director: a bug has no place in line and no limit
on how many builders are running, and a fix has its own branch, so it doesn't wait for whoever's working on the same feature.
"""
import asyncio
import json
import pathlib
import re
import time

from claude_agent_sdk import create_sdk_mcp_server, tool

from orchestrator import llm, progression, voice, workshop

STATE = pathlib.Path("/workspace/state")
CRASHED_MIXINS = pathlib.Path("/workspace/reports/crashed_mixins.json")
# Who a crashed mixin is reported by. It's no player's name, so there's nobody to tell, and what it would say to them just waits.
CRASH_REPORTER = "the server"
CRASH_CHECK_SECONDS = 30
LOG = "bugs.jsonl"
INVESTIGATING = "investigating"
FIXING = "fixing"
FIXED = "fixed"
NOT_A_BUG = "not_a_bug"
CANT_CONFIRM = "cant_confirm"
ENGINE_LIMIT = "engine_limit"
JOINED = "same_as_another"
STILL_OPEN = (INVESTIGATING, FIXING)
CONFIRMED = "confirmed"
ENGINE = "engine"
VERDICTS = (CONFIRMED, ENGINE, NOT_A_BUG, CANT_CONFIRM)
LABEL = "§c[Bug]§r "
LONGEST_REPORT = 1000
TRIES = 2
MOST_TURNS = 30
MOST_USAGE = 5.0
WAIT_SECONDS = 60

SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": list(VERDICTS)},
    "findings": {"type": "string"},
    "same_as": {"type": "integer"},
    "feature": {"type": "string"},
    "title": {"type": "string"},
    "spec": {"type": "string"},
    "owner_note": {"type": "string"}}, "required": ["verdict", "findings"]}
READING = ["Read", "Glob", "Grep"]
EVIDENCE = ["mcp__evidence__player_state", "mcp__evidence__server_errors", "mcp__evidence__java_api", "mcp__world__world_index"]


class BugDesk:
    def __init__(self, agent):
        self.agent = agent
        self.reports = agent.state.setdefault("bugs", {})  # By number, and saved, so a restart picks up what it interrupted.
        self.feature_locks = {}  # Two fixes to one feature would only collide when they went out, so they take turns.
        self.tasks = set()

    def _log(self, number, event, **details):
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / LOG).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "bug": number, "event": event, **details}) + "\n")

    def open_count(self):
        return sum(entry["status"] in STILL_OPEN for entry in self.reports.values())

    def of_player(self, player):
        """What they can be told about their own reports, and nobody else's."""
        return [{"reported": entry["text"], "status": entry["status"], **({"found": entry["findings"]} if entry.get("findings") else {})}
                for entry in self.reports.values() if entry["player"] == player or player in entry.get("also", [])]

    async def report(self, player, text):
        text = text.strip()[:LONGEST_REPORT]
        if not text:
            return
        number = max((int(key) for key in self.reports), default=0) + 1
        self.reports[str(number)] = {"player": player, "text": text, "at": time.time(), "status": INVESTIGATING}
        self.agent.save()
        self._log(number, "reported", player=player, text=text)
        await self.agent.tell(player, LABEL + "§7Thanks. I'm looking into that now, ahead of everything else, and I'll tell you what I find.")
        self._start(number)

    async def report_crashed_mixins(self):
        """A mixin that brings the live server down is taken out by the broker, and then it's a bug like any other, though no player's going to report it."""
        if not CRASHED_MIXINS.exists():
            return
        told = self.agent.state.setdefault("crashed_mixins_told", [])
        for feature_id, entry in json.loads(CRASHED_MIXINS.read_text(encoding="utf-8")).items():
            key = f"{feature_id} {entry['at']}"
            if key not in told:
                told.append(key)
                self.agent.save()
                await self.report(CRASH_REPORTER, f"The mixins of {feature_id} crashed the live server, so they've been taken out and that feature is running without them until they change. "
                                                  f"Find what's wrong with them in its mixins folder, and whether it can fail like this anywhere else. {entry['reason']}. {entry.get('crash', '')}")

    async def watch_for_crashed_mixins(self):
        while True:
            try:
                await self.report_crashed_mixins()
            except (OSError, ValueError, KeyError) as error:
                print(f"couldn't read what crashed: {error}", flush=True)
            await asyncio.sleep(CRASH_CHECK_SECONDS)

    def resume(self):
        """Whatever a restart interrupted. Its fix so far is still in its folder."""
        for key, entry in self.reports.items():
            if entry["status"] in STILL_OPEN:
                self._start(int(key))

    def _start(self, number):
        task = asyncio.create_task(self._work(number))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _work(self, number):
        entry = self.reports[str(number)]
        try:
            if entry["status"] == INVESTIGATING:
                await self._investigate(number, entry)
            if entry["status"] == FIXING:
                await self._fix(number, entry)
        except Exception as error:  # noqa: BLE001 - someone's waiting to hear, whatever went wrong
            print(f"bug {number} failed: {type(error).__name__}: {error}", flush=True)
            await self._collect(number, entry, f"Working on it failed with {type(error).__name__}: {error}")
            await self._tell_all(entry, LABEL + "§7I couldn't finish with that bug, so it isn't fixed. It's on the list of what's still broken.")

    async def _wait_until_allowed(self):
        """A stopped agent or a used-up plan holds this up, and it carries on by itself after. It's the owner's limit, so it counts for this too."""
        while self.agent.governor.why_not_build():
            await asyncio.sleep(WAIT_SECONDS)

    # Looking into it ----------------------------------------------------------------------------------------

    def _evidence(self, player):
        """Only ever about the player who reported it, and nothing here can change anything."""
        @tool("player_state", "Where the player who reported this is, what they're looking at and everything they're carrying, as the game has it right now.", {})
        async def player_state(args):
            try:
                return workshop._text(json.dumps(await self.agent.bridge.call("inspect_player", player=player)))
            except (RuntimeError, ConnectionError, TimeoutError) as error:
                return workshop._text(f"Can't see them right now: {error}")

        @tool("server_errors", "The live server's recent warnings and errors. Pass contains to keep only lines with those words, like the name of a feature's module.",
              {"type": "object", "properties": {"contains": {"type": "string"}}})
        async def server_errors(args):
            answer = await workshop.request("server_errors", contains=args.get("contains", ""))
            return workshop._text(answer.get("output") or answer.get("reason", "Nothing."))

        @tool("java_api", "Shows the real public methods and fields of a Minecraft or Fabric class. Pass the full class name.", {"class_name": str})
        async def java_api(args):
            answer = await workshop.request("javap", class_name=args["class_name"])
            return workshop._text(answer.get("output") or answer.get("reason", "Not found."))

        return create_sdk_mcp_server("evidence", tools=[player_state, server_errors, java_api])

    def _prompt(self, entry):
        others = [{"number": int(key), "report": other["text"], "status": other["status"], "feature": other.get("feature")}
                  for key, other in self.reports.items() if other is not entry and other["status"] in STILL_OPEN]
        return (f"A player called {entry['player']} has reported this:\n{llm.untrusted('player_report', entry['text'])}\n\n"
                f"Other bugs being worked on right now:\n{llm.untrusted('open_bugs', json.dumps(others))}\n\nFind out what's really going on." + voice.language_note(self.agent.language_of(entry["player"])))

    async def _ask(self, entry):
        for _ in range(TRIES):
            await self._wait_until_allowed()
            result = await llm.ask(self.agent.governor, "bug_investigator", self._prompt(entry), schema=SCHEMA, tools=READING, allowed_tools=[*READING, *EVIDENCE],
                                   disallowed_tools=workshop.BUILDER_DENIED, cwd=str(workshop.REPO), max_turns=MOST_TURNS, budget=MOST_USAGE,
                                   mcp_servers={"evidence": self._evidence(entry["player"]), "world": self.agent.workshop.world_server()})
            found = result.structured
            if not result.is_error and isinstance(found, dict) and found.get("verdict") in VERDICTS and found.get("findings"):
                return found
            print(f"looking into a bug didn't finish: {result.stop_reason}", flush=True)
        return None

    def _where_to_fix(self, found):
        """A model names the feature, and it becomes a folder and a branch, so it has to be one that's really out."""
        feature_id = found.get("feature") or ""
        manifest = workshop.REPO / "mods/genesis/features" / feature_id / "feature.json"
        if not found.get("spec") or not re.fullmatch(workshop.FEATURE_ID, feature_id) or not manifest.exists():
            return None
        node = json.loads(manifest.read_text(encoding="utf-8")).get("node")
        graph = progression.read(workshop.REPO / workshop.PROGRESSION)
        return (feature_id, node, progression.stage_of(graph, node)) if node in graph["nodes"] else None

    def _speakable(self, text):
        return voice.guard(text, self.agent.briefs(), voice.HELP_LIMIT)

    async def _investigate(self, number, entry):
        found = await self._ask(entry)
        if found is None:
            await self._collect(number, entry, "Looking into it didn't finish.")
            await self.agent.deliver(entry["player"], LABEL + "§7I couldn't get to the bottom of that, so it isn't fixed. It's on the list of what's still broken.")
            return
        self._log(number, "investigated", **{key: found.get(key) for key in SCHEMA["properties"] if found.get(key) is not None})
        said = self._speakable(found["findings"]) or "I've finished looking into that."
        entry["findings"] = said
        other = self.reports.get(str(found.get("same_as")))
        if other is not None and other is not entry and other["status"] in STILL_OPEN:
            other.setdefault("also", []).append(entry["player"])
            entry["status"] = JOINED
            entry["same_as"] = found["same_as"]
            self.agent.save()
            await self.agent.deliver(entry["player"], LABEL + said + " §7That's already being worked on, and I'll tell you when it's done.")
            return
        place = self._where_to_fix(found) if found["verdict"] == CONFIRMED else None
        if place:
            entry.update(status=FIXING, feature=place[0], node=place[1], stage=place[2], spec=found["spec"], title=found.get("title") or "")
            self.agent.save()
            await self.agent.deliver(entry["player"], LABEL + said + " §7I'm fixing it now, ahead of everything else, and I'll tell you when it's in.")
        elif found["verdict"] in (CONFIRMED, ENGINE):
            await self._collect(number, entry, found.get("owner_note") or found["findings"])
            await self.agent.deliver(entry["player"], LABEL + said + " §7That's in the engine under the world, which nothing in the world can change, so it's on the list of what the engine is missing.")
        else:
            entry["status"] = found["verdict"]
            self.agent.save()
            await self.agent.deliver(entry["player"], LABEL + said)

    async def _collect(self, number, entry, note):
        entry["status"] = ENGINE_LIMIT
        self.agent.tell_owner(f"bug {number}", [f"{entry['text']}: {note}"])
        self.agent.save()
        self._log(number, "collected for the engine", note=note)

    # Fixing it ----------------------------------------------------------------------------------------------

    async def _released(self, feature_id, tree):
        """Not the queue's own version, because a fix isn't the feature being finished, and whatever's been asked of that feature is still to come."""
        manifest = json.loads((tree / "mods/genesis/features" / feature_id / "feature.json").read_text(encoding="utf-8"))
        if manifest.get("host_requests"):
            self.agent.tell_owner(feature_id, manifest["host_requests"])
        self.agent.state["release_count"] = self.agent.state.get("release_count", 0) + 1
        self.agent.save()

    async def _build(self, number, entry):
        async with self.feature_locks.setdefault(entry["feature"], asyncio.Lock()):
            while True:
                await self._wait_until_allowed()
                shipped = await self.agent.workshop.build(entry["feature"], entry["spec"], entry["node"], entry["stage"], small=True, about="a bug fix", fix=f"bug_{number}", on_released=self._released)
                if shipped is not None:  # Otherwise it had to stop for now, not because of anything wrong with it.
                    return shipped

    async def _fix(self, number, entry):
        try:
            shipped = await self._build(number, entry)
        finally:
            self.agent.workshop.remove_fix(f"bug_{number}")
        if shipped:
            entry["status"] = FIXED
            self.agent.save()
            self._log(number, "fixed", feature=entry["feature"])
            title = self._speakable(entry.get("title"))
            await self._tell_all(entry, LABEL + (f"§7Fixed, and it's live now: §f{title}" if title else "§7That's fixed, and it's live now."))
        else:
            await self._collect(number, entry, f"A fix to {entry['feature']} couldn't be made to pass the gates. What was found: {entry['spec']}")
            await self._tell_all(entry, LABEL + "§7I couldn't get a fix for that through the checks, so it isn't fixed. It's on the list of what's still broken.")

    async def _tell_all(self, entry, text):
        for player in dict.fromkeys([entry["player"], *entry.get("also", [])]):
            await self.agent.deliver(player, text)
