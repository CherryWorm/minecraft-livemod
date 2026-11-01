#!/usr/bin/env python3
"""The agent's main loop: plain code that routes events and decides when each role runs."""
import asyncio
import collections
import json
import os
import pathlib
import re
import time

from orchestrator import feedback, icon, lanes, llm, minds, progression, research, voice, worker_hub, workshop, world_index
from orchestrator.bridge import Bridge
from orchestrator.governor import CONTROL, Governor

BIBLE = workshop.REPO / "bible"
PROGRESSION = workshop.REPO / workshop.PROGRESSION
FEATURES = workshop.REPO / "mods/genesis/features"
STATE = pathlib.Path("/workspace/state")
OPENING = STATE / "opening.json"
ENGINE_UPDATED = "engine_updated"
AGENT_LABEL ="§b[Agent]§r "
HOW_TO_ANSWER = ("§7Please answer me with a private message: type §f/dm§7, a space, then your message, like §f/dm I love exploring§7. "
                 "Only I can see those. You can also click this line to start one.")
OPENING_NOTE = ("§7Until the first new things arrive, the world is small and safe: you can go {radius} blocks from spawn, as far as the glowing wall, "
                "with no monsters and no hunger, and nothing can be broken yet.")
CHAT_BATCH_SECONDS = 20
WEEKLY_INTENTS_PER_PLAYER = 100
CHAT_MEMORY = 12  # Enough of a private chat to follow the conversation, without each reply getting more expensive.
WATCH_SECONDS = 5 * 60
FEATURE_ID = r"[a-z][a-z0-9_]{1,40}"
DIRECTION_RESEARCH = 6
DIRECTOR_RESEARCH = 3
DIRECTOR_REST_SECONDS = 30 * 60
FEEDBACK_PLAN_SECONDS = 10 * 60  # How long new requests can wait for the director, however much is being built.
REQUEST_FEATURES_PER_PLAN = 2  # However many people ask, most of what gets built comes from the world's own plan.
PLAN_SHOWN = 12
BOARD_SECONDS = 20
DECISIONS_REMEMBERED = 150
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
            "id": {"type": "string"}, "node": {"type": "string"}, "spec": {"type": "string"}, "category": {"type": "string", "enum": feedback.CATEGORIES},
            "answers": {"type": "array", "items": {"type": "integer"}}}, "required": ["id", "node", "spec", "category"]}},
        "decisions": {"type": "array", "items": {"type": "object", "properties": {
            "number": {"type": "integer"}, "outcome": {"type": "string", "enum": [feedback.LATER, feedback.DECLINED, feedback.NEEDS_OWNER, "already_there"]}, "why": {"type": "string"}},
            "required": ["number", "outcome", "why"]}},
        "new_nodes": {"type": "array", "items": NODE_SCHEMA},
    },
    "required": ["features", "decisions"],
}

SORTER_SCHEMA = {"type": "object", "properties": {"decisions": {"type": "array", "items": {"type": "object", "properties": {
    "numbers": {"type": "array", "items": {"type": "integer"}}, "action": {"type": "string", "enum": ["changed", "small", "declined", "plan"]},
    "id": {"type": "string"}, "node": {"type": "string"}, "spec": {"type": "string"}, "title": {"type": "string"}, "why": {"type": "string"}}, "required": ["numbers", "action"]}}}, "required": ["decisions"]}
SORTER_TOOLS = ["mcp__world__world_index", "mcp__world__tune", "mcp__world__set_rule"]


class Agent:
    def __init__(self):
        self.governor = Governor()
        self.bridge = Bridge()
        self.watcher = voice.Watcher(self.governor)
        self.research = research.Research(self.governor, self.private_words)
        self.minds = minds.Minds(self.governor, self.bridge, self.private_words)
        self.workshop = workshop.Workshop(self.governor, self.on_released, self.research, lambda: self.reached)
        self.self_hosted = lanes.SelfHosted()
        if self.self_hosted.lane:
            self.workshop.lanes[lanes.SELF_HOSTED] = self.self_hosted.lane
        self.hub = worker_hub.WorkerHub(workshop.REPO, workshop.request, self.governor, lambda: self.reached)
        self.workshop.hub = self.hub
        self.told_about_dm = set()
        self.chat_buffer = []
        self.wake_director = asyncio.Event()
        self.sort_wanted = asyncio.Event()
        self.sort_wanted.set()  # There may be requests from before a restart.
        self.planning = False
        self.last_planned = 0
        self.director_rest_until = 0
        self.reached = []
        self.locks = {}
        self.choosing_direction = False
        self.direction_problems = []
        self.state = {"direction_chosen": False, "briefs": {}, "released": [], "border_open": False,
                      "intents": {}, "intent_count": 0, "interviews": {}, "private_chats": {}, "requests": {}, "sorted_up_to": 0, "director_saw": 0,
                      "notices": {}, "queue": [], "in_flight": {}}
        if OPENING.exists():
            self.state.update(json.loads(OPENING.read_text(encoding="utf-8")))
        self.interviews = {player: voice.Interview(self.governor, player, saved) for player, saved in self.state["interviews"].items()}
        self.requests = feedback.Requests(STATE / "intents.jsonl", self.state["requests"])
        # Saved, so a restart costs as little as possible. What it interrupted goes first, and its work so far is still in its folder.
        self.queue = self.state["queue"]
        self.building = self.state["in_flight"]
        self.queue[:0] = list(self.building.values())
        self.building.clear()

    def save(self):
        self.state["interviews"] = {player: interview.saved() for player, interview in self.interviews.items()}
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

    async def tell(self, player, text, reply_click=False):
        """They may have left while a slow reply was on its way. Anything said in an interview is saved for when they're back."""
        try:
            await self.bridge.whisper(player, text, reply_click)
        except RuntimeError as error:
            print(f"couldn't tell {player} something: {error}", flush=True)

    async def explain(self, player):
        await self.tell(player, HOW_TO_ANSWER, reply_click=True)
        opening = (await self.bridge.call("status")).get("opening")
        if opening:
            await self.tell(player, OPENING_NOTE.format(radius=opening // 2))

    async def start_interview(self, player):
        interview = voice.Interview(self.governor, player)
        self.interviews[player] = interview
        reply = await interview.begin()
        self.save()
        await self.tell(player, AGENT_LABEL + reply, reply_click=True)
        await self.explain(player)

    async def resume_interview(self, player):
        """Costs nothing and needs no model, because all it does is remind them where things stand."""
        await self.tell(player, "§7Welcome back. We're still in the middle of our private talk, and this is where we'd got to:")
        await self.tell(player, AGENT_LABEL + self.interviews[player].last_question(), reply_click=True)
        await self.explain(player)

    async def on_dm(self, player, text):
        interview = self.interviews.get(player)
        if interview is not None:
            await self.interview_turn(player, interview, text)
        elif player in self.state["briefs"]:
            await self.private_turn(player, text)
        else:
            await self.start_interview(player)

    async def private_turn(self, player, text):
        chat = self.state["private_chats"].setdefault(player, [])
        chat.append({"from": "player", "text": text})
        del chat[:-CHAT_MEMORY]
        in_character = self.state["direction_chosen"]
        try:
            result = await voice.private_reply(self.governor, chat, in_character, await self.what_they_have(player))
        except Exception as error:  # noqa: BLE001 - they're waiting for an answer, so even a failed call needs one
            print(f"a private reply failed: {error}", flush=True)
            result = None
        reply = voice.guard(result.get("reply"), self.briefs(), voice.HELP_LIMIT) if result else None
        if reply:
            chat.append({"from": "you", "text": reply})
        self.save()
        if result:
            self.record_intents([{**intent, "player": player} for intent in result.get("intents", [])])
        if not reply:
            await self.tell(player, "§7Sorry, I couldn't answer that just now. Please try again.", reply_click=True)
        else:
            await self.tell(player, voice.styled(reply) if in_character else AGENT_LABEL + reply, reply_click=True)

    async def what_they_have(self, player):
        """So advice can be about their next step. An answer without the game's part still beats no answer."""
        known = {"what_they_asked_for": self.requests.of_player(player), "being_built_now": self.described(self.building.values()), "waiting_to_be_built": self.described(self.queue)}
        try:
            progress = await self.bridge.call("progress")
        except (RuntimeError, ConnectionError, TimeoutError):
            return known
        return {**known, **progress.get("online", {}).get(player, {}), "nobody_has_worked_out": progress.get("undiscovered", [])}

    # What players hear back -------------------------------------------------------------------------

    def described(self, features):
        graph = progression.read(PROGRESSION)
        return [feedback.describe(feature, graph) for feature in features]

    async def show_plan(self, player):
        """/plan, for anyone. Plain code writes it, so that nothing can be spoiled by a model getting carried away."""
        now, waiting = self.described(self.building.values()), self.described(self.queue)
        shown = ", ".join(waiting[:PLAN_SHOWN]) + (f", and {len(waiting) - PLAN_SHOWN} more" if len(waiting) > PLAN_SHOWN else "")
        await self.tell(player, f"§7Being built right now: §f{', '.join(now) or 'nothing'}")
        await self.tell(player, f"§7Up next, in order: §f{shown or 'nothing yet'}" + (" §7(more being planned)" if self.planning else ""))
        await self.tell(player, f"§7Out so far: §f{self.state.get('release_count', 0)} §7things. Ask about any of it with §f/dm§7, or keep the numbers on screen with §f/board§7.", reply_click=True)

    async def deliver(self, player, text):
        """They may have logged off, in which case it waits for them."""
        try:
            await self.bridge.whisper(player, text, True)
        except (RuntimeError, ConnectionError, TimeoutError):
            self.state["notices"].setdefault(player, []).append(text)
            self.save()

    async def deliver_waiting(self, player):
        waiting = self.state["notices"].pop(player, [])
        if waiting:
            self.save()
        for text in waiting:
            await self.deliver(player, text)

    async def send_news(self, news):
        """Takes (request, outcome, why) and tells each player once, however much was decided at the same time."""
        by_player = {}
        for entry, outcome, why in news:
            by_player.setdefault(entry.get("player", ""), []).append({"wanted": entry["wants"], "outcome": outcome, **({"why": why} if why else {})})
        for player, items in by_player.items():
            try:
                text = await voice.request_news(self.governor, items, self.briefs())
            except Exception as error:  # noqa: BLE001 - the plain version below still tells them
                print(f"writing the news failed: {error}", flush=True)
                text = None
            plain = "§7About what you asked for: " + "; ".join(f"{item['wanted']}: {item['outcome'].replace('_', ' ')}" for item in items)
            await self.deliver(player, voice.styled(text) if text else plain[:voice.HELP_LIMIT])

    async def interview_turn(self, player, interview, text):
        reply = await interview.turn(text)
        self.save()
        # They're waiting for an answer, so even a failed call needs one.
        await self.tell(player, AGENT_LABEL + (reply or "§7Sorry, I didn't catch that. Could you say it again?"), reply_click=True)
        if interview.finished:
            await self.tell(player, "§7That's all I needed, thanks. If you get stuck or want to tell me anything else, §f/dm§7 still works, and I'll answer. §f/plan§7 shows what's being built.")
            self.state["briefs"][player] = interview.brief
            del self.interviews[player]
            self.save()
            self._store_brief(player, interview.brief)

    def _store_brief(self, player, brief):
        folder = STATE / "briefs"  # Outside the agent's repo, so no builder ever reads one directly.
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{player}.json").write_text(json.dumps(brief, indent=1), encoding="utf-8")

    async def maybe_choose_direction(self):
        """Only ever on the owner's go-ahead. Until then, everyone who joins just gets asked what they'd like."""
        if self.state["direction_chosen"] or self.choosing_direction or not (CONTROL / "decide_now").exists():
            return
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
        self.sort_wanted.set()  # What was said before there was a direction can be dealt with now.
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
            if kind in ("dm", "plan"):
                await self.tell(player, "§7I can't answer right now, so I haven't read that. Please try again later.")
            return
        if kind == "join":
            self.told_about_dm.discard(player)
            if player in self.interviews:
                await self.resume_interview(player)
            elif player not in self.state["briefs"]:
                await self.start_interview(player)
            await self.deliver_waiting(player)
        elif kind == "dm":
            await self.on_dm(player, event.get("text", ""))
        elif kind == "plan":
            await self.show_plan(player)
        elif kind == "chat":
            text = event.get("text", "")
            if text.strip().lower() in ("!mute", "!unmute"):
                await self.set_muted(player, text.strip().lower() == "!mute")
            else:
                self.chat_buffer.append({"player": player, "text": text})
                if player in self.interviews and player not in self.told_about_dm:
                    self.told_about_dm.add(player)
                    await self.tell(player, "§7That went to everyone. To answer me privately, use §f/dm§7 instead.", reply_click=True)
        await self.speak_if_worthwhile(event, player)

    async def speak_if_worthwhile(self, event, player):
        # Nobody's met the character until the direction exists, so before then there's no one to speak.
        if not self.state["direction_chosen"]:
            return
        said = await self.watcher.consider(event, self.briefs())
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
        self.record_intents(result.get("intents", []))
        # Nobody's met the character until the direction exists, so before then there's no one to answer.
        reply = voice.guard(result.get("reply"), self.briefs(), voice.HELP_LIMIT) if self.state["direction_chosen"] else None
        if reply:
            await self.bridge.broadcast(voice.styled(reply))

    def record_intents(self, intents):
        week = time.strftime("%Y-%W", time.gmtime())
        counts = self.state["intents"].setdefault(week, {})
        accepted = []
        for intent in intents:
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
            self.sort_wanted.set()
            self.wake_director.set()

    # Sorting requests -------------------------------------------------------------------------------

    def work_list(self):
        work = [*self.building.values(), *self.queue]
        return "\n".join(llm.untrusted("work", f"{feature['id']}: {feature.get('spec', '')[:200]}") for feature in work) or "(nothing)"

    def decided_so_far(self):
        decided = self.requests.decided()[-DECISIONS_REMEMBERED:]
        return "\n".join(llm.untrusted("decided", json.dumps(entry)) for entry in decided) or "(nothing yet)"

    def can_build(self, feature):
        # The id comes from a model and becomes a folder and a branch name.
        return (re.fullmatch(FEATURE_ID, feature.get("id") or "") and feature.get("spec")
                and feature.get("node") in progression.read(PROGRESSION)["nodes"])

    async def sort_requests(self):
        """The director's fast look at anything new, on a faster model but with the same rules and the same record of what
        it's decided. A number or a server rule changes on the spot, a small job gets its own small builder, and anything
        that needs the whole picture waits for the next time it plans."""
        fresh = self.requests.unanswered_after(self.state["sorted_up_to"])
        if not fresh or not self.state["direction_chosen"]:
            return
        body = "\n".join(llm.untrusted("intent", json.dumps({"number": entry["number"], "wants": entry["wants"]})) for entry in fresh)
        theme = (BIBLE / "theme.md").read_text(encoding="utf-8") if (BIBLE / "theme.md").exists() else ""
        prompt = (f"What players have just asked for:\n{body}\n\nThe world's theme:\n{theme}\n\nWhat's being built or waiting to be built:\n{self.work_list()}\n\n"
                  f"What you've already decided:\n{self.decided_so_far()}")
        changes_before = self.workshop.changes
        try:
            result = await llm.ask(self.governor, "director_quick", prompt, system=llm.prompt_text("director") + "\n\n" + llm.prompt_text("director_quick"), schema=SORTER_SCHEMA,
                                   allowed_tools=SORTER_TOOLS, mcp_servers={"world": self.workshop.world_server(can_tune=True)}, max_turns=20)
            decisions = result.structured.get("decisions", []) if isinstance(result.structured, dict) and not result.is_error else []
        finally:
            # If this fails, the director still sees them, because a request only leaves its list by being decided.
            self.state["sorted_up_to"] = fresh[-1]["number"]
        known = {entry["number"]: entry for entry in fresh}
        news = []
        for decision in decisions:
            numbers = [number for number in decision.get("numbers", []) if number in known]
            if not numbers:
                continue
            if decision.get("action") == "changed" and self.workshop.changes > changes_before:
                for number in numbers:
                    self.requests.mark(number, feedback.DONE, why=decision.get("why", ""))
                    news.append((known[number], feedback.DONE, decision.get("why", "")))
            elif decision.get("action") == "declined" and decision.get("why"):
                for number in numbers:
                    self.requests.mark(number, feedback.DECLINED, why=decision["why"])
                    news.append((known[number], feedback.DECLINED, decision["why"]))
            elif decision.get("action") == "small" and self.can_build(decision):
                self.queue.insert(0, {"id": decision["id"], "node": decision["node"], "spec": decision["spec"], "title": decision.get("title"), "answers": numbers, "small": True})
                for number in numbers:
                    self.requests.mark(number, feedback.BUILDING, feature=decision["id"])
                    news.append((known[number], feedback.BUILDING, ""))
                print(f"{decision['id']}: a small job, for requests {numbers}", flush=True)
        self.save()
        await self.send_news(news)

    async def sort_loop(self):
        while True:
            await self.sort_wanted.wait()
            if self.governor.why_not_build():
                await asyncio.sleep(60)  # Still wanted, for whenever building can go ahead again.
                continue
            try:
                await self.sort_requests()
            except Exception as error:  # noqa: BLE001
                print(f"sorting requests failed: {error}", flush=True)
            # Cleared only now, because the director shouldn't start on something this might be about to take.
            self.sort_wanted.clear()
            self.wake_director.set()

    # Building ---------------------------------------------------------------------------------------

    @staticmethod
    def tell_owner(source, requests):
        """What the engine can't do goes to the owner, because adding it is reviewed human work."""
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / "host_requests.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "feature": source, "requests": requests}) + "\n")

    async def on_released(self, feature_id, tree):
        manifest = json.loads((tree / "mods/genesis/features" / feature_id / "feature.json").read_text(encoding="utf-8"))
        names = [entry.get("display") for table in ("blocks", "items") for entry in manifest.get(table, {}).values()]
        self.state["released"].extend(name for name in names if name)
        self.state["release_count"] = self.state.get("release_count", 0) + 1
        if manifest.get("host_requests"):
            self.tell_owner(feature_id, manifest["host_requests"])
        finished = self.requests.for_feature(feature_id)
        for entry in finished:
            self.requests.mark(entry["number"], feedback.DONE, feature=feature_id)
        self.save()
        await self.open_world()
        await self.send_news([(entry, feedback.DONE, "") for entry in finished])

    async def open_world(self):
        """The first thing to reach players starts the game proper. A release can restart the server, so this may
        have to wait for it, and the opening loop keeps trying."""
        if self.state["border_open"] or not self.state.get("release_count"):
            return
        try:
            await self.bridge.call("open_world")
        except (RuntimeError, ConnectionError, TimeoutError) as error:
            print(f"couldn't open the world yet: {error}", flush=True)
            return
        self.state["border_open"] = True
        self.save()

    async def next_features(self):
        """Asks the director what's next, and what to do about everything players have asked for."""
        if self.engine_updated():
            self.state["engine_updated"] = (CONTROL / ENGINE_UPDATED).stat().st_mtime
            self.requests.ask_again()
        undecided = {entry["number"]: entry for entry in self.requests.undecided()}
        saw = self.requests.last_number()
        body = "\n".join(llm.untrusted("intent", json.dumps({"number": number, "player": entry.get("player"), "wants": entry["wants"], "status": self.requests.status(number) or "new",
                                                             **({"owner_asked": True} if entry.get("owner_asked") else {})}))
                         for number, entry in undecided.items()) or "(no requests waiting)"
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
        prompt = (f"Player requests:\n{body}\n\n{self.waiting()} features are waiting to be built, and {self.governor.builders_allowed()} can be built at once.\n\n"
                  f"Being built or waiting to be built, so don't ask for these again:\n{self.work_list()}\n\n"
                  f"What you've already decided, so be consistent with it and don't build anything twice:\n{self.decided_so_far()}\n\n"
                  f"What players have found and learned:\n{llm.untrusted('progress', progress)}\n\n"
                  f"What each player privately said they wanted, never to be quoted or attributed:\n{briefs}\n\n"
                  f"Features that couldn't be finished, and why. Ask for these differently, or not at all:\n{unfinished}\n\n"
                  "Read bible/theme.md, bible/stages.yaml and bible/progression.json, look at world_index, then choose the next features.")
        result = await llm.ask(self.governor, "director", prompt, schema=DIRECTOR_SCHEMA, tools=["Read", "Glob", "Grep"],
                               allowed_tools=["Read", "Glob", "Grep", research.TOOL_NAME, "mcp__world__world_index"], cwd=str(workshop.REPO), max_turns=14,
                               mcp_servers={"web": self.research.server(DIRECTOR_RESEARCH), "world": self.workshop.world_server()})
        if result.is_error or not isinstance(result.structured, dict):
            return []
        self.grow_progression(result.structured.get("new_nodes") or [])
        self.state["director_saw"] = saw
        news = []
        for decision in result.structured.get("decisions", []):
            number, outcome = decision.get("number"), decision.get("outcome")
            if number not in undecided or outcome not in (feedback.LATER, feedback.DECLINED, feedback.NEEDS_OWNER, "already_there"):
                continue
            before = self.requests.status(number)
            # Someone looking at it again and coming to the same answer isn't news to the owner or the player.
            still_needs_owner = outcome == feedback.NEEDS_OWNER and before == feedback.ASK_AGAIN
            if outcome == feedback.NEEDS_OWNER and not still_needs_owner:
                self.tell_owner(f"request {number}", [f"{undecided[number]['wants']}: {decision.get('why', '')}"])
            # It'll keep coming back as later, and they only need to hear that once.
            if not still_needs_owner and not (outcome == feedback.LATER and before == feedback.LATER):
                news.append((undecided[number], outcome, decision.get("why", "")))
            self.requests.mark(number, feedback.DONE if outcome == "already_there" else outcome, why=decision.get("why", ""))
        taken = {feature["id"] for feature in [*self.queue, *self.building.values()]}
        features = []
        from_requests = 0
        for feature in result.structured.get("features", []):
            if feature.get("id") in taken:
                continue
            answers = [number for number in feature.get("answers", []) if number in undecided]
            # The rest of its requests stay undecided, so they come back next time. The owner's own don't count.
            owners = any(undecided[number].get("owner_asked") for number in answers)
            if answers and not owners and from_requests >= REQUEST_FEATURES_PER_PLAN:
                continue
            from_requests += bool(answers) and not owners
            for number in answers:
                self.requests.mark(number, feedback.BUILDING, feature=feature["id"])
                news.append((undecided[number], feedback.BUILDING, ""))
            features.append({**feature, "answers": answers})
        self.save()
        await self.send_news(news)
        return features

    async def plan(self):
        """A director's call can take minutes, and building doesn't stop for it. What it chooses waits its turn, because
        the world's plan comes first. It's small jobs that go to the front, and they have slots of their own."""
        try:
            features = await self.next_features()
            self.queue.extend(features)
            # This should hardly ever come back empty, because there's always more to build, but asking again every
            # few minutes would use up the day's limit if it did.
            self.director_rest_until = 0 if features else time.time() + DIRECTOR_REST_SECONDS
        except Exception as error:  # noqa: BLE001 - it'll be asked again
            print(f"planning failed: {error}", flush=True)
            self.director_rest_until = time.time() + DIRECTOR_REST_SECONDS
        finally:
            self.planning = False
            self.last_planned = time.time()
            self.save()
            self.wake_director.set()

    def waiting(self):
        return sum(not feature.get("small") for feature in self.queue)

    def out_of_work(self):
        """Fewer waiting than can be built at once, so the director plans ahead rather than leaving builders idle until everything's finished."""
        return self.waiting() < self.big_slots()

    def running_on(self):
        return collections.Counter(feature.get("lane") for feature in self.building.values() if not feature.get("small"))

    def big_slots(self):
        return self.governor.builders_allowed() + self.self_hosted.slots * bool(self.self_hosted.lane) + self.running_on()[lanes.REMOTE] + self.hub.free_slots()

    def lane_with_room(self):
        """Claude first, so that what's being built now is as good as it was, and anything else takes what's left over. A warning
        from the plan leaves Claude's builders with less room, so more work moves over by itself. False means nowhere has room."""
        running = self.running_on()
        if running[None] < self.governor.builders_allowed():
            return None
        if self.self_hosted.lane and running[lanes.SELF_HOSTED] < self.self_hosted.slots:
            return lanes.SELF_HOSTED
        if self.hub.free_slots() > 0:
            return lanes.REMOTE
        return False

    def engine_updated(self):
        """The owner's way of saying the engine can do more than it could. It's the file's time that counts, because the agent can only read that folder, so touching it again works again."""
        marker = CONTROL / ENGINE_UPDATED
        return marker.exists() and marker.stat().st_mtime != self.state.get("engine_updated")

    def should_plan(self):
        # While requests are being sorted, some of them may be about to become small jobs.
        if self.planning or self.sort_wanted.is_set():
            return False
        if self.engine_updated():
            return True
        if self.out_of_work() and time.time() >= self.director_rest_until:
            return True
        return bool(self.requests.unanswered_after(self.state["director_saw"])) and time.time() - self.last_planned >= FEEDBACK_PLAN_SECONDS

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
        shipped = False
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
            shipped = await self.workshop.build(feature["id"], feature["spec"], node, progression.stage_of(graph, node), small=feature.get("small", False), lane=feature.get("lane"))
        except Exception as error:  # noqa: BLE001 - one failed feature must not stop the others
            print(f"building {feature['id']} failed: {error}", flush=True)
        finally:
            del self.building[feature["id"]]
            if shipped is None:
                self.queue.insert(0, feature)  # It had to stop for now, not because of anything wrong with it.
            elif not shipped:
                # Nobody's going to deliver it after all, so the director gets to decide again, soon.
                for entry in self.requests.for_feature(feature["id"]):
                    self.requests.reopen(entry["number"])
                    self.state["director_saw"] = min(self.state["director_saw"], entry["number"] - 1)
            self.save()
            self.wake_director.set()

    def start_work(self):
        """Small jobs have slots of their own, so that one never waits behind a big feature."""
        def start(feature, lane):
            self.queue.remove(feature)
            feature["lane"] = lane
            self.building[feature["id"]] = feature
            asyncio.create_task(self.build_one(feature))

        running = sum(bool(feature.get("small")) for feature in self.building.values())
        for feature in [feature for feature in self.queue if feature.get("small")]:
            if running >= self.governor.small_builders_allowed():
                break
            if feature["id"] not in self.building:
                start(feature, None)
                running += 1
        for feature in [feature for feature in self.queue if not feature.get("small")]:
            lane = self.lane_with_room()
            if lane is False:
                break
            if feature["id"] not in self.building:
                start(feature, lane)
        self.save()

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
            if self.should_plan():
                self.planning = True
                asyncio.create_task(self.plan())
            self.start_work()
            self.wake_director.clear()
            try:
                await asyncio.wait_for(self.wake_director.wait(), timeout=300)
            except TimeoutError:
                pass

    async def opening_loop(self):
        """Notices the owner's go-ahead, and that the opening is due to end."""
        while True:
            if not self.state["direction_chosen"]:
                await self.maybe_choose_direction()
            await self.open_world()
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
                event = self.watcher.check_stuck(player, len(seen["found"]) + len(seen["known"]), progress.get("undiscovered", []), seen["found"])
                if event:
                    await self.speak_if_worthwhile(event, player)

    async def name_what_is_being_built(self, graph):
        """Once each, and only for what's really being built, so that this stays cheap."""
        for feature in list(self.building.values()):
            if feature.get("small") or "teaser" in feature or self.governor.why_not_speak():
                continue
            node = graph.get("nodes", {}).get(feature.get("node"), {})
            feature["teaser"] = await voice.teaser(self.governor, feature, feedback.STAGE_WORDS.get(node.get("stage"), "unknown"))
            self.save()

    async def board_loop(self):
        """Keeps the sidebar current for whoever has it on. Plain code does the counting, and if this stops, the game says so."""
        problem = None
        while True:
            graph = progression.read(PROGRESSION)
            await self.name_what_is_being_built(graph)
            try:
                await self.bridge.call("board", shipped=self.state.get("release_count", 0), building=len(self.building), queued=len(self.queue),
                                       now=[feedback.board_line(feature, graph) for feature in self.building.values()])
                problem = None
            except (RuntimeError, ConnectionError, TimeoutError) as error:
                if str(error) != problem:
                    print(f"couldn't update the build board: {error}", flush=True)
                problem = str(error)
            await asyncio.sleep(BOARD_SECONDS)

    async def run(self):
        workshop.setup_repo()
        await self.bridge.connect()
        readers = asyncio.create_task(self.bridge.run())
        # Anyone already online joined while the agent wasn't listening, so they'd never be asked.
        for player in await self.bridge.call("players"):
            name = player["name"] if isinstance(player, dict) else player
            await self.bridge.events.put({"event": "join", "player": name})
        print("agent running", flush=True)
        await asyncio.gather(readers, self.event_loop(), self.chat_loop(), self.build_loop(), self.sort_loop(), self.opening_loop(),
                             self.status_loop(), self.watch_loop(), self.board_loop(), self.self_hosted.serve(), self.hub.serve())


if __name__ == "__main__":
    asyncio.run(Agent().run())
