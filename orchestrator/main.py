#!/usr/bin/env python3
"""The agent's main loop: plain code that routes events and decides when each role runs."""
import asyncio
import json
import os
import pathlib
import re
import time

from orchestrator import icon, llm, minds, progression, research, voice, workshop, world_index
from orchestrator.bridge import Bridge
from orchestrator.governor import CONTROL, Governor

BIBLE = workshop.REPO / "bible"
PROGRESSION = workshop.REPO / workshop.PROGRESSION
FEATURES = workshop.REPO / "mods/genesis/features"
STATE = pathlib.Path("/workspace/state")
OPENING = STATE / "opening.json"
DECIDE_AFTER_SECONDS = 20 * 60
OPENING_BORDER = 256
OPEN_BORDER = 59_999_968
CHAT_BATCH_SECONDS = 20
WEEKLY_INTENTS_PER_PLAYER = 20
WATCH_SECONDS = 5 * 60
FEATURE_ID = r"[a-z][a-z0-9_]{1,40}"
DIRECTION_RESEARCH = 6
DIRECTOR_RESEARCH = 3
DIRECTOR_REST_SECONDS = 30 * 60
STOP_AFTER_RELEASES = os.environ.get("AGENT_STOP_AFTER_RELEASES")  # Lets a test spend a known amount.

STAGES_TEMPLATE = """\
# What each stage of the game is for. The world's own graph is in progression.json.
early:
  feel: Players still mine and build for themselves. There's just more to explore, more to build and more to work out.
  needs: [ores, tools_and_armor, plants_and_food, early_mobs, things_to_find, a_first_convenience_or_two]
mid:
  feel: Much more elaborate, and gated by resources from the early game, like vanilla's own technology. Players still have to go down mines, fight and explore.
  needs: [gating_resources, automated_crafting, machining, sorting, very_slow_automated_mining, very_slow_automated_mob_killing, stronger_gear_and_power_ups, biomes, structures]
end:
  feel: As crazy as it likes, with something big to build towards. This stage never has to be finished.
  needs: [a_goal_to_work_towards, enormous_machines, overpowered_mobs, gear_power_ups_or_spells_to_beat_them, new_places]
"""

NODE_SCHEMA = {"type": "object", "properties": {
    "id": {"type": "string"}, "stage": {"type": "string", "enum": list(progression.STAGES)}, "name": {"type": "string"},
    "requires": {"type": "array", "items": {"type": "string"}}, "opens_with": {"type": "string"}, "holds": {"type": "string"}},
    "required": ["id", "stage", "name", "requires", "opens_with", "holds"]}

DIRECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "features": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "node": {"type": "string"}, "spec": {"type": "string"}}, "required": ["id", "node", "spec"]}},
        "new_nodes": {"type": "array", "items": NODE_SCHEMA},
    },
    "required": ["features"],
}

TUNER_SCHEMA = {"type": "object", "properties": {"handled": {"type": "array", "items": {"type": "integer"}}}, "required": ["handled"]}


class Agent:
    def __init__(self):
        self.governor = Governor()
        self.bridge = Bridge()
        self.watcher = voice.Watcher(self.governor)
        self.research = research.Research(self.governor, self.private_words)
        self.minds = minds.Minds(self.governor, self.bridge, self.private_words)
        self.workshop = workshop.Workshop(self.governor, self.on_released, self.research, lambda: self.reached)
        self.interviews = {}
        self.chat_buffer = []
        self.queue = []
        self.building = set()
        self.wake_director = asyncio.Event()
        self.tune_wanted = asyncio.Event()
        self.director_rest_until = 0
        self.reached = []
        self.locks = {}
        self.choosing_direction = False
        self.direction_problems = []
        self.state = {"direction_chosen": False, "briefs": {}, "first_finished_at": 0, "released": [], "border_open": False,
                      "intents": {}, "intent_count": 0, "tuner_saw": 0, "handled_intents": []}
        if OPENING.exists():
            self.state.update(json.loads(OPENING.read_text(encoding="utf-8")))

    def save(self):
        OPENING.parent.mkdir(parents=True, exist_ok=True)
        OPENING.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def briefs(self):
        return list(self.state["briefs"].values())

    def private_words(self):
        return self.roster() | set(self.state["briefs"]) | set(self.interviews), self.briefs()

    def roster(self):
        path = CONTROL / "roster.txt"
        if not path.exists():
            return set()
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}

    # Interviews -----------------------------------------------------------------------------------

    async def start_interview(self, player):
        interview = voice.Interview(self.governor, player)
        self.interviews[player] = interview
        await self.bridge.capture(player, True)
        reply = await interview.turn("(The player has just arrived for the first time. Say hello and ask your first question.)")
        if reply:
            await self.bridge.whisper(player, reply)

    async def on_private_chat(self, player, text):
        interview = self.interviews.get(player)
        if interview is None:
            await self.bridge.capture(player, False)
            return
        reply = await interview.turn(text)
        # The player is waiting in private, so even a failed call needs an answer.
        await self.bridge.whisper(player, reply or "§7Sorry, I didn't catch that. Could you say it again?")
        if interview.finished:
            await self.bridge.capture(player, False)
            await self.bridge.whisper(player, "§7That's the end of the private talk. Your chat is public again.")
            self.state["briefs"][player] = interview.brief
            self.state["first_finished_at"] = self.state["first_finished_at"] or time.time()
            del self.interviews[player]
            self.save()
            self._store_brief(player, interview.brief)
            await self.maybe_choose_direction()

    def _store_brief(self, player, brief):
        folder = STATE / "briefs"  # Outside the agent's repo, so no builder ever reads one directly.
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{player}.json").write_text(json.dumps(brief, indent=1), encoding="utf-8")

    async def maybe_choose_direction(self):
        # A timer and a finished interview can both get here while the first call is still thinking.
        if self.state["direction_chosen"] or self.choosing_direction:
            return
        roster = self.roster()
        everyone_done = bool(roster) and roster.issubset(self.state["briefs"])
        waited = self.state["first_finished_at"] and time.time() - self.state["first_finished_at"] > DECIDE_AFTER_SECONDS
        called = (CONTROL / "decide_now").exists()
        if everyone_done or waited or called:
            self.choosing_direction = True
            try:
                await self.choose_direction()
            finally:
                self.choosing_direction = False

    async def choose_direction(self):
        print("choosing the direction", flush=True)
        direction = await voice.choose_direction(self.governor, self.briefs(), self.research.server(DIRECTION_RESEARCH), self.direction_problems)
        if direction is None:
            print("the direction call failed, will try again", flush=True)
            return
        graph = progression.from_direction(direction["goal"], direction["progression"])
        self.direction_problems = progression.problems(graph) + [
            f"First feature {feature['id']} names node {feature['node']!r}, which isn't in the graph."
            for feature in direction["first_features"] if feature["node"] not in graph["nodes"]]
        if self.direction_problems:
            print(f"the direction's progression has problems, will try again: {self.direction_problems}", flush=True)
            return
        BIBLE.mkdir(parents=True, exist_ok=True)
        (BIBLE / "theme.md").write_text(direction["theme_md"], encoding="utf-8")
        (BIBLE / "persona.md").write_text(direction["persona_md"], encoding="utf-8")
        (BIBLE / "persona_name.txt").write_text(direction["persona_name"], encoding="utf-8")
        (BIBLE / "discovery.md").write_text(direction["discovery_md"], encoding="utf-8")
        (BIBLE / "discovery.json").write_text(json.dumps({"scope": direction["discovery_scope"]}), encoding="utf-8")
        (BIBLE / "stages.yaml").write_text(STAGES_TEMPLATE, encoding="utf-8")
        progression.save(PROGRESSION, graph)
        workshop.commit_all("The direction for this world")
        self.queue.extend(direction["first_features"])
        self.state["direction_chosen"] = True
        self.save()
        for line in direction["tease"]:
            text = voice.guard(line, self.briefs())
            if text:
                await self.bridge.broadcast(voice.styled(text))
        print(f"direction chosen, {len(self.queue)} features queued", flush=True)
        self.wake_director.set()
        asyncio.create_task(self.make_icon())

    async def make_icon(self):
        try:
            await icon.make(self.governor)
        except Exception as error:  # noqa: BLE001 - a missing icon must never hold anything else up
            print(f"making the server icon failed: {error}", flush=True)

    # Events -----------------------------------------------------------------------------------------

    async def handle(self, event):
        kind = event.get("event")
        player = event.get("player", "")
        self.governor.player_seen()
        if self.governor.why_not_speak():
            # The character has gone quiet for now, so don't leave someone talking to nobody in private.
            if kind == "chat" and event.get("private"):
                await self.bridge.capture(player, False)
                await self.bridge.whisper(player, "§7The private talk is on hold, and that message wasn't sent. Your chat is public again.")
            return
        if kind == "join":
            if player not in self.state["briefs"] and player not in self.interviews:
                await self.start_interview(player)
            elif player in self.interviews:
                await self.bridge.capture(player, True)
        elif kind == "chat":
            text = event.get("text", "")
            if text.strip().lower() in ("!mute", "!unmute"):
                await self.set_muted(player, text.strip().lower() == "!mute")
            elif event.get("private"):
                await self.on_private_chat(player, text)
            else:
                self.chat_buffer.append({"player": player, "text": text})
        await self.speak_if_worthwhile(event, player)

    async def speak_if_worthwhile(self, event, player):
        # Nobody's met the character until the direction exists, so before then there's no one to speak.
        if not self.state["direction_chosen"]:
            return
        said = await self.watcher.consider(event, self.state["released"], self.briefs())
        if said:
            text, audience = said
            if audience == "broadcast":
                await self.bridge.broadcast(voice.styled(text))
            else:
                await self.bridge.whisper(player, voice.styled(text))

    async def set_muted(self, player, muted):
        if muted:
            self.watcher.muted.add(player)
        else:
            self.watcher.muted.discard(player)
        self.watcher._save()
        await self.bridge.whisper(player, "You won't hear unprompted remarks now." if muted else "Remarks are back on.")

    async def handle_in_turn(self, event):
        """Players don't wait on each other's slow calls, but each player's own events stay in order."""
        async with self.locks.setdefault(event.get("player", ""), asyncio.Lock()):
            try:
                await self.handle(event)
            except Exception as error:  # noqa: BLE001 - one bad event must not stop the agent
                print(f"error handling {event.get('event')}: {error}", flush=True)

    async def event_loop(self):
        while True:
            event = await self.bridge.events.get()
            # A creature's reply shouldn't hold up anything that player does next, or wait behind it.
            asyncio.create_task(self.minds.handle(event) if event.get("event") == "mob" else self.handle_in_turn(event))

    async def chat_loop(self):
        """Reads chat in batches, because most of it needs nothing and each read uses some of the plan."""
        while True:
            await asyncio.sleep(CHAT_BATCH_SECONDS)
            if not self.chat_buffer or self.governor.why_not_speak():
                continue
            batch, self.chat_buffer = self.chat_buffer, []
            try:
                result = await voice.triage(self.governor, batch)
                await self.apply_triage(result)
            except Exception as error:  # noqa: BLE001
                print(f"triage failed: {error}", flush=True)

    async def apply_triage(self, result):
        week = time.strftime("%Y-%W", time.gmtime())
        counts = self.state["intents"].setdefault(week, {})
        accepted = []
        for intent in result.get("intents", []):
            player = intent.get("player", "")
            if intent.get("personal_advantage") or counts.get(player, 0) >= WEEKLY_INTENTS_PER_PLAYER:
                continue
            counts[player] = counts.get(player, 0) + 1
            accepted.append(intent)
        if accepted:
            STATE.mkdir(parents=True, exist_ok=True)
            with (STATE / "intents.jsonl").open("a", encoding="utf-8") as stream:
                for intent in accepted:
                    self.state["intent_count"] += 1
                    stream.write(json.dumps({"at": time.time(), "number": self.state["intent_count"], **intent}) + "\n")
            self.save()
            self.tune_wanted.set()
            self.wake_director.set()
        reply = voice.guard(result.get("reply"), self.briefs())
        if reply:
            await self.bridge.broadcast(voice.styled(reply))

    # Tuning -----------------------------------------------------------------------------------------

    async def tune_from_feedback(self):
        """Feedback that a number can settle shouldn't wait for a builder. Anything else goes on to the director."""
        path = STATE / "intents.jsonl"
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        fresh = [entry for entry in entries if entry.get("number", 0) > self.state["tuner_saw"]]
        if not fresh or not any(FEATURES.glob("*/feature.json")):
            return
        body = "\n".join(llm.untrusted("intent", json.dumps({"number": entry["number"], "wants": entry["wants"]})) for entry in fresh)
        result = await llm.ask(self.governor, "tuner", body, schema=TUNER_SCHEMA, allowed_tools=["mcp__world__world_index", "mcp__world__tune"],
                               mcp_servers={"world": self.workshop.world_server(can_tune=True)}, max_turns=10)
        self.state["tuner_saw"] = fresh[-1]["number"]
        if isinstance(result.structured, dict):
            self.state["handled_intents"] += result.structured.get("handled", [])
        self.save()

    async def tune_loop(self):
        while True:
            await self.tune_wanted.wait()
            self.tune_wanted.clear()
            if self.governor.why_not_build():
                continue
            try:
                await self.tune_from_feedback()
            except Exception as error:  # noqa: BLE001
                print(f"tuning failed: {error}", flush=True)

    # Building ---------------------------------------------------------------------------------------

    async def on_released(self, feature_id, tree):
        manifest = json.loads((tree / "mods/genesis/features" / feature_id / "feature.json").read_text(encoding="utf-8"))
        names = [entry.get("display") for table in ("blocks", "items") for entry in manifest.get(table, {}).values()]
        self.state["released"].extend(name for name in names if name)
        self.state["release_count"] = self.state.get("release_count", 0) + 1
        # What the engine couldn't do goes to the owner, because adding it is reviewed human work.
        if manifest.get("host_requests"):
            STATE.mkdir(parents=True, exist_ok=True)
            with (STATE / "host_requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": time.time(), "feature": feature_id, "requests": manifest["host_requests"]}) + "\n")
        if not self.state["border_open"]:
            await self.bridge.border(OPEN_BORDER)
            self.state["border_open"] = True
        self.save()

    async def next_features(self):
        """Asks the director what's next, once the first list has run out."""
        intents = STATE / "intents.jsonl"
        recent = intents.read_text(encoding="utf-8").splitlines()[-30:] if intents.exists() else []
        handled = set(self.state["handled_intents"])
        body = "\n".join(llm.untrusted("intent", line) for line in recent if json.loads(line).get("number") not in handled) or "(no requests yet)"
        try:
            found = await self.bridge.call("progress")
            self.reached = found.get("reached", [])
            progress = json.dumps(found)
        except (RuntimeError, ConnectionError, TimeoutError):
            progress = "(not available right now)"
        # Includes anyone who joined after the direction was chosen, whose answers can still steer what comes next.
        briefs = "\n".join(llm.untrusted("brief", json.dumps(brief)) for brief in self.briefs())
        unfinished_file = STATE / "unfinished.jsonl"
        unfinished = "\n".join(unfinished_file.read_text(encoding="utf-8").splitlines()[-10:]) if unfinished_file.exists() else "(none)"
        prompt = (f"Player requests:\n{body}\n\nWhat players have found and learned:\n{llm.untrusted('progress', progress)}\n\n"
                  f"What each player privately said they wanted, never to be quoted or attributed:\n{briefs}\n\n"
                  f"Features that couldn't be finished, and why. Ask for these differently, or not at all:\n{unfinished}\n\n"
                  "Read bible/theme.md, bible/stages.yaml and bible/progression.json, look at world_index, then choose the next features.")
        result = await llm.ask(self.governor, "director", prompt, schema=DIRECTOR_SCHEMA, tools=["Read", "Glob", "Grep"],
                               allowed_tools=["Read", "Glob", "Grep", research.TOOL_NAME, "mcp__world__world_index"], cwd=str(workshop.REPO), max_turns=14,
                               mcp_servers={"web": self.research.server(DIRECTOR_RESEARCH), "world": self.workshop.world_server()})
        if result.is_error or not isinstance(result.structured, dict):
            return []
        self.grow_progression(result.structured.get("new_nodes") or [])
        return result.structured.get("features", [])

    def grow_progression(self, new_nodes):
        if not new_nodes:
            return
        graph = progression.read(PROGRESSION)
        merged, refused = progression.merge(graph, new_nodes, world_index.reached_nodes(FEATURES, self.reached))
        for problem in refused:
            print(f"a change to the progression was refused: {problem}", flush=True)
        if merged is not graph:
            progression.save(PROGRESSION, merged)
            workshop.commit_all("The progression grew")

    async def build_one(self, feature):
        try:
            # The id comes from a model and becomes a folder and a branch name.
            if not re.fullmatch(FEATURE_ID, feature["id"]):
                print(f"refusing a feature with a bad id: {feature['id']!r}", flush=True)
                return
            graph = progression.read(PROGRESSION)
            node = feature.get("node")
            if node not in graph["nodes"]:
                print(f"refusing feature {feature['id']}: node {node!r} isn't in the progression", flush=True)
                return
            await self.workshop.build(feature["id"], feature["spec"], node, progression.stage_of(graph, node))
        except Exception as error:  # noqa: BLE001 - one failed feature must not stop the others
            print(f"building {feature['id']} failed: {error}", flush=True)
        finally:
            self.building.discard(feature["id"])
            self.wake_director.set()

    async def build_loop(self):
        while True:
            reason = self.governor.why_not_build()
            if STOP_AFTER_RELEASES and self.state.get("release_count", 0) >= int(STOP_AFTER_RELEASES):
                reason = "the test's release limit is reached"
            if reason or not self.state["direction_chosen"]:
                if reason:
                    print(f"not building: {reason}", flush=True)
                self.wake_director.clear()
                try:
                    await asyncio.wait_for(self.wake_director.wait(), timeout=60)
                except TimeoutError:
                    pass
                continue
            if not self.queue and not self.building and time.time() >= self.director_rest_until:
                self.queue.extend(await self.next_features())
                # This should hardly ever come back empty, because there's always more to build, but asking again every
                # few minutes would use up the day's limit if it did.
                self.director_rest_until = 0 if self.queue else time.time() + DIRECTOR_REST_SECONDS
            while self.queue and len(self.building) < self.governor.builders_allowed():
                feature = self.queue.pop(0)
                self.building.add(feature["id"])
                asyncio.create_task(self.build_one(feature))
            self.wake_director.clear()
            try:
                await asyncio.wait_for(self.wake_director.wait(), timeout=300)
            except TimeoutError:
                pass

    async def opening_loop(self):
        """Holds the small border during the opening, and notices when the interview timer has run out."""
        while True:
            if not self.state["direction_chosen"]:
                await self.maybe_choose_direction()
            await asyncio.sleep(15)

    async def status_loop(self):
        """Notices the owner's in-game kill switch. The game and broker enforce it, and this just stops wasted work."""
        while True:
            try:
                self.governor.owner_stopped = (await self.bridge.call("status"))["agent_disabled"]
                self.reached = (await self.bridge.call("progress")).get("reached", [])
            except (RuntimeError, ConnectionError, TimeoutError) as error:
                print(f"couldn't read the game's status: {error}", flush=True)
            await asyncio.sleep(10)

    async def watch_loop(self):
        """Some things worth remarking on are an absence, so plain code checks for them now and then."""
        while True:
            await asyncio.sleep(WATCH_SECONDS)
            if self.governor.why_not_speak() or not self.state["direction_chosen"]:
                continue
            try:
                progress = await self.bridge.call("progress")
            except (RuntimeError, ConnectionError, TimeoutError):
                continue
            for player, seen in progress.get("online", {}).items():
                event = self.watcher.check_stuck(player, len(seen["found"]) + len(seen["known"]), progress.get("undiscovered", []))
                if event:
                    await self.speak_if_worthwhile(event, player)

    async def run(self):
        workshop.setup_repo()
        await self.bridge.connect()
        readers = asyncio.create_task(self.bridge.run())
        if not self.state["border_open"]:
            await self.bridge.border(OPENING_BORDER)
        # Anyone already online joined while the agent wasn't listening, so they'd never be asked.
        for player in await self.bridge.call("players"):
            name = player["name"] if isinstance(player, dict) else player
            await self.bridge.events.put({"event": "join", "player": name})
        print("agent running", flush=True)
        await asyncio.gather(readers, self.event_loop(), self.chat_loop(), self.build_loop(), self.tune_loop(), self.opening_loop(),
                             self.status_loop(), self.watch_loop())


if __name__ == "__main__":
    asyncio.run(Agent().run())
