"""Writes the Codex, the book players read in Patchouli: this world's knowledge, filed by where it falls in the progression.

It goes out in the resource pack, so new pages reach a running game with every release. Each entry has a flag, which a player's game
only turns on once they know it, and a category only exists while something in it does. So nobody's book shows them what they haven't learned.
"""
import hashlib
import math
import re

BOOKS = "assets/companion/patchouli_books/guide"
ENGLISH = "en_us"
NAMESPACE = "companion"
# About what fits on a line, under an entry's title, and on a page after it. A page that goes over is drawn smaller, so these can be approximate.
LINE_CHARACTERS = 26
FIRST_PAGE_LINES = 12
PAGE_LINES = 15
RECIPES_PER_PAGE = 2
# The most a category's page has room to show.
MOST_SUBCATEGORIES = 16
STAND_IN = 'minecraft:trial_key[minecraft:item_model="{}"]'
DEFAULT_ICON = "minecraft:knowledge_book"
SLOT_THING = re.compile(r"gm:[is]\d{4}$")
PARAGRAPH = "$(br2)"
STAGES = {
    "early": ("First Steps", "minecraft:wooden_pickaxe", "What you've come to know while finding your feet."),
    "mid": ("Further In", "minecraft:iron_pickaxe", "What you've come to know once things start to run themselves."),
    "end": ("The Far Reaches", "minecraft:netherite_pickaxe", "What you've come to know about the furthest things there are."),
}
OTHER = ("Odds and Ends", DEFAULT_ICON, "Everything else you've come to know.")


def _hashed(prefix, value):
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:10]


def flag(key):
    """What a player's game turns on once they know an entry. It's also the entry's file name, so a link can open it."""
    return _hashed("k", key)


def lines(page):
    """About how many lines a page's text takes, with a blank one between paragraphs."""
    return sum(math.ceil(len(paragraph) / LINE_CHARACTERS) + 1 for paragraph in page.split(PARAGRAPH)) - 1


def _pieces(paragraph):
    """Sentences, and anything too long for one page cut between words."""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        current = ""
        for word in sentence.split():
            if current and lines(f"{current} {word}") > FIRST_PAGE_LINES:
                yield current
                current = ""
            current = f"{current} {word}" if current else word
        if current:
            yield current


def text_pages(text):
    """Patchouli doesn't flow text across pages. Stops at the end of a sentence, so a page never ends in the middle of one if it can help it."""
    pages, page, limit = [], "", FIRST_PAGE_LINES
    # Anything starting with this is one of Patchouli's commands, and nothing written for players should be.
    for paragraph in re.split(r"\s*\n\s*", text.replace("$(", "$ (").strip()):
        gap = PARAGRAPH
        for piece in _pieces(paragraph):
            if page and lines(f"{page}{gap}{piece}") > limit:
                pages.append(page)
                page, limit = "", PAGE_LINES
            page += f"{gap}{piece}" if page else piece
            gap = " "
    if page:
        pages.append(page)
    return pages


def _icon(entry):
    chosen = entry.get("icon")
    # Only one somebody chose can be vanilla's, because what a route names might be a mob, which has no item to draw.
    if chosen and not SLOT_THING.match(chosen):
        return chosen
    for thing in (chosen, *(route.get("id") for route in entry["routes"]), *entry["things"]):
        if thing and SLOT_THING.match(thing):
            return STAND_IN.format(thing)
    return DEFAULT_ICON


def book(entries, nodes, language=ENGLISH, say=str):
    """Every file of the book in one language, as {path in the pack: contents}. Entries are each like {key, title, text, routes, recipes, node, things, icon},
    and nodes is the progression graph's. Each stage of it is a category of the book, and each node a category within that. What the book itself says goes through say."""
    folder = f"{BOOKS}/{language}"

    def _category(path, name, icon, description, flags, sortnum, parent=None):
        category = {"name": name, "icon": icon, "description": description, "sortnum": sortnum, "flag": "|" + ",".join(sorted(flags))}
        if parent:
            category["parent"] = f"{NAMESPACE}:{parent}"
        return f"{folder}/categories/{path}.json", category

    files = {}
    filed = {}
    for entry in entries:
        filed.setdefault(entry["node"] if entry["node"] in nodes else None, []).append(entry)
        pages = [{"type": "patchouli:text", "text": page} for page in text_pages(entry["text"])]
        recipes = entry["recipes"]
        pages += [{"type": "gm:recipe", "recipes": recipes[start:start + RECIPES_PER_PAGE]} for start in range(0, len(recipes), RECIPES_PER_PAGE)]
        category = f"n{_node_hash(entry['node'])}" if entry["node"] in nodes else "other"
        files[f"{folder}/entries/{flag(entry['key'])}.json"] = {
            "name": entry["title"], "category": f"{NAMESPACE}:{category}", "icon": _icon(entry), "flag": flag(entry["key"]), "pages": pages}

    if None in filed:
        name, icon, description = OTHER
        path, category = _category("other", say(name), icon, say(description), [flag(entry["key"]) for entry in filed[None]], len(STAGES) * MOST_SUBCATEGORIES)
        files[path] = category

    for stage_number, (stage, (name, icon, description)) in enumerate(STAGES.items()):
        here = [node for node in nodes if node in filed and nodes[node].get("stage") == stage]
        # Past what fits on a page, a stage goes on in another category of its own.
        for part, start in enumerate(range(0, len(here), MOST_SUBCATEGORIES)):
            root = f"s_{stage}" if part == 0 else f"s_{stage}_{part + 1}"
            chunk = here[start:start + MOST_SUBCATEGORIES]
            path, category = _category(root, say(name) if part == 0 else say("%s, Part %s") % (say(name), part + 1), icon, say(description),
                                       [flag(entry["key"]) for node in chunk for entry in filed[node]], stage_number * MOST_SUBCATEGORIES + part)
            files[path] = category
            for position, node in enumerate(chunk):
                node_name = nodes[node].get("name", node)
                path, category = _category(f"n{_node_hash(node)}", node_name, _icon(filed[node][0]), say("What you've come to know about %s.") % node_name,
                                           [flag(entry["key"]) for entry in filed[node]], position, root)
                files[path] = category
    return files


def _node_hash(node):
    return _hashed("", node)
