"""What players have asked for and what became of each request. Plain code keeps this, so that nothing's lost because a
model forgot it, and so everyone can hear back.

A request with no status hasn't been decided yet. After that it's building, later, done, declined or something the engine can't do.
"""
import json
import re

BUILDING = "building"
LATER = "later"
DONE = "done"
DECLINED = "declined"
ENGINE_LIMIT = "engine_limit"  # The engine or the client mod doesn't support what's needed, so no feature can do it. It's collected, and the player's told.
ASK_AGAIN = "ask_again"  # Something's changed since it was decided, like the owner changing the engine, so the director looks at it afresh.
# How anything that belongs to the world is shown to players before it's out. A fixed list, so a name can't slip in.
CATEGORIES = ["mob", "boss fight", "character", "gear", "tool", "upgrade", "machine", "biome", "structure", "story", "food", "item", "building block", "world event"]
STAGE_WORDS = {"early": "early game", "mid": "mid game", "end": "late game"}
BOARD_TAGS = {"early": "early", "mid": "mid", "end": "late"}
BOARD_WIDTH = 34  # The sidebar grows with its longest line and never wraps, so this is about how much of the screen it takes.
MOST_NAMED_IN_A_RELEASE = 3
# Nothing a voice says reaches anyone outside the game. What the engine lacks goes in a file that notifies nobody, and what the world becomes is the
# director's to decide, so no player should hear that someone's been told or that it's up to whoever runs the server. Prompts say so too, but players believe this.
RELAYED = re.compile(
    r"\bthe owner\b(?!'s| of)|\bserver'?s? owner|\bowner of (?:the|this) server|\b(?:server )?admins?\b|\b(?:person|people|one|someone) (?:who|that) runs?\b|\bwhoever runs\b"
    r"|\b(?:I've|I have|I'll|I will|we've|we have)\s+(?:also\s+)?(?:told|informed|notified|alerted|reported|flagged|escalated|forwarded|passed|sent)\b(?!\s+you)"
    r"|\b(?:it|that|this|they)(?:'s| has|'ve| have)\s+been\s+(?:passed|forwarded|escalated|flagged|sent)\b"
    r"|\bpassed\s+(?:it |this |that )?(?:on|along)\b"
    r"|\bBetreiber|\bServer-?Admin|\bweiter(?:gegeben|geleitet|gereicht|gesagt)\b|\bBescheid (?:gesagt|gegeben)\b",
    re.IGNORECASE)
NOTED = re.compile(r"\b(?:noted|note (?:it|that|this)|taken note|made a note|notiert|vermerkt)\b", re.IGNORECASE)


def _without_sentences(pattern, text):
    if not text or not pattern.search(text):
        return text
    return " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if not pattern.search(sentence))


def without_relays(text):
    """What's left once any sentence saying someone outside the game has been told, or has to decide, is gone."""
    return _without_sentences(RELAYED, text)


def without_noted(text):
    """For a reply that recorded nothing, which can't truthfully say it noted anything."""
    return _without_sentences(NOTED, text)


def describe(feature, graph):
    """What players get to read about one piece of work. A bug fix or a small convenience is named, because there's
    nothing to spoil. Anything else is only ever its stage and its category, like "early game mob"."""
    if feature.get("small"):
        return feature.get("title") or "a small fix"
    node = (graph or {}).get("nodes", {}).get(feature.get("node"))
    stage = STAGE_WORDS.get(node["stage"]) if node else None
    category = feature.get("category") if feature.get("category") in CATEGORIES else None
    return " ".join(word for word in (stage, category) if word) or "something new"


def about(feature, graph):
    """A few words for everyone about one piece of work, which are as safe as what the sidebar says about it."""
    return (not feature.get("small") and feature.get("teaser")) or describe(feature, graph)


def release_reason(abouts):
    """What players are told a release changes. Plain words that are ready beforehand, because it's said just before the reload."""
    named = list(dict.fromkeys(about_one for about_one in abouts if about_one)) or ["something new"]
    shown, more = named[:MOST_NAMED_IN_A_RELEASE], len(named) - MOST_NAMED_IN_A_RELEASE
    if more > 0:
        return f"{', '.join(shown)} and {more} more"
    return f"{', '.join(shown[:-1])} and {shown[-1]}" if len(shown) > 1 else shown[0]


def safe_teaser(text, feature):
    """A model wrote this and everyone's going to see it, so it's refused if it looks like it's giving anything away:
    anything from the feature's own id, a name from its brief, or something capitalised like a name."""
    text = (text or "").strip().rstrip(".").replace("§", "")
    spec = feature.get("spec", "")
    words = re.findall(r"[A-Za-z']+", text)
    named = [*feature.get("id", "").split("_"), *re.findall(r"(?<=[a-z,] )[A-Z][a-z]{2,}", spec), *re.findall(r"[A-Za-z]+", " ".join(re.findall(r"`([^`]+)`", spec)))]
    names = {name.lower() for name in named if len(name) > 2}
    if not words or len(text) > BOARD_WIDTH or any(word[0].isupper() for word in words[1:]) or any(word.lower() in names for word in words):
        return None
    return text


def board_line(feature, graph):
    """One line on the sidebar. A bug fix or a small convenience is named as it is in /plan. Anything else is a few careful
    words from a model if it has them, and otherwise what /plan says, with its stage alongside."""
    if feature.get("small"):
        title = feature.get("title") or "a small fix"
        return {"text": title if len(title) <= BOARD_WIDTH else title[:BOARD_WIDTH - 1].rstrip() + "…", "tag": "small"}
    node = (graph or {}).get("nodes", {}).get(feature.get("node"))
    category = feature.get("category") if feature.get("category") in CATEGORIES else None
    return {"text": feature.get("teaser") or category or "something new", "tag": BOARD_TAGS.get(node["stage"], "") if node else ""}


class Requests:
    def __init__(self, path, statuses):
        self.path = path
        self.statuses = statuses  # Kept with the rest of the agent's saved state, by request number.

    def all(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    def status(self, number):
        return self.statuses.get(str(number), {}).get("status")

    def mark(self, number, status, **details):
        self.statuses[str(number)] = {"status": status, **details}

    def reopen(self, number):
        self.statuses.pop(str(number), None)

    def decided(self):
        """What's been said so far about what, and why, so that an earlier answer can be judged and not only repeated. Who asked doesn't come into it."""
        return [{"wanted": entry["wants"], "decided": self.status(entry["number"]), **self._details(entry["number"])}
                for entry in self.all() if self.status(entry["number"]) not in (None, ASK_AGAIN)]

    def _details(self, number):
        """Reasons saved before voices were stopped from claiming to have told anyone get the same treatment."""
        details = {key: value for key, value in self.statuses.get(str(number), {}).items() if key != "status"}
        if details.get("why"):
            details["why"] = without_relays(details["why"])
        return {key: value for key, value in details.items() if value}

    def undecided(self):
        """Everything the director still has to think about. There's no window on this, so nothing can drop off the end."""
        return [entry for entry in self.all() if self.status(entry["number"]) in (None, LATER, ASK_AGAIN)]

    def ask_again(self):
        """Everything the engine couldn't do gets another look."""
        for entry in self.all():
            if self.status(entry["number"]) == ENGINE_LIMIT:
                self.mark(entry["number"], ASK_AGAIN)

    def unanswered_after(self, number):
        return [entry for entry in self.all() if entry["number"] > number and self.status(entry["number"]) is None]

    def last_number(self):
        entries = self.all()
        return entries[-1]["number"] if entries else 0

    def for_feature(self, feature_id):
        return [entry for entry in self.all()
                if self.status(entry["number"]) == BUILDING and self.statuses[str(entry["number"])].get("feature") == feature_id]

    def of_player(self, player, limit=10):
        """What they can be told about their own requests, and nobody else's."""
        mine = [entry for entry in self.all() if entry.get("player") == player][-limit:]
        return [{"wants": entry["wants"], "status": "being looked at" if self.status(entry["number"]) in (None, ASK_AGAIN) else self.status(entry["number"]),
                 **({"why": self._details(entry["number"])["why"]} if self._details(entry["number"]).get("why") else {})}
                for entry in mine]
