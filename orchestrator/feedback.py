"""What players have asked for and what became of each request. Plain code keeps this, so that nothing's lost because a
model forgot it, and so everyone can hear back.

A request with no status hasn't been decided yet. After that it's building, later, done, declined or waiting on the owner.
"""
import json

BUILDING = "building"
LATER = "later"
DONE = "done"
DECLINED = "declined"
NEEDS_OWNER = "needs_owner"  # Only a person can change the engine, so the director passes these on instead of pretending.
# How anything that belongs to the world is shown to players before it's out. A fixed list, so a name can't slip in.
CATEGORIES = ["mob", "boss fight", "character", "gear", "tool", "upgrade", "machine", "biome", "structure", "story", "food", "item", "building block", "world event"]
STAGE_WORDS = {"early": "early game", "mid": "mid game", "end": "late game"}


def describe(feature, graph):
    """What players get to read about one piece of work. A bug fix or a small convenience is named, because there's
    nothing to spoil. Anything else is only ever its stage and its category, like "early game mob"."""
    if feature.get("small"):
        return feature.get("title") or "a small fix"
    node = (graph or {}).get("nodes", {}).get(feature.get("node"))
    stage = STAGE_WORDS.get(node["stage"]) if node else None
    category = feature.get("category") if feature.get("category") in CATEGORIES else None
    return " ".join(word for word in (stage, category) if word) or "something new"


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
        """What's been said so far about what, so that the same thing gets the same answer. Who asked doesn't come into it."""
        return [{"wanted": entry["wants"], "decided": self.status(entry["number"]),
                 **{key: value for key, value in self.statuses[str(entry["number"])].items() if key != "status" and value}}
                for entry in self.all() if self.status(entry["number"]) is not None]

    def undecided(self):
        """Everything the director still has to think about. There's no window on this, so nothing can drop off the end."""
        return [entry for entry in self.all() if self.status(entry["number"]) in (None, LATER)]

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
        return [{"wants": entry["wants"], "status": self.status(entry["number"]) or "being looked at",
                 **({"why": self.statuses[str(entry["number"])]["why"]} if self.statuses.get(str(entry["number"]), {}).get("why") else {})}
                for entry in mine]
