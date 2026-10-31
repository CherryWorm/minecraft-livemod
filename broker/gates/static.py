"""The first gate: checks that need no server, so bad releases fail in seconds.

Each check here exists because the failure it catches would otherwise brick a boot, erase something
from a world, or spoil a surprise.
"""
import json
import re

from PIL import Image

from broker.gates import GateFailed

GATE = "static"
RESERVE = 0.2
RECIPE_MODES = {"open", "known", "guessable"}
MACHINE_RECIPE_TYPES = {"gm:machine"}
# Words that would give content away if they appeared in a path players can see.
SAFE_PATH = re.compile(r"^assets/(gm/(textures/(block/s\d{4}|item/i\d{4})\.png(\.mcmeta)?"
                       r"|models/(block/s\d{4}|item/i\d{4})\.json|lang/en_us\.json|sounds/[0-9a-f]+\.ogg|sounds\.json))$")


def _fail(message):
    raise GateFailed(GATE, message)


def check_ledger_append_only(old, new):
    """IDs live in world saves, so an assignment can never change or disappear."""
    for table in ("blocks", "items"):
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
        for table in ("blocks", "items"):
            declared.update(f"{feature_id}/{name}" for name in feature["manifest"].get(table, {}))
    for table in ("blocks", "items"):
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
