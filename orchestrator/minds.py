"""A very cheap model decides what mobs with minds do, at the moments the game says matter.

It gets a mob's character and what it remembers, and answers with a choice from that mob's own short list. The game
checks every choice again before doing anything, so all a player can talk a mob into is something it could do anyway.
A mob only knows what its character says, never the world's plans, so it has nothing to give away. When there's no
usage left, mobs go quiet and carry on with plain code.
"""
import json
import pathlib
import re
import time

from orchestrator import llm, voice, wording

STATE = pathlib.Path("/workspace/state")
RUMOURS = STATE / "rumours.jsonl"
MOST_HOPS = 4
RUMOURS_HEARD = 2
RUMOUR_LENGTH = 120
SAY_LENGTH = 140
CRY_LENGTH = 20
MEANINGS = {"follow": "go with them for a while", "flee": "get away from them", "stay": "stay put and watch them", "wander": "go back to what you were doing",
            "lead": "show them the way to somewhere you know", "give": "hand them something you have", "teach": "tell them something you know",
            "attack": "fight them"}
SCHEMA = {"type": "object", "properties": {
    "say": {"type": ["string", "null"]}, "animation": {"type": ["string", "null"]}, "sound": {"type": ["string", "null"]},
    "action": {"type": ["string", "null"]}, "give_item": {"type": ["string", "null"]}, "knowledge": {"type": ["string", "null"]},
    "accept_gift": {"type": "boolean"}, "like": {"type": "integer"}, "rumour": {"type": ["string", "null"]},
    "retold": {"type": ["integer", "null"]}, "move": {"type": ["string", "null"]}}, "required": ["say", "rumour"]}
HAPPENED = {
    "spoken": "{player} spoke to you.",
    "greeted": "{player} came up and nudged you, saying nothing.",
    "offered": "{player} is holding out {item} for you.",
    "hurt": "{player} just hurt you.",
    "noticed": "{player} has come near. You haven't met before.",
    "fight": ("You're fighting {player}. They're {distance:.0f} blocks away with {target_health:.0%} of their health, and you have "
              "{health:.0%} of yours. Choose your next move."),
}


def clean(text, limit):
    """Plain text only, so nothing a model writes can dress itself up as something from the game."""
    return re.sub(r"[§\x00-\x1f]", "", str(text)).strip()[:limit]


def spoken_line(say, mind, briefs):
    """What a mob may really say, given how it speaks. Words can't come from something that only makes cries."""
    speech = mind.get("voice", "words")
    if not say or speech == "silent":
        return None
    if speech == "cries":
        return clean(say, CRY_LENGTH) or None
    return voice.guard(clean(say, SAY_LENGTH), briefs)


def build_prompt(event, rumours):
    mind = event["mind"]
    lines = [f"You are {event['display']}. {mind.get('character', '')}"]
    speech = mind.get("voice", "words")
    lines.append({"silent": "You can't speak. You only move.", "cries": "You don't speak in words. You make cries."}.get(speech, "You can speak."))
    language = wording.family(event.get("language"))
    if language and speech == "words":
        lines.append(f"{event['player']} speaks {wording.LANGUAGES[language]}, so say what you say in that, unless they've spoken to you in another language.")
    lines.append("It's daytime." if event.get("daytime") else "It's night.")
    lines.append(HAPPENED[event["kind"]].format(**{"item": "something", "distance": 0, "target_health": 1, "health": 1, **event}))
    if event.get("text"):
        lines.append(llm.untrusted("player_said", event["text"]))
    if event.get("loved"):
        lines.append("It's something you really love.")
    lines.append(f"How much you trust {event['player']}, from -10 to 10: {event.get('trust', 0)}.")
    if event.get("notes"):
        lines.append("What you remember: " + "; ".join(str(note) for note in event["notes"]))
    actions = [action for action in mind.get("actions", []) if action in MEANINGS]
    if actions:
        lines.append("What you can do (`action`): " + "; ".join(f"{action} ({MEANINGS[action]})" for action in actions))
    if mind.get("stash"):
        lines.append("What you could hand over (`give_item`): " + ", ".join(f"{item.get('name', item['item'])} ({item['item']}), needs trust {item.get('trust', 1)}" for item in mind["stash"]))
    if mind.get("teaches"):
        lines.append("What you could teach (`knowledge`): " + ", ".join(f"{name}, needs trust {needed}" for name, needed in mind["teaches"].items()))
    for field, label in (("animations", "Your animations"), ("sounds", "Your sounds"), ("moves", "Your fight moves")):
        if mind.get(field):
            lines.append(f"{label}: {', '.join(mind[field])}")
    for rumour in rumours:
        lines.append(f"You've overheard, as rumour number {rumour['number']}: {llm.untrusted('rumour', rumour['text'])}")
    return "\n".join(lines)


def to_operation(event, decision, briefs):
    """Turns a decision into the request for the game. Anything a mob doesn't have is dropped here, and refused again there."""
    mind = event["mind"]
    request = {"mob": event["mob"], "player": event["player"]}
    say = spoken_line(decision.get("say"), mind, briefs)
    if say:
        request["say"] = say
    for field, allowed in (("animation", mind.get("animations", [])), ("sound", mind.get("sounds", [])), ("move", mind.get("moves", []))):
        if decision.get(field) in allowed:
            request[field] = decision[field]
    if decision.get("action") in mind.get("actions", []):
        request["action"] = decision["action"]
        if decision.get("give_item"):
            request["give_item"] = str(decision["give_item"])
        if decision.get("knowledge"):
            request["knowledge"] = str(decision["knowledge"])
    if event["kind"] == "offered" and decision.get("accept_gift"):
        request["accept_gift"] = True
        request["item_id"] = event.get("item_id")
    if decision.get("like") in (1, -1):
        request["like"] = decision["like"]
    return request


class Rumours:
    """Things creatures have heard. Each retelling changes it and wears it out, so gossip drifts and then dies away."""

    def __init__(self, path=RUMOURS):
        self.path = path
        self.items = []
        if path.exists():
            self.items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(item) + "\n" for item in self.items), encoding="utf-8")

    def add(self, text, kin, briefs):
        # Rumours are retold to anyone, so the same check applies as to anything else that's said out loud.
        text = voice.guard(clean(text, RUMOUR_LENGTH), briefs)
        if text:
            self.items.append({"number": len(self.items) + 1, "text": text, "kin": kin, "hops": 0, "at": time.time()})
            self._save()

    def for_kin(self, kin):
        """The newest that this kind of creature didn't start or last tell, because nobody gossips to itself."""
        fresh = [item for item in self.items if item["kin"] != kin and item["hops"] < MOST_HOPS]
        return fresh[-RUMOURS_HEARD:]

    def retold(self, number, kin, text):
        for item in self.items:
            if item["number"] == number and item["hops"] < MOST_HOPS:
                item.update(text=text, kin=kin, hops=item["hops"] + 1, at=time.time())
                self._save()
                return


class Minds:
    def __init__(self, governor, bridge, private_words):
        self.governor = governor
        self.bridge = bridge
        self.private_words = private_words
        self.rumours = Rumours()
        self.busy = set()

    async def handle(self, event):
        """Runs beside everything else. A mob already thinking about this player ignores them until it's done, like anyone."""
        key = (event["kin"], event["player"])
        if key in self.busy or self.governor.why_no_mind():
            return
        self.busy.add(key)
        try:
            await self._decide(event)
        except Exception as error:  # noqa: BLE001 - a confused mob must never take anything else down
            print(f"a mob's mind failed: {type(error).__name__}: {error}", flush=True)
        finally:
            self.busy.discard(key)

    async def _decide(self, event):
        _, briefs = self.private_words()
        result = await llm.ask(self.governor, "mind", build_prompt(event, self.rumours.for_kin(event["kin"])), schema=SCHEMA)
        self.governor.record_mind(result.estimate)
        if result.is_error or not isinstance(result.structured, dict):
            return
        decision = result.structured
        request = to_operation(event, decision, briefs)
        answer = await self.bridge.call("mob_act", **request)
        if answer.get("refused"):
            print(f"{event['display']} wasn't allowed: {answer['refused']}", flush=True)
        if decision.get("rumour") and event["kind"] == "spoken":
            self.rumours.add(decision["rumour"], event["kin"], briefs)
        if isinstance(decision.get("retold"), int) and request.get("say"):
            self.rumours.retold(decision["retold"], event["kin"], clean(request["say"], RUMOUR_LENGTH))
        with (STATE / "minds.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": time.time(), "mob": event["display"], "kind": event["kind"], "player": event["player"], "seconds": result.seconds,
                                     "estimate": result.estimate, "did": {key: value for key, value in request.items() if key not in ("mob", "player")}}) + "\n")
