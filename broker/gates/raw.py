"""Instant checks on the vanilla files a feature ships in raw/. A raw file can do anything the game can, so everything that keeps the world
fair and the server up has to be checked here: a bad one would stop the server starting, and a clever one could get around every tier.

What isn't understood is refused. An enchantment effect with no number to measure, for example, is only allowed at the tier with no limits.
Every vanilla number here was read from the 26.3 game jar, and the names are in vanilla_ids.json. See scripts/refresh-vanilla-ids.py.
"""
import json
import math
import pathlib
import re

from broker import rawpack
from broker.bundles import TOKEN
from broker.gates import GateFailed, balance

GATE = "static"
VANILLA = json.loads((pathlib.Path(__file__).parent / "vanilla_ids.json").read_text(encoding="utf-8"))
MOST_RAW_BYTES = 32 * 1024 * 1024
# Anything a player might be sent to, or made to run, by clicking on some text.
ESCAPE_KEYS = {
    "function": "a function can run any command, so it gets around every balance check. Use a server module",
    "click_event": "clicking on text could run a command as a player or send them to a web page. Leave it out",
    "clickEvent": "clicking on text could run a command as a player or send them to a web page. Leave it out",
}
ESCAPE_VALUES = {
    "minecraft:run_command": "it can run any command, so it gets around every balance check. Use a server module",
    "minecraft:run_function": "it can run any command, so it gets around every balance check. Use a server module",
}
# These hold other items or whole mobs and blocks, whatever the checks on loot say about the thing itself.
CARRYING_COMPONENTS = {"container", "bundle_contents", "charged_projectiles", "block_entity_data", "entity_data", "bucket_entity_data"}
OWN_ID = re.compile(r"\bgm:[a-z]")
# A mob variant says its picture's whole path, and only the name at the end of that is given out.
PATH_TO_OWN_NAME = re.compile(rf"gm:entity/[a-z_]+/\${rawpack.NAME_TOKEN}:{rawpack.NAME_PART}")
OLD_LOOT_FIELDS = {"functions", "conditions"}
FIELDS_THAT_CAN_ALSO_BE = {"description": {"str", "dict"}, "title": {"str", "dict"}, "author": {"str", "dict"}, "sound_event": {"str", "dict"},
                           "supported_items": {"str", "list"}, "primary_items": {"str", "list"}, "exclusive_set": {"str", "list"}}
JSON_NAMES = {"str": "text", "int": "a number", "float": "a number", "bool": "true or false", "list": "a list", "dict": "an object"}
# Vanilla's biggest single reward, for doing every effect in the game.
MOST_ADVANCEMENT_XP = 1000
ADVANCEMENT_FRAMES = {"task", "goal", "challenge"}
# What an ancient city's loot gets enchanted with, which is vanilla's strongest.
MOST_ENCHANT_LEVELS = 50
MOST_ENCHANTMENT_LEVEL = 5
# Unbreaking III and Breach IV. More of the first is close to never wearing out, which no tier allows.
MOST_DAMAGE_SKIPPED = 0.75
MOST_ARMOUR_IGNORED = 0.6
EARLY_TIER = "iron"
CHEST_TABLES = "minecraft:chests/"
TAG_REGISTRIES = {"tags/block": {"block"}, "tags/item": {"item", "block"}, "tags/entity_type": {"mob"}, "tags/fluid": set(), "tags/game_event": set(),
                  "tags/enchantment": {"enchantment"}, "tags/damage_type": {"damage_type"}, "tags/banner_pattern": {"banner_pattern"},
                  "tags/painting_variant": {"painting_variant"}, "tags/instrument": {"instrument"}, "tags/worldgen/biome": {"biome"}}
TAG_NAMES = {"tags/block": "block", "tags/item": "item", "tags/entity_type": "entity_type", "tags/fluid": "fluid", "tags/game_event": "game_event",
             "tags/enchantment": "enchantment", "tags/damage_type": "damage_type", "tags/worldgen/biome": "biome"}
# What these do is the cost of something vanilla, so one more cheap thing in the list gets around it: diamond gear from a cheap material, say.
UNFAIR_TAGS = {
    "tags/item": re.compile(r"[a-z]+_tool_materials|repairs_[a-z_]+|beacon_payment_items"),
    "tags/block": re.compile(r"beacon_base_blocks|enchantment_power_provider"),
}
CLIMBABLE = "climbable"
LADDER = "ladder"
# How a mob variant looks is all it does, so these only need to be in the right shape.
DAMAGE_SCALING = {"never", "when_caused_by_living_non_player", "always"}
BONUS_DEFENCE_TAGS = ("is_fall", "is_fire", "is_explosion", "is_projectile", "is_drowning", "is_freezing", "is_lightning")
# Vanilla's strongest at its highest level, for each effect with a number that can be read. An effect that only applies sometimes gets vanilla's strongest
# for that: Sharpness is 3 for anything, and Smite 12.5 for some mobs. Protection is 4 for any damage, and Feather Falling 12 for falling.
ENCHANTMENT_MOSTS = {
    "minecraft:damage": (3.0, 12.5), "minecraft:smash_damage_per_fallen_block": (2.5, 2.5), "minecraft:knockback": (2.0, 2.0),
    "minecraft:damage_protection": (4.0, 12.0), "minecraft:repair_with_xp": (2.0, 2.0), "minecraft:fishing_luck_bonus": (3.0, 3.0),
    "minecraft:fishing_time_reduction": (15.0, 15.0), "minecraft:projectile_piercing": (4.0, 4.0), "minecraft:trident_return_acceleration": (3.0, 3.0),
    "minecraft:equipment_drops": (0.03, 0.03), "minecraft:mob_experience": (2.0, 2.0), "minecraft:block_experience": (2.0, 2.0),
}
# The attributes vanilla's enchantments change, how, and the most any of them does, because any other is something gear has no curve for.
ENCHANTMENT_ATTRIBUTES = {
    "minecraft:mining_efficiency": ("add_value", 26.0), "minecraft:oxygen_bonus": ("add_value", 3.0), "minecraft:submerged_mining_speed": ("add_multiplied_total", 4.0),
    "minecraft:water_movement_efficiency": ("add_value", 1.0), "minecraft:sneaking_speed": ("add_value", 0.45), "minecraft:sweeping_damage_ratio": ("add_value", 0.75),
    "minecraft:explosion_knockback_resistance": ("add_value", 0.6), "minecraft:burning_time": ("add_multiplied_base", 0.6),
}
# These change no number, and are a sound or a drawback.
ENCHANTMENT_HARMLESS = {"minecraft:prevent_armor_change", "minecraft:prevent_equipment_drop", "minecraft:crossbow_charging_sounds", "minecraft:trident_sound"}
# Rounding in a level's value shouldn't fail something that's exactly vanilla's.
ROUNDING = 1e-6
# Effects that only change how things look or sound, or that a limit can be read from.
ENCHANTMENT_ACTIONS = {"minecraft:post_attack", "minecraft:hit_block", "minecraft:post_piercing_attack", "minecraft:projectile_spawned"}
HARMLESS_ACTIONS = {"minecraft:play_sound", "minecraft:spawn_particles"}
MOST_MOB_EFFECT_LEVEL = 3
MOST_IGNITE_SECONDS = 8.0
# Flame, which only lights the arrow, however long it says.
MOST_IGNITE_SECONDS_ARROW = 100.0
# How each of these changes its number, where it isn't by adding to it. Anything else would be a multiplier hiding as a small number.
ENCHANTMENT_READINGS = {"minecraft:repair_with_xp": {"minecraft:multiply": "factor"}, "minecraft:block_experience": {"minecraft:set": "value", "minecraft:add": "value"},
                        "minecraft:mob_experience": {"minecraft:set": "value", "minecraft:add": "value"}}
ADD_ONLY = {"minecraft:add": "value"}
LOOT_FUNCTIONS = {f"minecraft:{name}" for name in VANILLA["loot_function"]}
LOOT_ENTRIES = {f"minecraft:{name}" for name in VANILLA["loot_entry"]}


def _strip(name):
    return str(name).removeprefix("minecraft:")


def _is_vanilla(name, table):
    return str(name).startswith("minecraft:") and _strip(name) in VANILLA[table]


# Everything features have


class _World:
    """Every raw file in every feature, looked up by what refers to it."""

    def __init__(self, features):
        self.features = features
        self.files = {}
        self.problems = []
        self.names = {}
        self.texture_folders = {}
        for feature_id, feature in features.items():
            try:
                self.files[feature_id] = rawpack.files(feature["dir"])
            except rawpack.Refused as error:
                self.files[feature_id] = []
                self.problems.append(f"{feature_id}: {error}")
                continue
            for raw in self.files[feature_id]:
                if raw.token:
                    self.names.setdefault(raw.token, set()).add(f"{feature_id}/{raw.name}")
                if raw.token == rawpack.TEXTURE_TOKEN:
                    self.texture_folders.setdefault(f"{feature_id}/{raw.name}", set()).add(raw.registry)
            for name in feature["manifest"].get("biomes", {}):
                self.names.setdefault("biome", set()).add(f"{feature_id}/{name}")
            self.names.setdefault("sound", set()).update(f"{feature_id}/{name}" for name in feature["manifest"].get("sounds", []))

    def has(self, kind, feature_id, name):
        return (name if "/" in name else f"{feature_id}/{name}") in self.names.get(kind, set())

    def anything_called(self, feature_id, name):
        key = name if "/" in name else f"{feature_id}/{name}"
        return any(key in names for names in self.names.values())

    def texture_in(self, feature_id, name, folder):
        return folder in self.texture_folders.get(name if "/" in name else f"{feature_id}/{name}", set())


def _strings(value):
    """Every string in something read from JSON, with keys."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)


def _keys(value):
    if isinstance(value, list):
        for item in value:
            yield from _keys(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)


def _check_references(value, label, feature_id, world, problems):
    """A name nothing answers to would only show up as something quietly not there, so each has to exist."""
    for text in _strings(value):
        for found in rawpack.TOKEN.finditer(text):
            kind, name = found.group(1), found.group(2)
            exists = world.anything_called(feature_id, name) if kind == rawpack.NAME_TOKEN else world.has(kind, feature_id, name)
            if not exists:
                problems.append(f"{label} refers to {found.group(0)}, and no feature has that. Look in raw/ for the right name, and that it's in the right folder.")
        for found in TOKEN.finditer(text):
            if found.group(1) == "sound" and not world.has("sound", feature_id, found.group(2)):
                problems.append(f"{label} refers to {found.group(0)}, which no feature lists in its \"sounds\".")


def _scan(value, label, problems):
    """What must not be in any file at all, however it's arranged."""
    for key in _keys(value):
        if key in ESCAPE_KEYS:
            problems.append(f"{label} has {key}, and {ESCAPE_KEYS[key]}.")
    for text in _strings(value):
        if text in ESCAPE_VALUES:
            problems.append(f"{label} uses {text}, and {ESCAPE_VALUES[text]}.")
        if OWN_ID.search(text) and not PATH_TO_OWN_NAME.fullmatch(text):
            problems.append(f"{label} has {text!r}. Don't write a gm: id yourself, because they're given out for you. Use $item:name, $block:name, $mob:name, or the token for its folder, like $enchantment:name.")


def _check_shape(contents, registry, label, problems):
    """A file with something missing stops the server starting. One with a misspelt field loads and quietly does less, which is worse."""
    shape = VANILLA["shapes"].get(registry)
    if shape is None:
        return
    missing = [field for field in shape["required"] if field not in contents]
    if missing:
        problems.append(f"{label} is missing {', '.join(missing)}. Every one of vanilla's has that.")
    unknown = sorted(set(contents) - set(shape["known"]))
    if unknown:
        problems.append(f"{label} has {', '.join(unknown)}, which none of vanilla's has, and the game ignores what it doesn't know without saying so. It can have {', '.join(shape['known'])}.")
    for field, value in contents.items():
        seen = set(shape["types"].get(field, ()))
        # A number's a number whether or not it has a point, and vanilla doesn't happen to use everything a field can be.
        allowed = seen | FIELDS_THAT_CAN_ALSO_BE.get(field, set()) | ({"int", "float"} if seen & {"int", "float"} else set())
        if seen and type(value).__name__ not in allowed:
            problems.append(f"{label} has {field} {json.dumps(value)[:80]}, and that has to be {' or '.join(sorted({JSON_NAMES[kind] for kind in allowed}))}. The server wouldn't start with this.")


# Numbers that depend on an enchantment's level or on chance


def _level_value(value, level):
    """What the game's level-based numbers come to at a level. NaN for anything else, because that fails every limit."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, dict):
        return math.nan
    kind = value.get("type")
    if kind == "minecraft:linear":
        return _level_value(value.get("base"), level) + _level_value(value.get("per_level_above_first"), level) * (level - 1)
    if kind == "minecraft:levels_squared":
        return level * level + _level_value(value.get("added", 0), level)
    if kind == "minecraft:clamped":
        return min(max(_level_value(value.get("value"), level), _level_value(value.get("min"), level)), _level_value(value.get("max"), level))
    if kind == "minecraft:fraction":
        below = _level_value(value.get("denominator"), level)
        return _level_value(value.get("numerator"), level) / below if below else math.nan
    if kind == "minecraft:lookup":
        values = value.get("values", [])
        return _level_value(values[level - 1] if isinstance(values, list) and level <= len(values) else value.get("fallback"), level)
    return math.nan


def _at_any_level(pick, value, top):
    """The strongest something gets over all its levels. What can't be read comes out as NaN, which fails any limit."""
    values = [_level_value(value, level) for level in range(1, top + 1)]
    return math.nan if any(math.isnan(number) for number in values) else pick(values)


def _most_at_any_level(value, top):
    return _at_any_level(max, value, top)


def _most_of_provider(value):
    """The biggest a number in a loot table can be. NaN for what can't be read, so that it fails."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict):
        if value.get("type") in ("minecraft:uniform",) or "max" in value:
            return _most_of_provider(value.get("max"))
        if value.get("type") == "minecraft:constant":
            return _most_of_provider(value.get("value"))
    return math.nan


# Enchantments


def _effect_strength(effect, top, readings=ADD_ONLY, pick=max):
    """The most this changes a number by. NaN if it does that in any way but the one its component is measured by."""
    kind = effect.get("type") if isinstance(effect, dict) else None
    if kind == "minecraft:all_of":
        return sum(_effect_strength(inner, top, readings, pick) for inner in effect.get("effects", []))
    return _at_any_level(pick, effect.get(readings[kind]), top) if kind in readings else math.nan


def _check_action(action, top, label, component, problems):
    """Something an enchantment does to a mob or the world when it's used. Anything that can't be read is refused, because it might summon or replace anything."""
    kind = action.get("type") if isinstance(action, dict) else None
    if kind in HARMLESS_ACTIONS:
        return
    if kind == "minecraft:all_of":
        for inner in action.get("effects", []):
            _check_action(inner, top, label, component, problems)
    elif kind == "minecraft:apply_mob_effect":
        amplifier = _most_at_any_level(action.get("max_amplifier", 0), top)
        if not amplifier <= MOST_MOB_EFFECT_LEVEL:
            problems.append(f"{label} applies a mob effect up to amplifier {amplifier:g}, over {MOST_MOB_EFFECT_LEVEL}, which is what vanilla's Bane of Arthropods gets to.")
    elif kind == "minecraft:ignite":
        seconds = _most_at_any_level(action.get("duration"), top)
        if not seconds <= (MOST_IGNITE_SECONDS_ARROW if component == "minecraft:projectile_spawned" else MOST_IGNITE_SECONDS):
            problems.append(f"{label} sets things alight for {seconds:g} seconds, over {MOST_IGNITE_SECONDS:g}, which is vanilla's Fire Aspect II.")
    else:
        problems.append(f"{label} has {kind} in {component}, and that has nothing to measure it against. "
                        "Use what's listed in 'Raw files' in docs/content-types.md, or tier mythic, or a server module.")


def _check_enchantment_power(contents, tier, label, problems):
    """Vanilla's best at its highest level is the limit, because players can already get that. beyond allows half as much again, and mythic has no limit."""
    if tier == balance.UNLIMITED:
        return
    if tier is not None and tier not in balance.TIERS:
        problems.append(f"{label} declares tier {tier!r}, but a tier must be one of {', '.join(balance.TIERS)}.")
        return
    margin = balance.BEYOND_MARGIN if tier == "beyond" else 1.0
    top = contents.get("max_level")
    if not isinstance(top, int) or isinstance(top, bool) or not 1 <= top <= MOST_ENCHANTMENT_LEVEL:
        problems.append(f"{label} has max_level {top!r}. It has to be from 1 to {MOST_ENCHANTMENT_LEVEL}, which is the highest of vanilla's, unless its tier is mythic.")
        return
    for component, entries in (contents.get("effects") or {}).items():
        where = f"{label}'s {component}"
        for entry in entries if isinstance(entries, list) else [entries]:
            effect = entry.get("effect", entry) if isinstance(entry, dict) else entry
            if component in ENCHANTMENT_MOSTS:
                always, sometimes = ENCHANTMENT_MOSTS[component]
                text = json.dumps(entry.get("requirements") or "") if isinstance(entry, dict) else ""
                # Protection's own condition is only that the damage can be protected from at all, so it doesn't count as narrowing it down.
                narrowed = any(tag in text for tag in BONUS_DEFENCE_TAGS) if component == "minecraft:damage_protection" else bool(entry.get("requirements") if isinstance(entry, dict) else False)
                limit = (sometimes if narrowed else always) * margin
                strength = _effect_strength(effect, top, ENCHANTMENT_READINGS.get(component, ADD_ONLY))
                if not strength <= limit + ROUNDING:
                    problems.append(f"{where} comes to {strength:g} at level {top}, over vanilla's best of {limit:g}. Lower it, or use a higher tier. It's measured by adding, because a multiplier's strength depends on everything else.")
            elif component == "minecraft:item_damage":
                if not _effect_strength(effect, top, {"minecraft:remove_binomial": "chance"}) <= MOST_DAMAGE_SKIPPED * margin + ROUNDING:
                    problems.append(f"{where} has to be a remove_binomial with a chance of at most 0.75, which is Unbreaking III. More than that is close to never wearing out, which no tier allows.")
            elif component == "minecraft:armor_effectiveness":
                if not _effect_strength(effect, top, pick=min) >= -MOST_ARMOUR_IGNORED * margin - ROUNDING:
                    problems.append(f"{where} is stronger than vanilla's Breach IV, at -0.6.")
            elif component == "minecraft:attributes":
                attribute = entry.get("attribute")
                if attribute not in ENCHANTMENT_ATTRIBUTES:
                    problems.append(f"{where} changes {attribute}, which no vanilla enchantment does, so there's nothing to compare it with. Use tier mythic, or a server module.")
                    continue
                operation, most = ENCHANTMENT_ATTRIBUTES[attribute]
                amount = _at_any_level(lambda values: max(map(abs, values)), entry.get("amount"), top)
                if entry.get("operation") != operation or not amount <= most * margin + ROUNDING:
                    problems.append(f"{where} comes to {amount:g} on {attribute}, using {entry.get('operation')}, and vanilla's best is {most * margin:g} using {operation}.")
            elif component in ENCHANTMENT_ACTIONS:
                _check_action(effect, top, where, component, problems)
            elif component not in ENCHANTMENT_HARMLESS:
                problems.append(f"{label} has the effect {component}, and that has nothing to measure it against. "
                                "Use what's listed in 'Raw files' in docs/content-types.md, or tier mythic, or a server module.")


def _check_enchantment(contents, raw, feature_id, feature, label, world, problems):
    declared = feature["manifest"].get("enchantments", {}).get(raw.name, {})
    _check_enchantment_power(contents, declared.get("tier") if isinstance(declared, dict) else None, label, problems)


# Loot


def _entry_tier(entry, feature_id, world):
    name = entry.get("name")
    found = TOKEN.fullmatch(str(name))
    if found and found.group(1) in ("item", "block"):
        thing = balance._things(world.features).get(f"{found.group(1)}:{balance._key(feature_id, found.group(2))}", {})
        return thing.get("tier", entry.get("tier"))
    return entry.get("tier")


def _check_modifier(modifier, tier, label, feature_id, world, problems):
    """Something done to what comes out of a loot table. Whatever it can set on an item answers to the same curve as a recipe's result."""
    if not isinstance(modifier, dict):
        return
    kind = modifier.get("type")
    if kind not in LOOT_FUNCTIONS:
        problems.append(f"{label} has a modifier of type {kind!r}, which the game doesn't have.")
    if kind == "minecraft:set_components" and isinstance(modifier.get("components"), dict):
        claim, found = balance._from_components(label, modifier["components"])
        problems += [] if tier == balance.UNLIMITED else found
        carried = sorted({str(name).removeprefix("minecraft:") for name in modifier["components"]} & CARRYING_COMPONENTS)
        if carried and tier != balance.UNLIMITED:
            problems.append(f"{label} sets {', '.join(carried)}, and what's inside that could be anything at all, past every check here. Use set_contents with entries, which are checked.")
        if any(stat != "slot" for stat in claim):
            if tier is None:
                problems.append(f"{label} sets {', '.join(sorted(claim))} and doesn't say what tier that is. Add \"tier\" to the entry: one of {', '.join(balance.TIERS)}.")
            else:
                problems += balance._over_budget(label, tier, claim)
    elif kind == "minecraft:set_attributes" and tier != balance.UNLIMITED:
        problems.append(f"{label} uses set_attributes, which isn't measured. Use set_components with minecraft:attribute_modifiers, which is.")
    elif kind == "minecraft:set_item":
        problems.append(f"{label} uses set_item, which makes it into something else after the checks have looked at it. Name that item in the entry instead.")
    elif kind == "minecraft:enchant_with_levels":
        levels = _most_of_provider(modifier.get("levels"))
        if tier != balance.UNLIMITED and not levels <= MOST_ENCHANT_LEVELS:
            problems.append(f"{label} enchants with {levels:g} levels, over the {MOST_ENCHANT_LEVELS} of vanilla's best loot.")
    elif kind == "minecraft:set_enchantments":
        for name, level in (modifier.get("enchantments") or {}).items():
            _check_enchant_level(name, level, tier, label, feature_id, world, problems)
    elif kind == "minecraft:reference":
        if not rawpack.TOKEN.fullmatch(str(modifier.get("name"))):
            problems.append(f"{label} refers to the modifier {modifier.get('name')!r}. Use $item_modifier:name for one in your raw/ folder.")
    if isinstance(modifier.get("entries"), list):
        _check_entries(modifier["entries"], label, feature_id, world, problems)


def _check_enchant_level(name, level, tier, label, feature_id, world, problems):
    """An enchantment level past its own maximum can't be got any other way, so it would be stronger than anything it's measured as."""
    if tier == balance.UNLIMITED:
        return
    found = rawpack.TOKEN.fullmatch(str(name))
    most = _most_of_provider(level)
    if found and found.group(1) == "enchantment":
        top = _max_level_of(found.group(2), feature_id, world)
    elif str(name).startswith("minecraft:") and _strip(name) in VANILLA["enchantment"]:
        top = VANILLA["enchantment"][_strip(name)]
    else:
        problems.append(f"{label} enchants with {name!r}. Use $enchantment:name for your own, or one of vanilla's by its name.")
        return
    if top is not None and not most <= top:
        problems.append(f"{label} gives {name} at level {most:g}, over its highest of {top}.")


def _max_level_of(name, feature_id, world):
    owner, _, own = name.rpartition("/")
    owner = owner or feature_id
    for raw in world.files.get(owner, []):
        if raw.registry == "enchantment" and raw.name == own and raw.is_json:
            try:
                return json.loads(raw.path.read_text(encoding="utf-8")).get("max_level")
            except json.JSONDecodeError:
                return None
    return None


def _check_entries(entries, label, feature_id, world, problems):
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            problems.append(f"{label} has an entry that isn't an object: {entry!r}.")
            continue
        kind = entry.get("type")
        if kind not in LOOT_ENTRIES:
            problems.append(f"{label} has an entry of type {kind!r}, which the game doesn't have.")
        name = entry.get("name")
        if kind == "minecraft:item" and not (TOKEN.fullmatch(str(name)) or _is_vanilla(name, "item")):
            problems.append(f"{label} hands out {name!r}. Use $item:name, $block:name, or one of vanilla's by its full name, like minecraft:apple.")
        if kind == "minecraft:loot_table" and isinstance(entry.get("value"), str) and not (rawpack.TOKEN.fullmatch(entry["value"]) or _is_vanilla(entry["value"], "loot_table")):
            problems.append(f"{label} points at the loot table {entry['value']!r}. Use $loot_table:name for your own, or one of vanilla's by its full name.")
        tier = _entry_tier(entry, feature_id, world)
        for modifier in _listed(entry.get("modifier")):
            _check_modifier(modifier, tier, label, feature_id, world, problems)
        if isinstance(entry.get("children"), list):
            _check_entries(entry["children"], label, feature_id, world, problems)


def _listed(value):
    return value if isinstance(value, list) else [] if value is None else [value]


def _check_pools(pools, label, feature_id, world, problems):
    """Minecraft 26's format, in the file's own words: the older fields load fine and do nothing, which is why this looks for them first."""
    found = sorted(set(_old_fields(pools)))
    if found:
        problems.append(f"{label} uses {', '.join(found)}, which Minecraft 26 ignores. See 'Loot tables' in docs/content-types.md.")
    if not isinstance(pools, list):
        problems.append(f"{label} needs a list of pools.")
        return
    for pool in pools:
        if not isinstance(pool, dict) or "rolls" not in pool or "entries" not in pool:
            problems.append(f"{label} has a pool that needs both rolls and entries: {json.dumps(pool)[:120]}.")
            continue
        _check_entries(pool["entries"], label, feature_id, world, problems)
        for modifier in _listed(pool.get("modifier")):
            _check_modifier(modifier, pool.get("tier"), label, feature_id, world, problems)


def _old_fields(value):
    """The fields Minecraft 26 stopped reading."""
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in OLD_LOOT_FIELDS:
                yield key
            yield from _old_fields(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _old_fields(inner)


def _check_loot_table(contents, raw, feature_id, feature, label, world, problems):
    _check_pools(contents.get("pools", []), label, feature_id, world, problems)


def _check_item_modifier(contents, raw, feature_id, feature, label, world, problems):
    for modifier in _listed(contents):
        _check_modifier(modifier, None, label, feature_id, world, problems)


def _check_loot_additions(feature_id, feature, world, problems):
    for addition in feature["manifest"].get("loot_additions", []):
        table = str(addition.get("table", "")) if isinstance(addition, dict) else ""
        label = f"{feature_id}'s loot added to {table or 'a table'}"
        if not _is_vanilla(table, "loot_table"):
            problems.append(f"{label}: vanilla has no loot table called {table!r}. Name one like minecraft:chests/simple_dungeon.")
        pools = addition.get("pools") if isinstance(addition, dict) else None
        if not pools:
            problems.append(f"{label} has no pools, so it adds nothing.")
            continue
        _check_pools(pools, label, feature_id, world, problems)
        # Blocks and mobs never run out, so anything rare from one of those soon isn't. Chests do, which is why a ruin's or dungeon's can be a rare find.
        if not table.startswith(CHEST_TABLES):
            for precious in sorted(balance._VANILLA_PRECIOUS & {_strip(name) for name in _strings(pools)}):
                problems.append(f"{label} hands out minecraft:{precious}, and nothing that never runs out can, because it would soon be common. Add it to a chest's table, as a rare find.")
        # Anyone could find this from the start, so gear past what the early game allows would get around every step of the progression.
        for found in TOKEN.finditer(json.dumps(pools)):
            thing = balance._things(world.features).get(f"{found.group(1)}:{balance._key(feature_id, found.group(2))}", {})
            tier = thing.get("tier")
            if tier in balance.TIERS and balance.TIERS.index(tier) > balance.TIERS.index(EARLY_TIER):
                problems.append(f"{label} hands out {found.group(0)}, which is tier {tier}. Anyone can find vanilla's loot from the start, so nothing above {EARLY_TIER} can go there. Put it in a ruin of its own.")


# The other things a raw file can be


def _check_advancement(contents, raw, feature_id, feature, label, world, problems):
    criteria = contents.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        problems.append(f"{label} needs criteria, or it could never be earned.")
    else:
        for name, criterion in criteria.items():
            trigger = criterion.get("trigger") if isinstance(criterion, dict) else None
            if not _is_vanilla(trigger, "trigger"):
                problems.append(f"{label} has a criterion {name} with the trigger {trigger!r}, which the game doesn't have.")
        for group in contents.get("requirements", []) if isinstance(contents.get("requirements"), list) else []:
            for name in group if isinstance(group, list) else []:
                if name not in criteria:
                    problems.append(f"{label} requires {name}, which isn't one of its criteria, so it could never be earned.")
    parent = contents.get("parent")
    if parent is not None and not (rawpack.TOKEN.fullmatch(str(parent)) or _is_vanilla(parent, "advancement")):
        problems.append(f"{label} has the parent {parent!r}. Use $advancement:name for your own, or one of vanilla's by its full name.")
    rewards = contents.get("rewards")
    if rewards is not None:
        unknown = sorted(set(rewards) - {"experience", "loot", "function"}) if isinstance(rewards, dict) else ["rewards"]
        if unknown:
            problems.append(f"{label} rewards {', '.join(unknown)}. An advancement can reward experience and $loot_table:name. Recipes are learned through \"knowledge\", so that they can't be got around.")
        if isinstance(rewards, dict):
            experience = rewards.get("experience", 0)
            if not isinstance(experience, (int, float)) or isinstance(experience, bool) or not 0 <= experience <= MOST_ADVANCEMENT_XP:
                problems.append(f"{label} rewards {experience!r} experience. Vanilla's biggest is {MOST_ADVANCEMENT_XP}.")
            for table in rewards.get("loot", []) if isinstance(rewards.get("loot", []), list) else [rewards.get("loot")]:
                found = rawpack.TOKEN.fullmatch(str(table))
                if not found or found.group(1) != "loot_table":
                    problems.append(f"{label} rewards the loot table {table!r}. Use $loot_table:name, for one in your raw/ folder.")
    display = contents.get("display")
    if display is not None:
        if not isinstance(display, dict) or not all(field in display for field in ("icon", "title", "description")):
            problems.append(f"{label} needs an icon, a title and a description in its display, or leave out display for one nobody sees.")
        else:
            icon = display["icon"].get("id") if isinstance(display["icon"], dict) else None
            if not (TOKEN.fullmatch(str(icon)) or _is_vanilla(icon, "item")):
                problems.append(f"{label} has the icon {display['icon']!r}. It's like {{\"id\": \"$item:name\"}}, or one of vanilla's by its full name.")
            if display.get("frame", "task") not in ADVANCEMENT_FRAMES:
                problems.append(f"{label} has the frame {display.get('frame')!r}. Use one of {sorted(ADVANCEMENT_FRAMES)}.")


def _check_sound(sound, label, feature_id, world, problems):
    """Sounds of this world's aren't registered, so one has to be named by what it's called in the pack, or the game won't read the file."""
    if isinstance(sound, dict):
        sound = sound.get("sound_id")
        if not (TOKEN.fullmatch(str(sound)) or _is_vanilla(sound, "sound_event")):
            problems.append(f"{label} has the sound {sound!r}. Use {{\"sound_id\": \"$sound:name\"}}.")
    elif TOKEN.fullmatch(str(sound)):
        problems.append(f"{label} has the sound {sound}. This world's sounds aren't in the game's list, so write it as {{\"sound_id\": \"{sound}\"}}.")
    elif not _is_vanilla(sound, "sound_event"):
        problems.append(f"{label} has the sound {sound!r}, which isn't one of vanilla's. Use {{\"sound_id\": \"$sound:name\"}} for one of this world's.")


def _check_song(contents, raw, feature_id, feature, label, world, problems):
    _check_sound(contents.get("sound_event"), label, feature_id, world, problems)
    seconds = contents.get("length_in_seconds")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
        problems.append(f"{label} has length_in_seconds {seconds!r}. It's how long the song plays for, and a jukebox goes quiet after it.")
    output = contents.get("comparator_output")
    if not isinstance(output, int) or isinstance(output, bool) or not 0 <= output <= 15:
        problems.append(f"{label} has comparator_output {output!r}. It's a whole number from 0 to 15.")


def _check_instrument(contents, raw, feature_id, feature, label, world, problems):
    _check_sound(contents.get("sound_event"), label, feature_id, world, problems)
    for field in ("range", "use_duration"):
        if not isinstance(contents.get(field), (int, float)) or isinstance(contents.get(field), bool) or contents[field] <= 0:
            problems.append(f"{label} has {field} {contents.get(field)!r}. It has to be a number above 0.")


def _check_texture_id(contents, field, folder, feature_id, label, world, problems):
    """The game works out a picture's whole path from this, so the file has to be in just the right place, or it comes out purple and black."""
    found = rawpack.TOKEN.fullmatch(str(contents.get(field)))
    if not found or found.group(1) != rawpack.TEXTURE_TOKEN:
        if not str(contents.get(field)).startswith("minecraft:"):
            problems.append(f"{label} has the {field} {contents.get(field)!r}. Use $texture:name, for raw/assets/gm/{folder}/name.png.")
    elif not world.texture_in(feature_id, found.group(2), folder):
        problems.append(f"{label} uses {found.group(0)}, so it needs raw/assets/gm/{folder}/{found.group(2)}.png.")


def _check_painting(contents, raw, feature_id, feature, label, world, problems):
    _check_texture_id(contents, "asset_id", "textures/painting", feature_id, label, world, problems)
    for field in ("width", "height"):
        if not isinstance(contents.get(field), int) or isinstance(contents.get(field), bool) or not 1 <= contents[field] <= 16:
            problems.append(f"{label} has {field} {contents.get(field)!r}. It's a whole number of blocks, from 1 to 16.")


def _check_banner(contents, raw, feature_id, feature, label, world, problems):
    for folder in ("textures/entity/banner", "textures/entity/shield"):
        _check_texture_id(contents, "asset_id", folder, feature_id, label, world, problems)


def _check_damage_type(contents, raw, feature_id, feature, label, world, problems):
    if contents.get("scaling") not in DAMAGE_SCALING:
        problems.append(f"{label} has scaling {contents.get('scaling')!r}. Use one of {sorted(DAMAGE_SCALING)}.")


def _check_equipment(contents, raw, feature_id, feature, label, world, problems):
    """Worn armour is looked up as textures/entity/equipment/<layer>/<name>.png, so a layer with no picture there shows as nothing, with no complaint."""
    layers = contents.get("layers")
    if not isinstance(layers, dict) or not layers:
        problems.append(f"{label} needs layers, like {{\"humanoid\": [{{\"texture\": \"$texture:{raw.name}\"}}]}}.")
        return
    for layer, parts in layers.items():
        if layer not in rawpack.ARMOUR_LAYERS:
            problems.append(f"{label} has the layer {layer}. Use one of {sorted(rawpack.ARMOUR_LAYERS)}.")
            continue
        for part in parts if isinstance(parts, list) else []:
            texture = part.get("texture") if isinstance(part, dict) else None
            found = rawpack.TOKEN.fullmatch(str(texture))
            if found and found.group(1) == rawpack.TEXTURE_TOKEN:
                if not world.texture_in(feature_id, found.group(2), f"textures/{rawpack.EQUIPMENT_TEXTURES}/{layer}"):
                    problems.append(f"{label} uses {texture} for its {layer} layer, so it needs raw/assets/gm/textures/{rawpack.EQUIPMENT_TEXTURES}/{layer}/{found.group(2)}.png.")
            elif not str(texture).startswith("minecraft:"):
                problems.append(f"{label} has the texture {texture!r} in its {layer} layer. Use $texture:name, or one of vanilla's by its full name.")


def _block_family(token, feature_id, features):
    found = TOKEN.fullmatch(token)
    if not found or found.group(1) != "block":
        return None
    key = balance._key(feature_id, found.group(2))
    owner, _, name = key.partition("/")
    return features.get(owner, {"manifest": {}})["manifest"].get("blocks", {}).get(name, {}).get("family")


def _check_tag(contents, raw, feature_id, feature, label, world, problems):
    registry = raw.registry
    if registry not in TAG_REGISTRIES:
        problems.append(f"{label}: tags in {registry} can't be added to. A feature can add to {', '.join(sorted(TAG_REGISTRIES))}.")
        return
    if contents.get("replace"):
        problems.append(f"{label} has replace true, which would take away what's in it already, from vanilla or another feature. Leave it out, and it adds to them.")
    values = contents.get("values")
    if not isinstance(values, list) or not values:
        problems.append(f"{label} needs a list of values.")
        return
    wanted = TAG_NAMES.get(registry)
    vanilla_tags = VANILLA["tags"].get(registry.removeprefix("tags/"), [])
    if raw.is_vanilla_tag:
        unfair = UNFAIR_TAGS.get(registry)
        if unfair and unfair.fullmatch(raw.name):
            problems.append(f"{label}: {raw.name} is part of what something in vanilla costs, so one more thing in it gets around that. "
                            "Give your material a recipe, or make the gear yourself.")
        if raw.name not in vanilla_tags:
            problems.append(f"{label}: vanilla has no {registry.removeprefix('tags/')} tag called {raw.name}, so nothing would ever read this. Look it up, or put your own under data/gm/{registry}/.")
    for entry in values:
        value = entry.get("id") if isinstance(entry, dict) else entry
        text = str(value)
        if text.startswith("#"):
            found = rawpack.TOKEN.fullmatch(text[1:])
            if found and found.group(1) == rawpack.TAG_TOKEN:
                continue
            if not (text.startswith("#minecraft:") and _strip(text[1:]) in vanilla_tags):
                problems.append(f"{label} has {text}. Use #$tag:name for your own, or one of vanilla's that's in {registry.removeprefix('tags/')}.")
            continue
        own = TOKEN.fullmatch(text) or rawpack.TOKEN.fullmatch(text)
        if own:
            if own.group(1) not in TAG_REGISTRIES[registry]:
                problems.append(f"{label} has {text}, which isn't the right kind of thing for {registry}.")
        elif wanted is None or not _is_vanilla(text, wanted):
            problems.append(f"{label} has {text!r}. Use a token like $item:name, or one of vanilla's by its full name.")
        if raw.is_vanilla_tag and raw.registry == "tags/block" and raw.name == CLIMBABLE and own and _block_family(text, feature_id, world.features) != LADDER:
            problems.append(f"{label} has {text}, which isn't in the ladder family. A player's game works out climbing for itself from what it takes the block to be, so anything else "
                            "looks climbable to the server and not to them, and they just fall. Make it a ladder block, which needs no tag at all.")


CHECKS = {"advancement": _check_advancement, "enchantment": _check_enchantment, "loot_table": _check_loot_table, "item_modifier": _check_item_modifier,
          "jukebox_song": _check_song, "instrument": _check_instrument, "painting_variant": _check_painting, "banner_pattern": _check_banner, "damage_type": _check_damage_type,
          "equipment": _check_equipment}


def _check_file(raw, feature_id, feature, world, problems):
    label = f"raw/{raw.relative} in {feature_id}"
    if not raw.is_json:
        return
    try:
        contents = json.loads(raw.path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        problems.append(f"{label} isn't valid JSON: {error}")
        return
    _scan(contents, label, problems)
    _check_references(contents, label, feature_id, world, problems)
    if raw.registry.startswith("tags/"):
        if isinstance(contents, dict):
            _check_tag(contents, raw, feature_id, feature, label, world, problems)
        else:
            problems.append(f"{label} needs an object with a list of values.")
        return
    if raw.registry == "item_modifier":
        _check_item_modifier(contents, raw, feature_id, feature, label, world, problems)
        return
    if not isinstance(contents, dict):
        problems.append(f"{label} needs to be an object.")
        return
    _check_shape(contents, raw.registry, label, problems)
    check = CHECKS.get(raw.registry)
    if check:
        check(contents, raw, feature_id, feature, label, world, problems)


def _check_kept(world, old_ledger, problems):
    """Items and worlds hold on to these by name, and with one gone the game drops what refers to it. So once out, it stays."""
    have = {f"{raw.registry}/{feature_id}/{raw.name}" for feature_id, files in world.files.items() for raw in files}
    for key in old_ledger.get("raw", []):
        if key not in have:
            registry, _, name = key.rpartition("/")
            problems.append(f"{key} has been released, so players' things and the world may hold on to it, and the game throws away whatever refers to something that's gone. Put it back, however plain, and stop using it.")


def _check_size(world, problems):
    for feature_id, files in world.files.items():
        total = sum(raw.path.stat().st_size for raw in files if not raw.path.is_symlink())
        if total > MOST_RAW_BYTES:
            problems.append(f"{feature_id}'s raw/ folder is {total // (1024 * 1024)} MB, and every player downloads the art in it. It can be at most {MOST_RAW_BYTES // (1024 * 1024)} MB.")


def _biome_problem(value, label, feature_id, world, tags_allowed):
    text = str(value)
    found = rawpack.TOKEN.fullmatch(text)
    if found and found.group(1) == "biome":
        return None if world.has("biome", feature_id, found.group(2)) else f"{label} is in {text}, which no feature declares."
    if text.startswith("#"):
        if not tags_allowed:
            return f"{label} is in {text}. Only a mob's spawn can use tags. List the biomes instead."
        return None if _strip(text[1:]) in VANILLA["tags"].get("worldgen/biome", []) else f"{label} is in {text}, which vanilla doesn't have."
    if _is_vanilla(text, "biome"):
        return None
    return f"{label} is in {text!r}, which isn't a biome. Use one of vanilla's by its full name, like minecraft:plains, or $biome:name for one of this world's."


def check_biomes(features, world=None, old_ledger=None):
    """A wrong name in one of these either stops the whole file loading or means something never appears, and neither says why at the time.
    What's already out is left alone, so an old mistake that does nothing can't hold up every release from now on."""
    world = world or _World(features)
    old_ledger = old_ledger or {}
    released = set(old_ledger.get("patches", []))
    problems = []
    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        for table in ("ores", "plants", "ruins"):
            entries = manifest.get(table, [])
            for entry in entries.values() if isinstance(entries, dict) else entries:
                if entry.get("id") in released:
                    continue
                for value in entry.get("biomes") or []:
                    problem = _biome_problem(value, f"{feature_id}'s {table[:-1]} {entry.get('id', '')}".rstrip(), feature_id, world, False)
                    if problem:
                        problems.append(problem)
        for name, mob in manifest.get("mobs", {}).items():
            if f"{feature_id}/{name}" in old_ledger.get("mobs", {}):
                continue
            for value in (mob.get("spawn") or {}).get("biomes") or []:
                problem = _biome_problem(value, f"Mob {feature_id}/{name}", feature_id, world, True)
                if problem:
                    problems.append(problem)
        for name, biome in manifest.get("biomes", {}).items():
            if f"biome_{rawpack.biome_id(feature_id, name)}" not in released and biome.get("base") is not None and not _is_vanilla(biome["base"], "biome"):
                problems.append(f"Biome {feature_id}/{name} starts from {biome['base']!r}, which isn't one of vanilla's. Use its full name, like minecraft:plains.")
    return problems


def run(features, old_ledger=None):
    """Reports everything at once, so fixing a batch takes one try and not ten."""
    world = _World(features)
    problems = list(world.problems)
    try:
        for feature_id, feature in features.items():
            for raw in world.files[feature_id]:
                _check_file(raw, feature_id, feature, world, problems)
            _check_loot_additions(feature_id, feature, world, problems)
            _check_references(feature["manifest"], f"{feature_id}/feature.json", feature_id, world, problems)
            for name in feature["manifest"].get("enchantments", {}):
                if not world.has("enchantment", feature_id, name):
                    problems.append(f"{feature_id}/feature.json says something about the enchantment {name}, and there's no raw/data/gm/enchantment/{name}.json.")
        problems += check_biomes(features, world, old_ledger)
        _check_kept(world, old_ledger or {}, problems)
        _check_size(world, problems)
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        # What couldn't be read hasn't been checked, so it can't pass. A crash here would also leave no answer at all.
        raise GateFailed(GATE, f"A raw file or loot_additions has something in the wrong shape, so it can't be checked: {error!r}. Compare it with 'Raw files' in docs/content-types.md.") from error
    if problems:
        raise GateFailed(GATE, "\n".join(dict.fromkeys(problems)))

