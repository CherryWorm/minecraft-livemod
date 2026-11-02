"""Takes out what must never reach the website: secrets, what players said in private, and who they are. Whatever a builder saw can end
up in what's recorded about its build, and a builder has a shell, so nothing here assumes that what's passing through is well behaved.

Plain standard library, because the website's own process uses the part about secrets as a last check, and it has nothing else of the agent's.
"""
import os
import re

HIDDEN = "(hidden)"
PRIVATE = "(private)"
PLAYER = "a player"
PHRASE_WORDS = 5  # The same as voice.guard: a shorter run of words is too often just how anyone would say it.
SHORTEST_SECRET = 8  # Anything shorter would hide ordinary words.

_KEY_SHAPES = re.compile(
    r"\bsk-[A-Za-z0-9_-]{12,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bxox[a-z]-[A-Za-z0-9-]{10,}"
    r"|\bAKIA[0-9A-Z]{12,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL)
_ASSIGNED = re.compile(
    r"([A-Za-z0-9_.-]*(?:token|secret|password|passwd|api[_-]?key|authorization|credential)[A-Za-z0-9_.-]*[\"']?\s*[:=]\s*[\"']?)((?:Bearer\s+|Basic\s+)?[^\s\"',;]{4,})", re.IGNORECASE)
_BEARER = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9+/._~=-]{8,}")
_LONG = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
_ADDRESS = re.compile(r"\b(?:[\w.-]+@)?(?:\d{1,3}\.){3}\d{1,3}\b(?::\d+)?")
_HEX = re.compile(r"(?=.*[0-9a-fA-F])[0-9a-fA-F-]+")
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|API_KEY|AUTH", re.IGNORECASE)
_KNOWN = set()  # What's been read from a secret's file. Only the agent's own process has these.


def keep_out(value):
    """A secret's real value, for wherever one's read. It can then be recognised in anything, whatever it looks like."""
    if value and len(value) >= SHORTEST_SECRET:
        _KNOWN.add(value)


def keep_out_environment(environment=None):
    for name, value in (os.environ if environment is None else environment).items():
        if _SECRET_NAME.search(name):
            keep_out(value)


def _looks_random(word):
    """A long run of letters and digits that has them all mixed together. A long file name is all one case, so it's left alone."""
    if _HEX.fullmatch(word):
        return True
    return any(c.isdigit() for c in word) and any(c.isupper() for c in word) and any(c.islower() for c in word)


def secrets(text):
    """Whatever looks like a secret or an address. It's fine for this to catch too much, because the worst that does is hide a commit's hash."""
    for value in _KNOWN:
        text = text.replace(value, HIDDEN)
    text = _KEY_SHAPES.sub(HIDDEN, text)
    text = _BEARER.sub(lambda match: f"{match.group(1)} {HIDDEN}", text)
    text = _ASSIGNED.sub(lambda match: match.group(1) + HIDDEN, text)
    text = _LONG.sub(lambda match: HIDDEN if _looks_random(match.group()) else match.group(), text)
    return _ADDRESS.sub("(address)", text)


def _phrases(texts):
    found = set()
    for text in texts:
        words = [word.lower() for word in _WORD.findall(text or "")]
        found.update(tuple(words[start:start + PHRASE_WORDS]) for start in range(len(words) - PHRASE_WORDS + 1))
    return found


class Scrubber:
    """Knows who plays and what's been said in private. It compares runs of words, so nothing's kept but those, and a reworded phrase gets past it,
    which is why voices and the director are told not to repeat these in the first place."""

    def __init__(self, names=(), private_texts=()):
        wanted = sorted({name for name in names if name and len(name) > 2}, key=len, reverse=True)
        self.names = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(name) for name in wanted) + r")(?![\w-])", re.IGNORECASE) if wanted else None
        self.phrases = _phrases(private_texts)

    def _without_phrases(self, text):
        if not self.phrases:
            return text
        words = list(_WORD.finditer(text))
        spans = []
        for start in range(len(words) - PHRASE_WORDS + 1):
            run = words[start:start + PHRASE_WORDS]
            if tuple(word.group().lower() for word in run) in self.phrases:
                if spans and run[0].start() <= spans[-1][1]:
                    spans[-1][1] = run[-1].end()
                else:
                    spans.append([run[0].start(), run[-1].end()])
        for begin, end in reversed(spans):
            text = text[:begin] + PRIVATE + text[end:]
        return text

    def __call__(self, text, limit=None):
        if not isinstance(text, str):
            return ""
        text = secrets(text)
        if self.names:
            text = self.names.sub(PLAYER, text)
        text = self._without_phrases(text)
        return cut(text, limit) if limit else text


def cut(text, limit):
    """Keeps both ends of something too long, because how a command's output ended is often what mattered."""
    if len(text) <= limit:
        return text
    tail = limit // 4
    return f"{text[:limit - tail]}\n... ({len(text) - limit} characters left out) ...\n{text[-tail:]}"
