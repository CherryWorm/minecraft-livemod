"""The first gate: checks that need no server, so bad releases fail in seconds.

Each check here exists because the failure it catches would otherwise brick a boot, erase something
from a world, or spoil a surprise.
"""
import json
import re

from PIL import Image

from broker.gates import GateFailed, balance

GATE = "static"
RESERVE = 0.2
RECIPE_MODES = {"open", "known", "guessable"}
ROUTE_TYPES = {"obtain", "examine", "kill", "read", "fragments"}
LEDGER_TABLES = ("blocks", "items", "mobs")
OLD_LOOT_FIELDS = {"functions", "function", "conditions"}
MACHINE_RECIPE_TYPES = {"gm:machine"}
# Words that would give content away if they appeared in a path players can see.
SAFE_PATH = re.compile(r"^assets/(gm/(textures/(block/s\d{4}|item/i\d{4})\.png(\.mcmeta)?"
                       r"|models/(block/s\d{4}|item/i\d{4})\.json|lang/en_us\.json|sounds/[0-9a-f]+\.ogg|sounds\.json))$")


def _fail(message):
    raise GateFailed(GATE, message)


def check_ledger_append_only(old, new):
    """IDs live in world saves, so an assignment can never change or disappear."""
    for table in LEDGER_TABLES:
        for key, entry in old.get(table, {}).items():
            current = new.get(table, {}).get(key)
            if current is None:
                _fail(f"{key} was removed from the ledger. Worlds may contain it, so it must stay. "
                      "Stop using it in the feature instead of deleting the entry.")
            if current["slot"] != entry["slot"]:
                _fail(f"{key} moved from {entry['slot']} to {current['slot']}. Slot assignments can't change.")


def check_kept_names(features, old):
    """A name in the ledger whose feature no longer declares it would lose its art and behaviour."""
    declared = set()
    for feature_id, feature in features.items():
        for table in LEDGER_TABLES:
            declared.update(f"{feature_id}/{name}" for name in feature["manifest"].get(table, {}))
    for table in LEDGER_TABLES:
        for key in old.get(table, {}):
            if key not in declared:
                _fail(f"{key} is in the ledger but no feature declares it any more. Keep it declared, "
                      "marked as retired if needed, so existing blocks and items keep working.")


def check_slot_budget(ledger, pool):
    """Keeps a reserve in every family, because running out of slots would block all new content."""
    used = {}
    for entry in ledger["blocks"].values():
        used[entry["family"]] = used.get(entry["family"], 0) + 1
    for family, count in used.items():
        limit = int(pool["families"][family]["count"] * (1 - RESERVE))
        if count > limit:
            _fail(f"Family {family} would use {count} slots, over its limit of {limit}. "
                  "Reuse or combine content, or raise the pool in a conduit release.")
    items = len(ledger["items"])
    if items > int(pool["item_count"] * (1 - RESERVE)):
        _fail(f"{items} item slots used, over the limit of {int(pool['item_count'] * (1 - RESERVE))}.")
    for category, available in pool["mobs"].items():
        count = sum(1 for entry in ledger.get("mobs", {}).values() if entry["category"] == category)
        if count > int(available * (1 - RESERVE)):
            _fail(f"{count} {category} mobs would be in use, over the limit of {int(available * (1 - RESERVE))}. "
                  "Reuse or replace one, or raise the pool in a conduit release.")


def check_textures(pack):
    """Bad textures show up as purple and black checkers in the world."""
    for path in sorted((pack / "assets/gm/textures").rglob("*.png")):
        name = path.relative_to(pack)
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                mode = image.mode
        except Exception as error:  # noqa: BLE001 - Pillow raises many types for a broken file
            _fail(f"{name} isn't a valid PNG: {error}")
        if width not in (16, 32, 64) or height % width != 0:
            _fail(f"{name} is {width}x{height}. Textures must be 16, 32 or 64 wide, "
                  "with a height that's a multiple of the width for animations.")
        if height != width and not path.with_suffix(".png.mcmeta").exists():
            _fail(f"{name} is {width}x{height} with no .mcmeta, so it can't animate.")
        if mode not in ("RGB", "RGBA", "P", "LA", "L"):
            _fail(f"{name} uses colour mode {mode}, which the game can't read.")


def check_spoilers(pack):
    """Everything in the pack must use meaningless names. Display names live only in the language file."""
    for path in sorted(file for file in pack.rglob("*") if file.is_file()):
        relative = path.relative_to(pack).as_posix()
        if not SAFE_PATH.match(relative):
            _fail(f"The pack contains {relative}, whose path could give content away. "
                  "Pack files must use slot IDs only.")


def check_json_files(root, label):
    for path in sorted(root.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            _fail(f"{label} file {path.relative_to(root)} isn't valid JSON: {error}")


def check_recipes(recipes):
    """Every recipe must say how players find it, and guessing is only fair on machines."""
    for recipe_id, info in recipes.items():
        source = info["source"]
        if info["mode"] not in RECIPE_MODES:
            _fail(f"Recipe {source} must declare a mode: open, known or guessable. Found {info['mode']!r}.")
        if info["mode"] == "known" and not info.get("route"):
            _fail(f"Recipe {source} is 'known' but has no route, so nobody could ever learn it.")


def check_guessable_only_on_machines(features):
    for feature_id, feature in features.items():
        for name, recipe in feature["manifest"].get("recipes", {}).items():
            if recipe.get("mode") == "guessable":
                kind = recipe.get("json", {}).get("type", "")
                if kind not in MACHINE_RECIPE_TYPES and not recipe.get("machine"):
                    _fail(f"Recipe {feature_id}/{name} is guessable but isn't a machine recipe. "
                          "A crafting grid has too many possibilities for guessing to be fair.")
                if not recipe.get("feedback"):
                    _fail(f"Recipe {feature_id}/{name} is guessable with no feedback, "
                          "so experimenting at the machine wouldn't tell players anything.")


def _old_loot_fields(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in OLD_LOOT_FIELDS:
                yield key
            yield from _old_loot_fields(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _old_loot_fields(inner)


def check_loot_format(features):
    """The game ignores fields it doesn't know without a word, so an old-style loot table loads and quietly does less."""
    for feature_id, feature in features.items():
        for name, ruin in feature["manifest"].get("ruins", {}).items():
            found = sorted(set(_old_loot_fields(ruin.get("loot") or {})))
            if found:
                _fail(f"Ruin {feature_id}/{name} has loot using {', '.join(found)}, which Minecraft 26 ignores. "
                      "See 'Loot tables' in docs/content-types.md.")


def check_knowledge(features):
    """A recipe that has to be learned needs a way of learning it that players can actually reach."""
    entries = {f"{feature_id}/{name}": entry for feature_id, feature in features.items()
               for name, entry in feature["manifest"].get("knowledge", {}).items()}
    for key, entry in entries.items():
        routes = entry.get("routes")
        if not routes:
            _fail(f"Knowledge {key} has no routes, so nobody could ever learn it.")
        for route in routes:
            if route.get("type") not in ROUTE_TYPES:
                _fail(f"Knowledge {key} has a route of type {route.get('type')!r}. Use one of {sorted(ROUTE_TYPES)}.")
            if not route.get("id"):
                _fail(f"Knowledge {key} has a {route['type']} route that doesn't say what triggers it.")
            if route["type"] == "fragments" and not route.get("needed"):
                _fail(f"Knowledge {key} collects fragments but doesn't say how many are needed.")
    for feature_id, feature in features.items():
        for name, recipe in feature["manifest"].get("recipes", {}).items():
            if recipe.get("mode") != "known":
                continue
            route = recipe.get("route", "")
            key = route if "/" in route else f"{feature_id}/{route}"
            if key not in entries:
                _fail(f"Recipe {feature_id}/{name} is learned through {key!r}, which no feature declares, "
                      "so nobody could ever learn it.")
            kind = recipe.get("json", {}).get("type", "")
            if not recipe.get("machine") and not kind.startswith("minecraft:crafting"):
                _fail(f"Recipe {feature_id}/{name} is 'known', but a {kind} recipe can't be locked. "
                      "Only crafting and machine recipes can. Use 'open' here.")


def run(features, old_ledger, new_ledger, pool, content):
    pack = content / "pack"
    check_ledger_append_only(old_ledger, new_ledger)
    check_kept_names(features, old_ledger)
    check_slot_budget(new_ledger, pool)
    check_textures(pack)
    check_spoilers(pack)
    check_json_files(content / "datapack", "Data pack")
    check_json_files(pack, "Pack")
    check_recipes(json.loads((content / "recipes.json").read_text(encoding="utf-8")))
    check_guessable_only_on_machines(features)
    check_knowledge(features)
    check_loot_format(features)
    balance.run(features)
