"""The first gate: checks that need no server, so bad releases fail in seconds.

Each check here exists because the failure it catches would otherwise brick a boot, erase something
from a world, or spoil a surprise.
"""
import itertools
import json
import re

from PIL import Image

from broker import bundles
from broker.bundles import TOKEN
from broker.gates import GateFailed, balance, progression
from orchestrator import others

GATE = "static"
RESERVE = 0.2
RECIPE_MODES = {"open", "known", "guessable"}
ROUTE_TYPES = {"obtain", "examine", "kill", "read", "fragments"}
LEDGER_TABLES = ("blocks", "items", "mobs")
OLD_LOOT_FIELDS = {"functions", "function", "conditions"}
MACHINE_RECIPE_TYPES = {"gm:machine"}
# Starting values, to be tuned once real players' computers have shown what they can draw.
MAX_BONES_ROAMING = 16
MAX_BONES_ONE_OFF = 48
MAX_BONES_BLOCK = 16
MAX_MODEL_CUBES = 3000
MIND_ACTIONS = {"follow", "flee", "stay", "wander", "lead", "give", "teach", "attack"}
MIND_VOICES = {"words", "cries", "silent"}
MAX_CHARACTER = 800
MAX_STASH = 8
MOB_SOUNDS = {"idle", "hurt", "death"}
INVENTORY_KINDS = {"inputs", "fuel", "outputs"}
MACHINE_FAMILIES = {"machine", "model"}
MOST_MACHINE_SLOTS = 27
MOST_HARDNESS = 5
CROP_STAGES = 4
NOT_CUBES = {"plant", "glow_plant", "tinted_plant", "crop", "connected", "model", "cutout"}
MOST_USE_SECONDS = 60
USE_ANIMATIONS = {"none", "eat", "drink", "block", "bow", "trident", "crossbow", "spyglass", "toot_horn", "brush", "bundle", "spear"}
MOST_SHADER_CHARACTERS = 16000
# What fits at the size a small window draws its interface. A vanilla chest is 176 by 222.
MOST_PANEL_WIDTH = 320
PLAYER_INVENTORY_FROM_BOTTOM = 82
TITLE_PLACE = (8, 6)
INVENTORY_LABEL_ABOVE = 12
TEXT_LINE = 9
NARROW_CHARACTER = 5
SLOT_ITEM = 16
SLOT_STEP = 18
HOTBAR_ROW = 3
HOTBAR_GAP = 4
# How far round a slot to look for any sign of a frame, which leaves room for a big one of its own.
FRAME_MARGIN = 8
MOST_PANEL_HEIGHT = 230
MOST_CHEST_ROWS = 6
MOST_TYPED = 256
PLAYER_INVENTORY_WIDTH = 162
PLAYER_INVENTORY_HEIGHT = 76
MOST_PANEL_IMAGE = 1024
# Each kind of widget, and how big it is if it doesn't say.
PANEL_WIDGETS = {"slot": 18, "label": 0, "icon": 16, "image": 16, "bar": 16, "button": 20, "tabs": 20, "list": 60, "mob": 40, "text_field": 16}
PANEL_NEEDS_ID = {"button", "list", "text_field", "bar"}
PANEL_BAR_DIRECTIONS = {"right", "left", "up", "down"}
MIN_COMPASS_FRAMES = 2
MAX_COMPASS_FRAMES = 64
BLOCK_WITH_STATE = re.compile(r"[^\[\]\s]+(\[[a-z0-9_]+=[a-z0-9_]+(,[a-z0-9_]+=[a-z0-9_]+)*\])?")
# The vanilla blocks whose block entity takes a loot table. An ender chest looks like one, but it's the player's own.
LOOT_CONTAINERS = re.compile(r"minecraft:(chest|trapped_chest|barrel|dispenser|dropper|hopper|crafter|([a-z]+_)?shulker_box|([a-z]+_)*copper_chest)")
# Words that would give content away if they appeared in a path players can see.
SAFE_PATH = re.compile(r"^assets/(gm/(textures/(block/s\d{4}(_(top|bottom|front|back|left|right|side|\d))?|item/[is]\d{4}(_[cv]\d+)?)\.png(\.mcmeta)?"
                       r"|models/(block/s\d{4}(_c?\d+)?|item/[is]\d{4}(_[cv]\d+)?)\.json|items/[is]\d{4}\.json|lang/en_us\.json|sounds/[0-9a-f]+\.ogg|sounds\.json|shaders/post/p[0-9a-f]+\.fsh|post_effect/p[0-9a-f]+\.json|textures/gui/p[0-9a-f]+\.png)"
                       r"|companion/patchouli_books/guide/en_us/(entries/k[0-9a-f]+|categories/(n[0-9a-f]+|s_[a-z]+(_\d+)?|other))\.json)$")


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
        if path.parent.name == "gui":
            if max(width, height) > MOST_PANEL_IMAGE:
                _fail(f"{name} is {width}x{height}. A panel's images can be at most {MOST_PANEL_IMAGE} across.")
            continue
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
            found = sorted(set(_old_loot_fields(balance.ruin_loot(ruin))))
            if found:
                _fail(f"Ruin {feature_id}/{name} has loot using {', '.join(found)}, which Minecraft 26 ignores. "
                      "See 'Loot tables' in docs/content-types.md.")


def _check_can_be_learned(entries):
    """Routes can need other entries first, so a circle of those is a set of things nobody could ever start on."""
    learnable = set()
    while True:
        more = {key for key, entry in entries.items() if key not in learnable
                and any(all(balance._key(key.split("/")[0], need) in learnable for need in route.get("requires", [])) for route in entry["routes"])}
        if not more:
            break
        learnable |= more
    stuck = sorted(set(entries) - learnable)
    if stuck:
        _fail(f"Nobody could ever learn {', '.join(stuck)}, because every route to each one requires something that can't be learned first.")


def check_changes_to_others(features):
    """A reviewer and the next builder both need to know why one feature reached into another."""
    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        declared = manifest.get("changes_features", {})
        if not isinstance(declared, dict):
            _fail(f"{feature_id} has changes_features {declared!r}. It's other features and why, like {{\"alloy_kiln\": \"Its recipe was in the wrong place\"}}.")
        additions = manifest.get("adds_to", {})
        reasons = {**declared, **{target: places.get(others.WHY) for target, places in additions.items()}}
        for target, reason in reasons.items():
            if target == feature_id:
                _fail(f"{feature_id} lists itself as a feature it changes. It only needs to list others.")
            if target not in features:
                _fail(f"{feature_id} says it changes {target!r}, which isn't a feature that's out. One still being built is for its own builder.")
            if len(str(reason or "").strip()) < progression.MIN_REASON:
                _fail(f"{feature_id} changes {target} without a clear reason. Say why, in a sentence: a reviewer and the next builder both read it.")


def check_knowledge(features):
    """A recipe that has to be learned needs a way of learning it that players can actually reach."""
    entries = {f"{feature_id}/{name}": entry for feature_id, feature in features.items()
               for name, entry in feature["manifest"].get("knowledge", {}).items()}
    for key, entry in entries.items():
        routes = entry.get("routes")
        if not routes:
            _fail(f"Knowledge {key} has no routes, so nobody could ever learn it.")
        icon = entry.get("icon")
        if icon is not None and not re.fullmatch(r"\$(item|block):[a-z0-9_/]+|minecraft:[a-z0-9_]+", str(icon)):
            _fail(f"Knowledge {key} has the icon {icon!r}. Use $item:name, $block:name or a vanilla item like minecraft:apple.")
        for route in routes:
            if route.get("type") not in ROUTE_TYPES:
                _fail(f"Knowledge {key} has a route of type {route.get('type')!r}. Use one of {sorted(ROUTE_TYPES)}.")
            if not route.get("id"):
                _fail(f"Knowledge {key} has a {route['type']} route that doesn't say what triggers it.")
            if route["type"] == "fragments" and not route.get("needed"):
                _fail(f"Knowledge {key} collects fragments but doesn't say how many are needed.")
            for need in route.get("requires", []):
                if balance._key(key.split("/")[0], need) not in entries:
                    _fail(f"Knowledge {key} has a route that requires {need!r}, which no feature declares. Name another feature's as feature/name.")
    _check_can_be_learned(entries)
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


def check_no_tags_in_patches(features):
    """Ores, plants and ruins are read by name on the server, and a tag there stops the whole file from loading."""
    fields = {"ores": ("replaces", "biomes"), "plants": ("on", "biomes"), "ruins": ("on", "replaces", "biomes")}
    for feature_id, feature in features.items():
        for table, names in fields.items():
            entries = feature["manifest"].get(table, [])
            for entry in entries.values() if isinstance(entries, dict) else entries:
                for field in names:
                    tags = [value for value in entry.get(field) or [] if str(value).startswith("#")]
                    if tags:
                        _fail(f"{feature_id} has {tags[0]} in the {field} of one of its {table}. Those only take exact names, "
                              "so list them instead of using a tag. Only mob spawns can use tags.")


def _is_share(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 1


def check_ruins(features):
    """The server reads every ruin at once, so one it can't place stops all of them. And one with no way to appear would just never turn up."""
    for feature_id, feature in features.items():
        for name, ruin in feature["manifest"].get("ruins", {}).items():
            label = f"Ruin {feature_id}/{name}"
            if bool(ruin.get("parts")) == bool(ruin.get("layouts")):
                _fail(f"{label} needs either parts, for one fixed shape, or layouts, for several to pick from, and not both.")
            layouts = balance.ruin_layouts(ruin)
            if not all(layouts):
                _fail(f"{label} has a layout with nothing in it.")
            for layout in layouts:
                for part in layout:
                    if not all(isinstance(part.get(axis), int) and not isinstance(part.get(axis), bool) and 0 <= part[axis] < 16 for axis in "xz"):
                        _fail(f"{label} has a part at x {part.get('x')}, z {part.get('z')}. A ruin has to fit in one chunk, so both run from 0 to 15.")
                    if "chance" in part and not _is_share(part["chance"]):
                        _fail(f"{label} has a part with chance {part['chance']!r}. It's how often that part is there, above 0 and up to 1.")
                    if not isinstance(part.get("block"), str) or not BLOCK_WITH_STATE.fullmatch(part["block"]):
                        _fail(f"{label} has a part with block {part.get('block')!r}. A block state goes after the name, like minecraft:ladder[facing=north].")
                    if "loot" in part and not isinstance(part["loot"], dict):
                        _fail(f"{label} has a part with loot {part['loot']!r}, which isn't a loot table.")
                    # With nowhere to put it, it would count as a source of what's in it and never hand any of it out.
                    if "loot" in part and not LOOT_CONTAINERS.fullmatch(balance.part_block(part)):
                        _fail(f"{label} gives loot to {part.get('block')}, which can't hold any. Only vanilla's chests, barrels, shulker boxes, "
                              "dispensers, droppers, hoppers and crafters can.")
            spacing = ruin.get("spacing")
            if spacing is not None and (not isinstance(spacing, int) or isinstance(spacing, bool) or spacing < 1):
                _fail(f"{label} has spacing {spacing!r}. It's a whole number of chunks, at least 1.")
            if "chance" in ruin and not _is_share(ruin["chance"]):
                _fail(f"{label} has chance {ruin['chance']!r}. It has to be above 0 and up to 1.")
            if "chance" not in ruin and not spacing:
                _fail(f"{label} needs a chance per chunk, or a spacing, or it would never appear.")
            if ruin.get("followTerrain") and ruin.get("underground"):
                _fail(f"{label} follows the terrain and is underground. Only something on the surface has terrain to follow.")
            if "maxSlope" in ruin:
                if not ruin.get("followTerrain"):
                    _fail(f"{label} has a maxSlope, which only means something with followTerrain.")
                if not isinstance(ruin["maxSlope"], int) or isinstance(ruin["maxSlope"], bool) or ruin["maxSlope"] < 0:
                    _fail(f"{label} has maxSlope {ruin['maxSlope']!r}. It's a whole number of blocks.")
            if "highGround" in ruin:
                if ruin.get("underground"):
                    _fail(f"{label} wants high ground and is underground. Only something on the surface can stand above what's around it.")
                if not isinstance(ruin["highGround"], int) or isinstance(ruin["highGround"], bool) or ruin["highGround"] < 1:
                    _fail(f"{label} has highGround {ruin['highGround']!r}. It's a whole number of blocks, at least 1.")


def check_block_drops(features):
    """An empty list looks like a block that drops nothing, but it's the same as leaving it out, and then the block drops itself."""
    for feature_id, feature in features.items():
        for name, block in feature["manifest"].get("blocks", {}).items():
            if block.get("drops") == []:
                _fail(f"Block {feature_id}/{name} has an empty list of drops. Leave it out, and it drops itself.")


def check_block_kinds(features):
    """What each kind of block needs is easy to get wrong, and most of it would just quietly look or act wrong."""
    for feature_id, feature in features.items():
        for name, block in feature["manifest"].get("blocks", {}).items():
            label = f"Block {feature_id}/{name}"
            family = block.get("family")
            if "hardness" in block and not (isinstance(block["hardness"], (int, float)) and not isinstance(block["hardness"], bool) and 0 <= block["hardness"] <= MOST_HARDNESS):
                _fail(f"{label} has hardness {block['hardness']!r}. It's from 0, which breaks at once, up to {MOST_HARDNESS}. For anything harder, use a family that is.")
            if family == "crop":
                if not isinstance(block.get("stages"), list) or len(block["stages"]) != CROP_STAGES:
                    _fail(f"{label} is a crop, so it needs \"stages\": a list of {CROP_STAGES} textures, from just planted to ripe.")
                if "growth" in block and not _is_share(block["growth"]):
                    _fail(f"{label} has growth {block['growth']!r}. It's how likely each random tick is to grow it a stage, above 0 and up to 1.")
            elif "stages" in block or "growth" in block or "young_drops" in block:
                _fail(f"{label} has stages, growth or young_drops, which only a crop can have.")
            if "connects" in block and family != "connected":
                _fail(f"{label} has connects, which only a connected block can have.")
            if block.get("emissive") and family in NOT_CUBES:
                _fail(f"{label} is emissive, but only a plain cube can be, and a {family} block isn't one.")
            if block.get("drops") == "nothing" and family == "crop":
                _fail(f"{label} is a crop that drops nothing, so nobody could ever harvest it.")


def check_items(features):
    for feature_id, feature in features.items():
        for name, item in feature["manifest"].get("items", {}).items():
            label = f"Item {feature_id}/{name}"
            use = item.get("use")
            if use is not None:
                if not isinstance(use, dict) or not isinstance(use.get("seconds"), (int, float)) or isinstance(use.get("seconds"), bool) or not 0 < use["seconds"] <= MOST_USE_SECONDS:
                    _fail(f"{label} has use {use!r}. It needs seconds, above 0 and up to {MOST_USE_SECONDS}, and can have an animation.")
                if use.get("animation", "none") not in USE_ANIMATIONS:
                    _fail(f"{label} has use animation {use.get('animation')!r}. Use one of {sorted(USE_ANIMATIONS)}.")
                if "minecraft:consumable" in (item.get("components") or {}):
                    _fail(f"{label} has both a use and minecraft:consumable. It's either something timed that goes to a module, or something eaten.")
            tooltip = item.get("tooltip")
            if tooltip is not None and not (isinstance(tooltip, list) and all(isinstance(line, str) for line in tooltip)):
                _fail(f"{label} has tooltip {tooltip!r}. It's a list of lines of text.")
            compass = item.get("compass")
            if compass is not None and not (isinstance(compass, list) and MIN_COMPASS_FRAMES <= len(compass) <= MAX_COMPASS_FRAMES and all(isinstance(frame, str) for frame in compass)):
                _fail(f"{label} has compass {compass!r}. It's a list of {MIN_COMPASS_FRAMES} to {MAX_COMPASS_FRAMES} textures, the first pointing straight ahead and the rest going round clockwise.")
            variants = item.get("variants")
            if variants is not None and not (isinstance(variants, dict) and variants and all(isinstance(texture, str) for texture in variants.values())):
                _fail(f"{label} has variants {variants!r}. It's names and the texture for each, like {{\"gilded\": \"ledger_gilded\"}}.")


def _inventory_place(panel):
    """Where the player's own slots go, as the companion works it out, or None if it has none."""
    inventory = panel.get("inventory")
    if inventory is False:
        return None
    if inventory is None:
        return (panel["width"] - PLAYER_INVENTORY_WIDTH) // 2 + 1, panel["height"] - PLAYER_INVENTORY_FROM_BOTTOM
    return inventory["x"], inventory["y"]


def _text_overlaps(panel):
    """The title and "Inventory" are drawn for you, which is easy to forget, and text on text can't be read. It's worked out from the text a
    panel starts with, using about the narrowest a line of that text could be, so anything this finds really does overlap."""
    boxes = []
    if panel.get("title"):
        boxes.append(("its title", panel.get("title_x", TITLE_PLACE[0]), panel.get("title_y", TITLE_PLACE[1]), len(panel["title"]) * NARROW_CHARACTER, TEXT_LINE, None))
    place = _inventory_place(panel)
    if place:
        boxes.append(("the game's \"Inventory\" label", place[0], place[1] - INVENTORY_LABEL_ABOVE, len("Inventory") * NARROW_CHARACTER, TEXT_LINE, None))
    for widget in panel.get("widgets", []):
        if widget.get("type") == "label" and widget.get("text") and all(isinstance(widget.get(axis), int) for axis in "xy"):
            wide = len(widget["text"]) * NARROW_CHARACTER
            wrapped = widget.get("width") if isinstance(widget.get("width"), int) and widget.get("width") > 0 else wide
            lines = max(1, -(-wide // wrapped))
            boxes.append((f"the label {widget['text']!r}", widget["x"], widget["y"], min(wide, wrapped), lines * TEXT_LINE, widget.get("page")))
    problems = []
    for (first, x, y, wide, high, page), (second, other_x, other_y, other_wide, other_high, other_page) in itertools.combinations(boxes, 2):
        same_page = not page or not other_page or page == other_page
        if same_page and x < other_x + other_wide and other_x < x + wide and y < other_y + other_high and other_y < y + high:
            problems.append(f"{first} at {x}, {y} and {second} at {other_x}, {other_y} overlap, so neither can be read. The game draws the title and the \"Inventory\" label for you.")
    return problems


def _missing_frames(feature, panel):
    """With a background, a panel's art has to show where each slot is. Without that, a player's items float on nothing."""
    path = feature["dir"] / "assets" / "panels" / f"{panel.get('background')}.png"
    if not panel.get("background") or not path.exists():
        return []
    with Image.open(path) as art:
        pixels = art.convert("RGBA")
    across, down = pixels.width / panel["width"], pixels.height / panel["height"]

    def plain(x, y):
        box = (int((x - FRAME_MARGIN) * across), int((y - FRAME_MARGIN) * down), int((x + SLOT_ITEM + FRAME_MARGIN) * across), int((y + SLOT_ITEM + FRAME_MARGIN) * down))
        colours = pixels.crop(box).getcolors(maxcolors=1)
        return colours is not None

    problems = []
    place = _inventory_place(panel)
    if place and any(plain(place[0] + column * SLOT_STEP, place[1] + row * SLOT_STEP + (HOTBAR_GAP if row == HOTBAR_ROW else 0)) for row in (0, HOTBAR_ROW) for column in (0, 8)):
        problems.append(f"its background shows no frames for the player's inventory at {place[0]}, {place[1]}, so their items would float on nothing. "
                        "Draw them, or start from panel_back in assetkit's textures, or use \"inventory\": false if it doesn't need them.")
    for widget in panel.get("widgets", []):
        if widget.get("type") == "slot" and all(isinstance(widget.get(axis), int) for axis in "xy") and plain(widget["x"], widget["y"]):
            problems.append(f"its background shows no frame for the item slot at {widget['x']}, {widget['y']}, so nobody could tell it was there.")
    return problems


def _panel_problems(feature, panel):
    """Everything that would stop a panel working or fitting, as text, so a builder gets all of it at once."""
    width, height = panel.get("width"), panel.get("height")
    if not all(isinstance(number, int) and not isinstance(number, bool) for number in (width, height)) or not (0 < width <= MOST_PANEL_WIDTH and 0 < height <= MOST_PANEL_HEIGHT):
        return [f"its size is {width} by {height}. It has to fit on a small screen, so it can be at most {MOST_PANEL_WIDTH} by {MOST_PANEL_HEIGHT}."]
    problems = []
    images = feature["dir"] / "assets" / "panels"

    def needs_image(name, where):
        if not (images / f"{name}.png").exists():
            problems.append(f"{where} uses assets/panels/{name}.png, which doesn't exist.")

    if panel.get("background"):
        needs_image(panel["background"], "its background")
    inventory = panel.get("inventory")
    if inventory is not None and inventory is not False:
        if not isinstance(inventory, dict) or not all(isinstance(inventory.get(axis), int) for axis in "xy"):
            problems.append(f"its inventory is {inventory!r}. It's where the player's own slots go, like {{\"x\": 8, \"y\": 84}}, or false to leave them out.")
        elif inventory["x"] + PLAYER_INVENTORY_WIDTH > width or inventory["y"] + PLAYER_INVENTORY_HEIGHT > height:
            problems.append(f"the player's inventory at {inventory['x']}, {inventory['y']} takes {PLAYER_INVENTORY_WIDTH} by {PLAYER_INVENTORY_HEIGHT}, which doesn't fit in {width} by {height}.")
    seen, pages = set(), {tab.get("id") for widget in panel.get("widgets", []) if widget.get("type") == "tabs" for tab in widget.get("tabs", [])}
    for widget in panel.get("widgets", []):
        kind, label = widget.get("type"), f"{widget.get('type')} {widget.get('id', '')}".strip()
        if kind not in PANEL_WIDGETS:
            problems.append(f"it has a widget of type {kind!r}. Use one of {sorted(PANEL_WIDGETS)}.")
            continue
        wide, high = widget.get("width", PANEL_WIDGETS[kind]), widget.get("height", PANEL_WIDGETS[kind])
        if not all(isinstance(widget.get(axis), int) and not isinstance(widget.get(axis), bool) for axis in "xy") or not all(isinstance(size, int) for size in (wide, high)):
            problems.append(f"{label} needs whole numbers for x and y, and for width and height if it has them.")
            continue
        if widget["x"] < 0 or widget["y"] < 0 or widget["x"] + wide > width or widget["y"] + high > height:
            problems.append(f"{label} at {widget['x']}, {widget['y']}, {wide} by {high}, goes outside the panel, which is {width} by {height}.")
        identifier = widget.get("id")
        if identifier in seen:
            problems.append(f"two widgets are called {identifier}.")
        if identifier:
            seen.add(identifier)
        elif kind in PANEL_NEEDS_ID:
            problems.append(f"a {kind} needs an id, so a module can tell which one it is.")
        if widget.get("page") and widget["page"] not in pages:
            problems.append(f"{label} is on page {widget['page']!r}, which no tabs have.")
        for field in bundles.PANEL_IMAGE_FIELDS:
            if widget.get(field):
                needs_image(widget[field], label)
        if kind == "slot" and not (isinstance(widget.get("slot"), int) and not isinstance(widget.get("slot"), bool) and widget["slot"] >= 0):
            problems.append(f"an item slot at {widget['x']}, {widget['y']} needs \"slot\": which slot of the inventory it shows, from 0.")
        if kind == "image" and not widget.get("image"):
            problems.append(f"an image at {widget['x']}, {widget['y']} doesn't say which image.")
        if kind == "bar" and not widget.get("image") and not widget.get("color"):
            problems.append(f"{label} needs an image or a color to fill with.")
        if kind == "bar" and widget.get("direction", "right") not in PANEL_BAR_DIRECTIONS:
            problems.append(f"{label} has direction {widget.get('direction')!r}. Use one of {sorted(PANEL_BAR_DIRECTIONS)}.")
        if kind == "icon" and not widget.get("icon") and not identifier:
            problems.append(f"an icon at {widget['x']}, {widget['y']} needs an item, or an id for a module to set one by.")
        if kind == "mob":
            mob = str(widget.get("mob"))
            if not mob.startswith("minecraft:") and not widget.get("portrait"):
                problems.append(f"a mob preview of {mob} needs a \"portrait\" image, because only vanilla's mobs can be drawn on a screen. Render one from its model with assetkit.")
        if kind == "text_field" and not (isinstance(widget.get("max_length"), int) and 0 < widget["max_length"] <= MOST_TYPED):
            problems.append(f"{label} needs a max_length, from 1 to {MOST_TYPED}.")
        if kind == "tabs" and not widget.get("tabs"):
            problems.append(f"{label} has no tabs in it.")
        if kind == "list" and not (isinstance(widget.get("max_rows", 1), int) and 0 < widget.get("max_rows", 1) <= 45):
            problems.append(f"{label} has max_rows {widget.get('max_rows')!r}. It's how many rows it can ever have, up to 45.")
    if not problems:
        problems += _text_overlaps(panel) + _missing_frames(feature, panel)
    copied = json.loads(json.dumps(panel))
    places = bundles.panel_chest_slots(copied)
    if places > bundles.CHEST_ROW * MOST_CHEST_ROWS:
        problems.append(f"it would need {places} places in the plain chest someone with no companion sees, and a chest has {bundles.CHEST_ROW * MOST_CHEST_ROWS}. "
                        "Item slots, buttons, tabs, rows of a list and anything with an id each take one, so use fewer, or leave off some ids.")
    return problems


def check_panels(features):
    """A panel goes to friends' screens with nothing else looking at it first, so what's wrong has to be found here."""
    problems = []
    for feature_id, feature in features.items():
        for name, panel in feature["manifest"].get("panels", {}).items():
            problems += [f"Panel {feature_id}/{name}: {problem}" for problem in _panel_problems(feature, panel)]
    if problems:
        _fail("\n".join(problems))


def check_screen_effects(features):
    """A shader runs for every pixel of every frame on friends' computers, and one that never finishes can hang a graphics card."""
    for feature_id, feature in features.items():
        for name in feature["manifest"].get("screen_effects", []):
            label = f"Screen effect {feature_id}/{name}"
            path = feature["dir"] / "assets" / "shaders" / f"{name}.fsh"
            if not path.exists():
                _fail(f"{label} needs assets/shaders/{name}.fsh.")
            text = path.read_text(encoding="utf-8")
            if len(text) > MOST_SHADER_CHARACTERS:
                _fail(f"{label} is {len(text)} characters long, over the limit of {MOST_SHADER_CHARACTERS}. It runs for every pixel of every frame, so keep it simple.")
            if not text.lstrip().startswith("#version 330"):
                _fail(f"{label} has to start with #version 330, which is what the game's own are. See 'Screen effects' in docs/content-types.md.")
            if "#moj_import" in text:
                _fail(f"{label} uses #moj_import, which this version of the game doesn't have. Use #include <minecraft:globals.glsl>.")
            if re.search(r"\b(while|do)\b", text):
                _fail(f"{label} uses a while or do loop, which could never finish and hang a player's graphics card. Use a for loop with a fixed count.")


def check_machines(features):
    """A machine with no slots to take from, or a recipe that says what it makes in two ways, would quietly do less than it looks like."""
    for feature_id, feature in features.items():
        for name, block in feature["manifest"].get("blocks", {}).items():
            inventory = block.get("inventory")
            if inventory is None:
                continue
            label = f"Block {feature_id}/{name}"
            if block.get("family") not in MACHINE_FAMILIES:
                _fail(f"{label} has an inventory, which only a machine or model block can have.")
            if not isinstance(inventory, dict) or not set(inventory) <= INVENTORY_KINDS or not all(isinstance(count, int) and not isinstance(count, bool) and count >= 0 for count in inventory.values()):
                _fail(f"{label} has inventory {inventory!r}. It's whole numbers of slots, like {{\"inputs\": 2, \"fuel\": 1, \"outputs\": 1}}.")
            if not 0 < sum(inventory.values()) <= MOST_MACHINE_SLOTS:
                _fail(f"{label} has {sum(inventory.values())} slots in its inventory. It can have from 1 to {MOST_MACHINE_SLOTS}.")
        for name, recipe in feature["manifest"].get("recipes", {}).items():
            if not isinstance(recipe.get("machine"), str):
                continue
            label = f"Recipe {feature_id}/{name}"
            if ("output" in recipe) == ("outputs" in recipe):
                _fail(f"{label} needs either output, for one thing, or outputs, for several, and not both.")
            made = recipe.get("outputs", [recipe.get("output")])
            if not isinstance(made, list) or not made or not all(isinstance(output, dict) and isinstance(output.get("item"), str) and isinstance(output.get("count"), int) for output in made):
                _fail(f"{label} has outputs {made!r}. Each is like {{\"item\": \"$item:name\", \"count\": 1}}.")


def check_mob_sounds(features):
    """A sound the pack doesn't have plays nothing, and a kind of sound nothing asks for never plays, and neither says so."""
    sounds = {f"{feature_id}/{name}" for feature_id, feature in features.items() for name in feature["manifest"].get("sounds", [])}
    for feature_id, feature in features.items():
        for name, mob in feature["manifest"].get("mobs", {}).items():
            label = f"Mob {feature_id}/{name}"
            own = mob.get("sounds", {})
            if not isinstance(own, dict) or not set(own) <= MOB_SOUNDS:
                _fail(f"{label} has sounds {own!r}. It's an object with any of {sorted(MOB_SOUNDS)}, like {{\"hurt\": \"$sound:yelp\"}}.")
            for kind, sound in own.items():
                found = TOKEN.fullmatch(str(sound))
                if found and found.group(1) == "sound":
                    if balance._key(feature_id, found.group(2)) not in sounds:
                        _fail(f"{label} has {kind} sound {sound}, which no feature lists in its sounds.")
                elif not str(sound).startswith("minecraft:"):
                    _fail(f"{label} has {kind} sound {sound!r}. Use one of this world's as $sound:name, or vanilla's as minecraft:name.")


def _model_cost(path):
    """Bones that have cubes, because each is an entity for players' computers to draw, and the number of cubes."""
    model = json.loads(path.read_text(encoding="utf-8"))
    cubes = {element["uuid"] for element in model.get("elements", [])}

    def bones_in(node):
        children = node.get("children", [])
        own = any(isinstance(child, str) and child in cubes for child in children)
        return own + sum(bones_in(child) for child in children if isinstance(child, dict))

    return sum(bones_in(root) for root in model.get("outliner", []) if isinstance(root, dict)), len(cubes)


def check_model_costs(features):
    """Something that roams around in numbers costs more than one boss, so each has its own limit."""
    for feature_id, feature in features.items():
        models = feature["dir"] / "assets" / "models"
        drawn = [(name, mob.get("model", name), MAX_BONES_ROAMING if mob.get("spawn") else MAX_BONES_ONE_OFF)
                 for name, mob in feature["manifest"].get("mobs", {}).items()]
        drawn += [(name, block["model"], MAX_BONES_BLOCK) for name, block in feature["manifest"].get("blocks", {}).items() if block.get("model")]
        drawn += [(target, model, MAX_BONES_ROAMING) for target, model in feature["manifest"].get("reskins", {}).items()]
        for name, model, limit in drawn:
            path = models / f"{model}.bbmodel"
            if not path.exists():
                continue
            bones, cubes = _model_cost(path)
            if bones > limit:
                _fail(f"{feature_id}/{name} has {bones} moving parts, over the limit of {limit} for something like it. Each is an entity "
                      "for players' computers to draw, so merge some. A boss that only a module summons is allowed more.")
            if cubes > MAX_MODEL_CUBES:
                _fail(f"{feature_id}/{name} has {cubes} cubes, over the limit of {MAX_MODEL_CUBES}. Use a coarser grain.")


def check_minds(features):
    """What a mob's mind is allowed to do comes from here, because the model choosing can be talked into anything."""
    knowledge = {f"{feature_id}/{name}" for feature_id, feature in features.items() for name in feature["manifest"].get("knowledge", {})}
    for feature_id, feature in features.items():
        for name, mob in feature["manifest"].get("mobs", {}).items():
            mind = mob.get("mind")
            if mind is None:
                continue
            label = f"Mob {feature_id}/{name}'s mind"
            character = str(mind.get("character", "")).strip()
            if not character or len(character) > MAX_CHARACTER:
                _fail(f"{label} needs a character of up to {MAX_CHARACTER} characters, because it's read at every decision.")
            if mind.get("voice", "words") not in MIND_VOICES:
                _fail(f"{label} has voice {mind.get('voice')!r}. Use one of {sorted(MIND_VOICES)}.")
            unknown = set(mind.get("actions", [])) - MIND_ACTIONS
            if unknown:
                _fail(f"{label} lists actions {sorted(unknown)}. Use only {sorted(MIND_ACTIONS)}.")
            actions = set(mind.get("actions", []))
            if "attack" in actions and mob.get("behaviour") not in ("hostile", "neutral"):
                _fail(f"{label} can attack, but it's {mob.get('behaviour')}. Make it neutral or hostile, or leave attack out.")
            if bool(mind.get("stash")) != ("give" in actions):
                _fail(f"{label} needs both a stash and the give action, or neither.")
            if bool(mind.get("teaches")) != ("teach" in actions):
                _fail(f"{label} needs both teaches and the teach action, or neither.")
            if bool(mind.get("leads_to")) != ("lead" in actions):
                _fail(f"{label} needs both leads_to and the lead action, or neither.")
            stash = mind.get("stash", [])
            if sum(item.get("count", 0) for item in stash) > MAX_STASH or any(item.get("count", 0) < 1 for item in stash):
                _fail(f"{label} has too large a stash. It's per player, so {MAX_STASH} things in all is the limit.")
            for entry in mind.get("teaches", {}):
                if (entry if "/" in entry else f"{feature_id}/{entry}") not in knowledge:
                    _fail(f"{label} teaches {entry}, which no feature declares. Knowledge needs its own routes as well, so no one depends on a mob.")
            model = feature["dir"] / "assets" / "models" / f"{mob.get('model', name)}.bbmodel"
            if model.exists():
                have = {animation.get("name") for animation in json.loads(model.read_text(encoding="utf-8")).get("animations", [])}
                missing = set(mind.get("animations", [])) - have
                if missing:
                    _fail(f"{label} lists animations {sorted(missing)}, which its model doesn't have.")


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
    check_changes_to_others(features)
    check_knowledge(features)
    check_loot_format(features)
    check_no_tags_in_patches(features)
    check_ruins(features)
    check_block_drops(features)
    check_block_kinds(features)
    check_items(features)
    check_screen_effects(features)
    check_panels(features)
    check_machines(features)
    check_mob_sounds(features)
    check_model_costs(features)
    check_minds(features)
    balance.run(features)
