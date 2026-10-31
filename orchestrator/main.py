#!/usr/bin/env python3
"""The agent's main loop: plain code that routes events and decides when each role runs."""
import asyncio
import json
import pathlib
import time

from orchestrator import llm, voice, workshop
from orchestrator.bridge import Bridge
from orchestrator.governor import CONTROL, Governor

BIBLE = workshop.REPO / "bible"
STATE = pathlib.Path("/workspace/state")
OPENING = STATE / "opening.json"
DECIDE_AFTER_SECONDS = 20 * 60
OPENING_BORDER = 256
OPEN_BORDER = 59_999_968
CHAT_BATCH_SECONDS = 20
WEEKLY_INTENTS_PER_PLAYER = 20

PHASES_TEMPLATE = """\
# What each phase needs before the next begins. The director tracks this.
phases:
  1:
    name: Early to mid game
    needs: [ores, tools_and_armor, plants_and_food, early_mobs, core_machines]
  2:
    name: Exploration
    needs: [new_biomes, structures, things_to_find_and_do]
  3:
    name: Late game
    needs: [new_worlds, boss_fights, absurd_machines]
"""

DIRECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "phase": {"type": "integer"},
        "features": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "spec": {"type": "string"}}, "required": ["id", "spec"]}},
    },
    "required": ["phase", "features"],
}


class Agent:
    def __init__(self):
        self.governor = Governor()
        self.bridge = Bridge()
        self.watcher = voice.Watcher(self.governor)
        self.workshop = workshop.Workshop(self.governor, self.on_released)
        self.interviews = {}
        self.chat_buffer = []
        self.queue = []
        self.building = set()
        self.wake_director = asyncio.Event()
        self.state = {"direction_chosen": False, "briefs": {}, "first_finished_at": 0, "released": [], "border_open": False,
                      "phase": 1, "intents": {}}
        if OPENING.exists():
            self.state.update(json.loads(OPENING.read_text(encoding="utf-8")))

    def save(self):
        OPENING.parent.mkdir(parents=True, exist_ok=True)
        OPENING.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def briefs(self):
        return list(self.state["briefs"].values())

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
        if reply:
            await self.bridge.whisper(player, reply)
        if interview.finished:
            await self.bridge.capture(player, False)
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
        if self.state["direction_chosen"]:
            return
        roster = self.roster()
        everyone_done = bool(roster) and roster.issubset(self.state["briefs"])
        waited = self.state["first_finished_at"] and time.time() - self.state["first_finished_at"] > DECIDE_AFTER_SECONDS
        called = (CONTROL / "decide_now").exists()
        if everyone_done or waited or called:
            await self.choose_direction()

    async def choose_direction(self):
        print("choosing the direction", flush=True)
        direction = await voice.choose_direction(self.governor, self.briefs())
        if direction is None:
            print("the direction call failed, will try again", flush=True)
            return
        BIBLE.mkdir(parents=True, exist_ok=True)
        (BIBLE / "theme.md").write_text(direction["theme_md"], encoding="utf-8")
        (BIBLE / "persona.md").write_text(direction["persona_md"], encoding="utf-8")
        (BIBLE / "persona_name.txt").write_text(direction["persona_name"], encoding="utf-8")
        (BIBLE / "discovery.md").write_text(direction["discovery_md"], encoding="utf-8")
        (BIBLE / "phases.yaml").write_text(PHASES_TEMPLATE, encoding="utf-8")
        workshop.commit_all("The direction for this world")
        self.queue.extend(direction["phase1_features"])
        self.state["direction_chosen"] = True
        self.save()
        for line in direction["tease"]:
            text = voice.guard(line, self.briefs())
            if text:
                await self.bridge.broadcast(voice.styled(text))
        print(f"direction chosen, {len(self.queue)} features queued", flush=True)
        self.wake_director.set()

    # Events -----------------------------------------------------------------------------------------

    async def handle(self, event):
        kind = event.get("event")
        player = event.get("player", "")
        self.governor.player_seen()
        if self.governor.why_not_speak():
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

    async def event_loop(self):
        while True:
            event = await self.bridge.events.get()
            try:
                await self.handle(event)
            except Exception as error:  # noqa: BLE001 - one bad event must not stop the agent
                print(f"error handling {event.get('event')}: {error}", flush=True)

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
                    stream.write(json.dumps({"at": time.time(), **intent}) + "\n")
            self.save()
            self.wake_director.set()
        reply = voice.guard(result.get("reply"), self.briefs())
        if reply:
            await self.bridge.broadcast(voice.styled(reply))

    # Building ---------------------------------------------------------------------------------------

    async def on_released(self, feature_id, tree):
        manifest = json.loads((tree / "mods/genesis/features" / feature_id / "feature.json").read_text(encoding="utf-8"))
        names = [entry.get("display") for table in ("blocks", "items") for entry in manifest.get(table, {}).values()]
        self.state["released"].extend(name for name in names if name)
        if not self.state["border_open"]:
            await self.bridge.border(OPEN_BORDER)
            self.state["border_open"] = True
        self.save()

    async def next_features(self):
        """Asks the director what's next, once the first list has run out."""
        intents = STATE / "intents.jsonl"
        recent = intents.read_text(encoding="utf-8").splitlines()[-30:] if intents.exists() else []
        body = "\n".join(llm.untrusted("intent", line) for line in recent) or "(no requests yet)"
        prompt = (f"Current phase: {self.state['phase']}. Released so far: {', '.join(self.state['released']) or 'nothing'}.\n\n"
                  f"Player requests:\n{body}\n\nRead bible/theme.md and bible/phases.yaml, then choose the next features. "
                  "If the current phase's needs are all covered, move to the next phase.")
        result = await llm.ask(self.governor, "director", prompt, schema=DIRECTOR_SCHEMA, tools=["Read", "Glob", "Grep"],
                               allowed_tools=["Read", "Glob", "Grep"], cwd=str(workshop.REPO), max_turns=8)
        if result.is_error or not isinstance(result.structured, dict):
            return []
        self.state["phase"] = result.structured.get("phase", self.state["phase"])
        self.save()
        return result.structured.get("features", [])

    async def build_one(self, feature):
        try:
            await self.workshop.build(feature["id"], feature["spec"], self.state["phase"])
        except Exception as error:  # noqa: BLE001 - one failed feature must not stop the others
            print(f"building {feature['id']} failed: {error}", flush=True)
        finally:
            self.building.discard(feature["id"])
            self.wake_director.set()

    async def build_loop(self):
        while True:
            reason = self.governor.why_not_build()
            if reason or not self.state["direction_chosen"]:
                if reason:
                    print(f"not building: {reason}", flush=True)
                await asyncio.sleep(60)
                continue
            if not self.queue and not self.building:
                self.queue.extend(await self.next_features())
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

    async def run(self):
        workshop.setup_repo()
        await self.bridge.connect()
        readers = asyncio.create_task(self.bridge.run())
        if not self.state["border_open"]:
            await self.bridge.border(OPENING_BORDER)
        print("agent running", flush=True)
        await asyncio.gather(readers, self.event_loop(), self.chat_loop(), self.build_loop(), self.opening_loop())


if __name__ == "__main__":
    asyncio.run(Agent().run())
