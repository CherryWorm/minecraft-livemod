"""Puts what builders write into the other languages players use, on a cheap model, and keeps it (see wording.py).

It runs just before a feature goes to the gates, so what it writes goes out with that feature, and it only ever asks about English it hasn't
seen, so most of the time it asks nothing at all. If it can't ask, or doesn't like the answer, that English just stays English until a later
look, and nothing waits for it. What's written is never written again, because players know things by these names.
"""
import asyncio
import collections
import json

from orchestrator import llm, wording

MOST_AT_ONCE = 30
MOST_LETTERS_AT_ONCE = 6000
# A model that won't keep a token in one line of text isn't going to, so that line stays English rather than being asked about forever.
TRIES = 3
SCHEMA = {"type": "object", "properties": {"translations": {"type": "array", "items": {"type": "object", "properties": {
    "number": {"type": "integer"}, "translation": {"type": "string"}}, "required": ["number", "translation"]}}}, "required": ["translations"]}


def _batches(things):
    """In groups a cheap model can do well in one go."""
    batch, letters = [], 0
    for thing in things:
        if batch and (len(batch) >= MOST_AT_ONCE or letters + len(thing["english"]) > MOST_LETTERS_AT_ONCE):
            yield batch
            batch, letters = [], 0
        batch.append(thing)
        letters += len(thing["english"])
    if batch:
        yield batch


def _missing(wanted, store):
    """What the store doesn't have yet, once each. The tightest room anywhere is the room it has, because it's the same words everywhere."""
    found = {}
    for part, english, what, room in wanted:
        if english not in store[part]:
            earlier = found.get((part, english))
            tightest = min((size for size in (room, earlier and earlier["room"]) if size), default=None)
            found[(part, english)] = {"part": part, "english": english, "what": what, "room": tightest}
    return list(found.values())


def _prompt(batch, name, names):
    used = {english: own for english, own in names.items() if any(english.lower() in thing["english"].lower() for thing in batch)}
    lines = [{"number": number, "what": thing["what"], "english": thing["english"]} for number, thing in enumerate(batch)]
    return (f"Translate these into {name}.\n\n" + (f"These are already named, so use exactly these names:\n{json.dumps(used, ensure_ascii=False, indent=0)}\n\n" if used else "")
            + llm.untrusted("english", json.dumps(lines, ensure_ascii=False, indent=0)))


class Translator:
    def __init__(self, governor, repo, commit):
        self.governor = governor
        self.repo = repo
        self.commit = commit
        self.lock = asyncio.Lock()  # There's one store, on main.
        self.tries = collections.Counter()

    async def feature(self, folder):
        """Just before a feature's gates. Whatever goes wrong here, the feature still goes out, in English, and catch_up has another look."""
        try:
            await self._bring_up_to_date(wording.wanted_in(folder))
        except Exception as error:  # noqa: BLE001 - nothing about words is worth stopping a feature for
            print(f"translating {folder.name} failed: {type(error).__name__}: {error}", flush=True)

    async def catch_up(self, features_dir, graph):
        """Anything released before there were translations, or when no model could be asked, and any new step of the progression."""
        wanted = wording.wanted_in_graph(graph)
        for path in sorted(features_dir.glob("*/feature.json")):
            try:
                wanted += wording.wanted_in(path.parent)
            except (OSError, ValueError, AttributeError, TypeError) as error:
                print(f"couldn't read the words in {path.parent.name}: {error}", flush=True)
        await self._bring_up_to_date(wanted)

    async def _bring_up_to_date(self, wanted):
        async with self.lock:
            for language, name in wording.LANGUAGES.items():
                # Names first, so that text mentioning one can be told what it's called.
                for part in (wording.NAMES, wording.TEXTS):
                    missing = [thing for thing in _missing([entry for entry in wanted if entry[0] == part], wording.read_store(self.repo, language)) if self.tries[(language, thing["english"])] < TRIES]
                    for batch in _batches(missing):
                        if self.governor.why_not_build():
                            return
                        await self._translate(batch, language, name)

    async def _translate(self, batch, language, name):
        store = wording.read_store(self.repo, language)
        result = await llm.ask(self.governor, "translator", _prompt(batch, name, store[wording.NAMES]), schema=SCHEMA)
        for thing in batch:
            self.tries[(language, thing["english"])] += 1
        answers = result.structured.get("translations", []) if isinstance(result.structured, dict) and not result.is_error else []
        added = 0
        for answer in answers:
            number = answer.get("number")
            if not isinstance(number, int) or not 0 <= number < len(batch):
                continue
            thing, translated = batch[number], answer.get("translation")
            fits = thing["room"] is None or (isinstance(translated, str) and len(translated) <= thing["room"])
            # Never over what's there: another feature with the same words may have got here first, and players know that one.
            if wording.keeps_codes(thing["english"], translated) and fits and thing["english"] not in store[thing["part"]]:
                store[thing["part"]][thing["english"]] = translated.strip()
                added += 1
        if added:
            wording.write_store(self.repo, language, store)
            self.commit(f"{name} for {added} more things")
        print(f"translated {added} of {len(batch)} into {name} in {result.seconds}s", flush=True)
