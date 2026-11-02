"""What players read, in the language their game is set to. Everything's written in English, and a cheap model puts a feature's words into
other languages (orchestrator/translation.py). What it wrote is kept in bible/lang/<language>.json on main, by the English it came from.
So the same words always come out the same, a name players have learned never changes, and only new English ever needs a model.

The broker reads the same file to write the resource pack, so this imports nothing that only the agent's container has. What the engine says
itself has no model involved, and is in orchestrator/words/<language>.json.
"""
import hashlib
import json
import pathlib
import re

ENGLISH = "en_us"
# Only those with someone playing in them, because each adds to the pack and to every translation.
LANGUAGES = {"de_de": "German"}
# Each of these reads only its own file, and without this someone playing in Austrian German would get this world's things in English.
SAME_WORDS = {"de_de": ("de_de", "de_at", "de_ch")}
FAMILY = {variant: language for language, variants in SAME_WORDS.items() for variant in variants}
NAMES = "names"  # What things are called, which players learn, so these go together for a model to keep to.
TEXTS = "texts"
STORE = "bible/lang/{}.json"
WORDS = pathlib.Path(__file__).parent / "words"
# What has to come through a translation exactly as it was: tokens for names, the game's colour codes, the book's commands, and places for a value.
CODES = re.compile(r"\$(?:block|item|mob|sound|biome|dimension):[a-z0-9_]+(?:/[a-z0-9_]+)?|\$\([^)]*\)|§.|%(?:\d+\$)?[A-Za-z%]")
HAS_LETTERS = re.compile(r"[^\W\d_]")
# How the instant check says a feature's code has words in it, so a builder only hears about their own feature's, not every module in the world.
TEXT_IN_CODE = "piece(s) of text straight into it"
# About as much longer as another language could really need, so anything past this isn't a translation of it.
LONGEST_GROWTH = 4
ROOM_FOR_A_SHORT_ONE = 40
# The widest a character usually is, with the gap after it, and what a button keeps clear at its sides.
CHARACTER_WIDTH = 6
BUTTON_MARGIN = 4


def family(code):
    """The language this world has words for that's closest to what someone's game is set to, or None for English."""
    return FAMILY.get(code)


def codes(text):
    return sorted(CODES.findall(text))


def keeps_codes(english, translated):
    """Whether a translation can safely stand in for its English. Without this, a lost token shows players a slot's id, and a lost colour code colours everything after it."""
    return (isinstance(translated, str) and bool(translated.strip()) and codes(english) == codes(translated)
            and len(translated) <= len(english) * LONGEST_GROWTH + ROOM_FOR_A_SHORT_ONE)


def read_store(root, language):
    path = pathlib.Path(root) / STORE.format(language)
    found = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {NAMES: found.get(NAMES, {}), TEXTS: found.get(TEXTS, {})}


def write_store(root, language, store):
    path = pathlib.Path(root) / STORE.format(language)
    path.parent.mkdir(parents=True, exist_ok=True)
    # One to a line, sorted, so that git can merge two lots of additions.
    path.write_text(json.dumps(store, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def engine_words(language, section):
    path = WORDS / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8")).get(section, {}) if path.exists() else {}


def said(code, text):
    """What plain code says to someone, in their language. It works on any part of a line, so a line can be put together however it needs to be, and what isn't in the list stays as it was."""
    language = family(code)
    if language is None:
        return text
    words = engine_words(language, "said")
    for english in sorted(words, key=len, reverse=True):
        text = text.replace(english, words[english])
    return text


def plan_words(code):
    """How to say what's on the fixed list that /plan goes by, in someone's language."""
    language = family(code)
    words = engine_words(language, "plan") if language else {}
    return lambda english: words.get(english, english)


class Words:
    """One language's translations, for writing the pack. Whatever it doesn't have, or has lost a code from, stays in English, so nothing's ever worse than that."""

    def __init__(self, language, store):
        self.language = language
        self.names = {english: found for english, found in store[NAMES].items() if keeps_codes(english, found)}
        self.texts = {english: found for english, found in store[TEXTS].items() if keeps_codes(english, found)}

    def name(self, english):
        return self.names.get(english, english)

    def text(self, english):
        return self.texts.get(english, english)


def load_languages(root):
    """Every language this world has words for, from a source tree."""
    return {language: Words(language, read_store(root, language)) for language in LANGUAGES}


def is_translation(relative):
    """Whether a file in a release's content only says what another one says, in another language. Nothing that a slow gate tests depends on these."""
    if re.fullmatch(r"config/panels\.[a-z_]+\.json", relative):
        return True
    found = re.fullmatch(r"pack/assets/(?:gm/lang/([a-z_]+)\.json|companion/patchouli_books/guide/([a-z_]+)/.*)", relative)
    return bool(found) and (found.group(1) or found.group(2)) != ENGLISH


def text_id(feature_id, name):
    """What a piece of a feature's text is called in the pack. conduit and the companion work this out the same way, from the name a module asks for."""
    return "t" + hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:16]


def _button_room(widget):
    width = widget.get("width")
    return (width - BUTTON_MARGIN) // CHARACTER_WIDTH if isinstance(width, int) else None


def wanted(manifest, extra=()):
    """Everything in a feature that players read, as (which part of the store, the English, what it is, how many letters fit if that matters), so a model knows what it's looking at."""
    found = []

    def add(part, text, what, room=None):
        if isinstance(text, str) and HAS_LETTERS.search(text):
            found.append((part, text, what, room))

    for table, what in (("blocks", "a block"), ("items", "an item"), ("mobs", "a creature"), ("projectiles", "something fired"), ("vehicles", "a vehicle"), ("props", "an object placed in the world")):
        for thing in (manifest.get(table) or {}).values():
            add(NAMES, thing.get("display"), f"the name of {what}")
    for item in (manifest.get("items") or {}).values():
        for line in item.get("tooltip") or []:
            add(TEXTS, line, "a line of an item's tooltip")
    for entry in (manifest.get("knowledge") or {}).values():
        add(NAMES, entry.get("title"), "the title of a page in the player's book")
        add(TEXTS, entry.get("text"), "a page in the player's book, written the way the world would say it")
    for text in (manifest.get("texts") or {}).values():
        add(TEXTS, text, "something shown to a player, as a whole sentence or label")
    for text in (manifest.get("keys") or {}).values():
        add(TEXTS, text, "what a key does, in the game's controls menu, as a short label")
    for panel in (manifest.get("panels") or {}).values():
        add(TEXTS, panel.get("title"), "the title of a screen")
        for widget in panel.get("widgets") or []:
            room = _button_room(widget) if widget.get("type") == "button" else None
            add(TEXTS, widget.get("text"), f"a button on a screen, which has room for {room} letters" if room else "a short label on a screen", room)
            add(TEXTS, widget.get("tooltip"), "a tooltip on a screen")
            add(TEXTS, widget.get("hint"), "a hint in an empty text box")
            for tab in widget.get("tabs") or []:
                add(TEXTS, tab.get("text"), "the label of a tab, as short as you can make it")
    for text in extra:
        add(TEXTS, text, "something shown to a player")
    return found


def wanted_in(folder):
    """The same, for a feature's folder."""
    folder = pathlib.Path(folder)
    manifest = json.loads((folder / "feature.json").read_text(encoding="utf-8"))
    extra = folder / "assets" / "lang.json"
    return wanted(manifest, json.loads(extra.read_text(encoding="utf-8")).values() if extra.exists() else ())


def wanted_in_graph(graph):
    """A step of the progression gives its name to a category in the player's book."""
    return [(NAMES, node["name"], "the name of a chapter in the player's book", None) for node in (graph or {}).get("nodes", {}).values() if node.get("name")]


def known_names(root, features_dir, language):
    """What's out, as {English: translated}, for a voice that's talking to someone in that language and has to use the names their game shows."""
    store = read_store(root, language)[NAMES]
    shown = {}
    for path in sorted(pathlib.Path(features_dir).glob("*/feature.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # A voice is waiting on this, and it can do without one feature's names.
        if not isinstance(manifest, dict):
            continue
        for table in ("blocks", "items", "mobs", "projectiles", "vehicles", "props"):
            for thing in (manifest.get(table) or {}).values():
                english = thing.get("display")
                if english in store and keeps_codes(english, store[english]) and store[english] != english:
                    shown[english] = store[english]
    return shown
