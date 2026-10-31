"""Everything the agent says to players: interviews, the direction, chat replies and unprompted remarks.

None of these roles get shell or file tools. They receive text and return JSON, so the worst a malicious
chat message can do is make the character say something odd. Outgoing text then passes through
guard(), which stops anything quoting a private brief.
"""
import json
import pathlib
import re
import time

from orchestrator import llm
from orchestrator.governor import Governor

BIBLE = pathlib.Path("/workspace/repo/bible")
STATE = pathlib.Path("/workspace/state")

INTERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "finished": {"type": "boolean"},
        "brief": {
            "type": "object",
            "properties": {
                "wants": {"type": "string"},
                "theme_ideas": {"type": "string"},
                "mods_enjoyed": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"}, "why": {"type": "string"}}, "required": ["name", "why"]}},
                "dislikes": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["wants", "theme_ideas", "mods_enjoyed", "dislikes", "notes"],
        },
    },
    "required": ["reply", "finished"],
}

DIRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "theme_md": {"type": "string"},
        "persona_name": {"type": "string"},
        "persona_md": {"type": "string"},
        "discovery_md": {"type": "string"},
        "discovery_scope": {"type": "string", "enum": ["shared", "per_player"]},
        "tease": {"type": "array", "items": {"type": "string"}},
        "phase1_features": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "spec": {"type": "string"}}, "required": ["id", "spec"]}},
    },
    "required": ["theme_md", "persona_name", "persona_md", "discovery_md", "discovery_scope", "tease", "phase1_features"],
}

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "intents": {"type": "array", "items": {"type": "object", "properties": {
            "player": {"type": "string"}, "wants": {"type": "string"}, "personal_advantage": {"type": "boolean"}},
            "required": ["player", "wants", "personal_advantage"]}},
        "reply": {"type": ["string", "null"]},
    },
    "required": ["intents", "reply"],
}

WATCHER_SCHEMA = {
    "type": "object",
    "properties": {
        "say": {"type": ["string", "null"]},
        "audience": {"type": "string", "enum": ["whisper", "broadcast"]},
    },
    "required": ["say", "audience"],
}


def guard(text, briefs):
    """Blocks a message that repeats a distinctive phrase from someone's private interview answers."""
    if not text:
        return None
    lowered = text.lower()
    for brief in briefs:
        for value in (brief.get("wants", ""), brief.get("theme_ideas", ""), brief.get("dislikes", ""), brief.get("notes", "")):
            words = re.findall(r"[a-z']+", value.lower())
            for start in range(0, max(0, len(words) - 4)):
                if " ".join(words[start:start + 5]) in lowered:
                    return None
    return text[:256]


class Interview:
    """One private conversation with one player. Each turn resumes the same session."""

    def __init__(self, governor: Governor, player):
        self.governor = governor
        self.player = player
        self.session = None
        self.finished = False
        self.brief = None
        self.turns = 0

    async def turn(self, player_text):
        self.turns += 1
        prompt = llm.untrusted("player_message", player_text)
        if self.turns >= 6:
            prompt += "\n\nThis is the last exchange. Finish now."
        result = await llm.ask(self.governor, "interviewer", prompt, schema=INTERVIEW_SCHEMA, resume=self.session, max_turns=3)
        self.session = result.session_id or self.session
        data = result.structured if isinstance(result.structured, dict) else None
        if result.is_error or data is None:
            return None
        if data.get("finished"):
            self.finished = True
            self.brief = data.get("brief") or {"wants": "", "theme_ideas": "", "mods_enjoyed": [], "dislikes": "", "notes": ""}
        return data.get("reply")


async def choose_direction(governor, briefs, web):
    blocks = "\n\n".join(llm.untrusted("brief", json.dumps(brief, indent=1)) for brief in briefs)
    prompt = (blocks or "No player gave a brief. Choose a direction you think friends would enjoy.") + \
        "\n\nChoose this world's direction."
    result = await llm.ask(governor, "direction", prompt, schema=DIRECTION_SCHEMA, allowed_tools=["mcp__web__research"],
                           mcp_servers={"web": web}, max_turns=10)
    return result.structured if isinstance(result.structured, dict) and not result.is_error else None


def persona():
    path = BIBLE / "persona.md"
    return path.read_text(encoding="utf-8") if path.exists() else "A mysterious, watchful presence."


def persona_name():
    path = BIBLE / "persona_name.txt"
    return path.read_text(encoding="utf-8").strip() if path.exists() else "?"


def styled(text):
    """How the character's words look in chat."""
    return f"§d{persona_name()}§r: {text}"


async def triage(governor, messages):
    body = "\n".join(llm.untrusted("player_message", f"{item['player']}: {item['text']}") for item in messages)
    result = await llm.ask(governor, "triage", body, system=llm.prompt_text("triage") + persona(), schema=TRIAGE_SCHEMA, max_turns=3)
    return result.structured if isinstance(result.structured, dict) and not result.is_error else {"intents": [], "reply": None}


class Watcher:
    """Plain code decides when something's worth a remark. The model only runs after that."""

    PER_PLAYER_COOLDOWN = 10 * 60
    PER_HOUR_LIMIT = 6
    NO_PROGRESS_SECONDS = 45 * 60

    def __init__(self, governor):
        self.governor = governor
        self.muted = set()
        self.last_spoke = {}
        self.spoken_times = []
        self.deaths = {}
        self.seen_before = set()
        self.last_seen = {}
        self.progress = {}
        self._load()

    def _path(self):
        return STATE / "watcher.json"

    def _load(self):
        if self._path().exists():
            data = json.loads(self._path().read_text(encoding="utf-8"))
            self.seen_before = set(data.get("seen_before", []))
            self.muted = set(data.get("muted", []))
            self.last_seen = data.get("last_seen", {})

    def _save(self):
        self._path().parent.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps({
            "seen_before": sorted(self.seen_before), "muted": sorted(self.muted), "last_seen": self.last_seen}), encoding="utf-8")

    def trigger_for(self, event):
        """Turns a game event into a reason to speak, or None if it isn't interesting."""
        kind = event.get("event")
        player = event.get("player", "")
        now = time.time()
        if kind == "join":
            away = now - self.last_seen.get(player, now)
            first = player not in self.seen_before
            self.seen_before.add(player)
            self.last_seen[player] = now
            self._save()
            if first:
                return None  # The interview handles a first arrival.
            if away > 6 * 3600:
                return f"{player} has come back after {away / 3600:.0f} hours away"
            return None
        if kind == "leave":
            self.last_seen[player] = now
            self._save()
            return None
        if kind == "death":
            recent = [stamp for stamp in self.deaths.get(player, []) if now - stamp < 900] + [now]
            self.deaths[player] = recent
            if len(recent) >= 3:
                return f"{player} has died {len(recent)} times in the last few minutes, most recently from {event.get('cause')}"
            return None
        if kind == "stuck":
            return f"{player} hasn't found anything new for a while. Not yet worked out by anyone: {', '.join(event.get('undiscovered', [])) or 'nothing'}"
        if kind == "discovery":
            return f"{player} just found something for the first time: {event.get('what')}"
        if kind == "milestone":
            return f"The players reached a milestone: {event.get('what')}"
        return None

    def check_stuck(self, player, known_count, undiscovered):
        """Returns an event if this player has gone a long time without finding anything new."""
        now = time.time()
        count, since = self.progress.get(player, (-1, now))
        if known_count != count:
            self.progress[player] = (known_count, now)
            return None
        if now - since < self.NO_PROGRESS_SECONDS:
            return None
        self.progress[player] = (known_count, now)
        return {"event": "stuck", "player": player, "undiscovered": undiscovered[:5]}

    def allowed(self, player):
        now = time.time()
        if player in self.muted:
            return False
        self.spoken_times = [stamp for stamp in self.spoken_times if now - stamp < 3600]
        if len(self.spoken_times) >= self.PER_HOUR_LIMIT:
            return False
        return now - self.last_spoke.get(player, 0) >= self.PER_PLAYER_COOLDOWN

    async def consider(self, event, released, briefs):
        """Returns (text, audience) if the character should speak, otherwise None."""
        reason = self.trigger_for(event)
        player = event.get("player", "")
        if reason is None or not self.allowed(player):
            return None
        prompt = llm.untrusted("event", reason) + "\n\nReleased so far: " + (", ".join(released) or "nothing yet")
        result = await llm.ask(self.governor, "watcher", prompt, system=llm.prompt_text("watcher") + persona(),
                               schema=WATCHER_SCHEMA, max_turns=3)
        data = result.structured if isinstance(result.structured, dict) and not result.is_error else None
        if not data or not data.get("say"):
            return None
        text = guard(data["say"], briefs)
        if text is None:
            return None
        self.last_spoke[player] = time.time()
        self.spoken_times.append(time.time())
        return text, data.get("audience", "whisper")
