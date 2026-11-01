"""Changes a number in something already released, with no builder and no review. "This is too rare" shouldn't take
minutes of building, so plain code makes the change and the normal gates still judge the result.

Only the numbers listed here can be changed. Anything else is a job for a builder.
"""
import json
import math

BASE_ATTACK_DAMAGE = 1.0
BASE_ATTACK_SPEED = 4.0
MODIFIER_BASE = {"attack_damage": BASE_ATTACK_DAMAGE, "attack_speed": BASE_ATTACK_SPEED, "armor": 0, "armor_toughness": 0}
ITEM_FIELDS = {"durability", "mining_speed", "nutrition", "saturation", *MODIFIER_BASE}
MOB_FIELDS = {"health", "damage", "speed", "armor", "followRange", "spawn.weight", "spawn.cap", "drops.count"}
BLOCK_FIELDS = {"drops.count"}
PROJECTILE_FIELDS = {"damage", "speed", "gravity", "lifetime", "shots_per_second"}
VEHICLE_FIELDS = {"speed", "reverse", "acceleration", "turn", "climb", "health"}
RECIPE_FIELDS = {"output.count", "json.result.count", "json.cookingtime"}
ADDITIVE_FIELD = {"ores": "veinsPerChunk", "plants": "perChunk"}
# Chunks remember the ids they've had, so more of something in the world has to be a new entry.
EXTRA = "_more"


class TuneError(Exception):
    """Why a change can't be made, worded for whoever asked."""


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise TuneError(f"{value!r} isn't a usable number.")
    return value


def _set_path(entry, field, value):
    parts = field.split(".")
    for part in parts[:-1]:
        entry = entry.get(part)
        if not isinstance(entry, dict):
            raise TuneError(f"This doesn't have {field}. A builder would need to add it.")
    if parts[-1] not in entry:
        raise TuneError(f"This doesn't have {field}. A builder would need to add it.")
    before = entry[parts[-1]]
    entry[parts[-1]] = value
    return before


def _count(field, value):
    """A drop count is a pair of lowest and highest. Anything else is one number."""
    if not field.endswith("drops.count"):
        return _number(value)
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(part, int) and part >= 0 for part in value) or value[0] > value[1]:
        raise TuneError("A drop count is two whole numbers, lowest then highest, like [1, 3].")
    return value


def _component_maps(manifest, name):
    """Where an item's real numbers live: on the item itself, and on the results of the recipes that make it."""
    maps = []
    item = manifest.get("items", {}).get(name, {})
    if isinstance(item.get("components"), dict):
        maps.append(item["components"])
    tokens = {f"$item:{name}", f"$item:{manifest.get('id')}/{name}"}
    for recipe in manifest.get("recipes", {}).values():
        result = recipe.get("json", {}).get("result")
        if isinstance(result, dict) and result.get("id") in tokens and isinstance(result.get("components"), dict):
            maps.append(result["components"])
    return maps


def _set_in_components(components, field, value):
    """Returns True if this set of components has the number at all, and sets it."""
    changed = False
    food = components.get("minecraft:food")
    if field in ("nutrition", "saturation") and isinstance(food, dict) and field in food:
        food[field], changed = value, True
    if field == "durability" and "minecraft:max_damage" in components:
        components["minecraft:max_damage"], changed = value, True
    tool = components.get("minecraft:tool")
    if field == "mining_speed" and isinstance(tool, dict):
        for rule in tool.get("rules", []):
            if "speed" in rule:
                rule["speed"], changed = value, True
    modifiers = components.get("minecraft:attribute_modifiers")
    if field in MODIFIER_BASE and modifiers is not None:
        for modifier in modifiers.get("modifiers", []) if isinstance(modifiers, dict) else modifiers:
            kind = str(modifier.get("type", "")).removeprefix("minecraft:").removeprefix("generic.")
            if kind == field:
                # A modifier adds to the player's own base, while what's asked for is what the tooltip says.
                modifier["amount"], changed = round(value - MODIFIER_BASE[field], 3), True
    return changed


def _tune_item(manifest, name, field, value):
    if field not in ITEM_FIELDS:
        raise TuneError(f"An item's numbers are {', '.join(sorted(ITEM_FIELDS))}. Anything else needs a builder.")
    value = _number(value)
    changed = any([_set_in_components(components, field, value) for components in _component_maps(manifest, name)])
    stats = manifest.get("items", {}).get(name, {}).get("stats")
    if isinstance(stats, dict) and field in stats:
        stats[field], changed = value, True
    if not changed:
        raise TuneError(f"{name} doesn't have {field}. A builder would need to add it.")


def _tune_additive(manifest, table, name, field, value):
    """More of something in the world is a new entry for the difference, because it can't be taken out again."""
    value = _number(value)
    if field != ADDITIVE_FIELD[table]:
        raise TuneError(f"Only {ADDITIVE_FIELD[table]} can change here.")
    entries = manifest.get(table, [])
    base = name.split(EXTRA)[0]
    family = [entry for entry in entries if entry.get("id") == base or str(entry.get("id")).startswith(base + EXTRA)]
    if not family:
        raise TuneError(f"This feature has no {table} entry called {name}.")
    current = sum(entry[field] for entry in family)
    if value <= current:
        raise TuneError(f"It's at {current:g} now, and what's already in the world can't be taken out. To make it less rewarding, "
                        "lower the block's drops.count instead. Land generated later can only be changed by a builder.")
    # Veins are whole numbers on the server, so a raise rounds up rather than being lost.
    difference = math.ceil(value - current) if table == "ores" else round(value - current, 3)
    entries.append({**family[0], "id": f"{base}{EXTRA}{len(family)}", field: difference})


def apply(manifest, table, name, field, value, reason):
    """Makes one change to a feature's manifest. Raises TuneError if it can't be made this way."""
    if len(str(reason).strip()) < 15:
        raise TuneError("Say why, so the reason can be read later.")
    if table in ADDITIVE_FIELD:
        _tune_additive(manifest, table, name, field, value)
        block = next((entry["block"] for entry in manifest[table] if entry["id"].startswith(name.split(EXTRA)[0])), None)
        if block:
            manifest.setdefault("changes_reached", {})[block] = reason
        return
    if table == "items":
        if name not in manifest.get("items", {}):
            raise TuneError(f"This feature has no item called {name}.")
        _tune_item(manifest, name, field, value)
    elif table in ("mobs", "blocks", "recipes", "projectiles", "vehicles"):
        allowed = {"mobs": MOB_FIELDS, "blocks": BLOCK_FIELDS, "recipes": RECIPE_FIELDS, "projectiles": PROJECTILE_FIELDS, "vehicles": VEHICLE_FIELDS}[table]
        if field not in allowed:
            raise TuneError(f"A {table[:-1]}'s numbers are {', '.join(sorted(allowed))}. Anything else needs a builder.")
        entry = manifest.get(table, {}).get(name)
        if entry is None:
            raise TuneError(f"This feature has no {table[:-1]} called {name}.")
        _set_path(entry, field, _count(field, value))
    else:
        raise TuneError("Numbers can be changed in items, blocks, mobs, projectiles, vehicles, recipes, ores and plants.")
    if table != "recipes":
        manifest.setdefault("changes_reached", {})[name] = reason
    else:
        for output in _recipe_outputs(manifest, name):
            manifest.setdefault("changes_reached", {})[output] = reason


def _recipe_outputs(manifest, name):
    """The names in this feature that a recipe makes, because changing a recipe changes them."""
    recipe = manifest["recipes"][name]
    text = json.dumps(recipe.get("outputs") or recipe.get("output") or recipe.get("json", {}).get("result"))
    return [thing for table in ("items", "blocks") for thing in manifest.get(table, {}) if f":{thing}\"" in text or f"/{thing}\"" in text]
