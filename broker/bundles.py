"""Compiles feature bundles into what the server loads.

A bundle is written with readable names like "ember_ore". This turns them into meaningless slot IDs,
so nothing in the resource pack or data pack spoils what a block is. The ledger records every
assignment and only ever grows, which is what makes rollback safe: an ID never changes meaning.
"""
import hashlib
import json
import pathlib
import re
import shutil

from broker import guide, rawpack
from orchestrator import others
from orchestrator import wording

TOKEN = re.compile(r"\$(block|item|mob|sound|biome|dimension):([a-z0-9_]+(?:/[a-z0-9_]+)?)")

TOOL_TAGS = {"pickaxe": "pickaxe", "axe": "axe", "shovel": "shovel", "hoe": "hoe"}
LEVEL_TAGS = {"stone": "needs_stone_tool", "iron": "needs_iron_tool", "diamond": "needs_diamond_tool"}
ORE_FAMILIES = {"ore", "deep_ore", "glow_ore"}
# Not cubes, so like vanilla's flowers, what these look like in an inventory is a flat picture of the texture. A sculpted block's texture is a picture of it for just that.
FLAT_ICON_FAMILIES = {"model", "plant", "glow_plant", "tinted_plant", "crop", "ladder"}
# What vanilla's grasses are coloured by when they're held, away from any biome.
HELD_PLANT_TINT = {"type": "minecraft:grass", "temperature": 0.5, "downfall": 1.0}
# How a block sits in an inventory or a hand. A model with no parent has none of this, so it's drawn flat on and too big.
BLOCK_DISPLAY = "minecraft:block/block"
CROP_STAGES = 4
# In the order the game numbers directions, which is how a connected block's 64 shapes are numbered.
CONNECTED_ARMS = (((6, 0, 6), (10, 6, 10)), ((6, 10, 6), (10, 16, 10)), ((6, 6, 0), (10, 10, 6)),
                  ((6, 6, 10), (10, 10, 16)), ((0, 6, 6), (6, 10, 10)), ((10, 6, 6), (16, 10, 10)))
CUBE_FACES = ("down", "up", "north", "south", "west", "east")
LIGHT_EMISSION_FULL = 15
USE_SOUND = "minecraft:intentionally_empty"
DEFAULT_LIST_ROWS = 9
CHEST_ROW = 9
PANEL_IMAGE_FIELDS = ("image", "hover_image", "disabled_image", "portrait")
# The padding of a tab and the gap after it.
TAB_GAP = 11
LOOKS_ONLY_ATTRIBUTES = ("minecraft:visual/", "minecraft:audio/")
BLOCK_FACES = {"top", "bottom", "front", "back", "left", "right", "side"}
# Everything a dimension type can say. The game ignores a field it doesn't know without saying so, so this has to catch those.
DIMENSION_TYPE_FIELDS = {"ambient_light", "attributes", "cardinal_light", "coordinate_scale", "default_clock", "has_ceiling", "has_ender_dragon_fight", "has_fixed_time",
                         "has_skylight", "height", "infiniburn", "logical_height", "min_y", "monster_spawn_block_light_limit", "monster_spawn_light_level", "skybox", "timelines"}
DEFAULT_DIMENSION_TYPE = "minecraft:overworld"


class BundleError(Exception):
    """A problem with a bundle, worded so the agent can fix it."""


class LanguageFiles:
    """The pack's language files as they're written, with a translation going in beside each piece of English. A key a language
    doesn't have falls back to English in the game itself, so a translation that's missing or no different is just left out."""

    def __init__(self, languages):
        self.english = {}
        self.languages = languages
        self.others = {language: {} for language in languages}

    def name(self, key, english):
        self._put(key, english, lambda words: words.name(english))

    def text(self, key, english):
        self._put(key, english, lambda words: words.text(english))

    def literal(self, key, english):
        """The same, for what goes through the game's formatting without being written for it, where a percent sign means something."""
        self._put(key, _literal(english), lambda words: _literal(words.text(english)))

    def _put(self, key, english, translate):
        self.english[key] = english
        for language, words in self.languages.items():
            translated = translate(words)
            if translated != english:
                self.others[language][key] = translated

    def write(self, pack):
        _write_json(pack / f"assets/gm/lang/{wording.ENGLISH}.json", self.english)
        for language, translated in self.others.items():
            words = {**translated, **wording.engine_words(language, "game")}
            for variant in wording.SAME_WORDS.get(language, (language,)):
                _write_json(pack / f"assets/gm/lang/{variant}.json", words)


def read_pool(repo):
    """Reads the slot pool from the mod's own source, so this can't drift from what's registered."""
    source = (repo / "mods/conduit/src/main/java/gm/conduit/slots/SlotFamily.java").read_text(encoding="utf-8")
    families = {}
    for name, first, count in re.findall(r"^\s+([A-Z_]+)\((\d+), (\d+), (?:BlockModelType|null)", source, re.MULTILINE):
        families[name.lower()] = {"first": int(first), "count": int(count)}
    if not families:
        raise BundleError("Couldn't read any slot families from SlotFamily.java")
    slots = (repo / "mods/conduit/src/main/java/gm/conduit/slots/NeutralSlots.java").read_text(encoding="utf-8")
    item_count = int(re.search(r"ITEM_COUNT = (\d+)", slots).group(1))
    mobs = (repo / "mods/conduit/src/main/java/gm/conduit/mobs/SlotMobs.java").read_text(encoding="utf-8")
    return {"families": families, "item_count": item_count, "mobs": {
        "monster": int(re.search(r"MONSTER_COUNT = (\d+)", mobs).group(1)),
        "creature": int(re.search(r"CREATURE_COUNT = (\d+)", mobs).group(1)),
    }}


def load_features(features_dir):
    features = {}
    if not features_dir.is_dir():
        return features
    for folder in sorted(path for path in features_dir.iterdir() if path.is_dir()):
        # A link can point anywhere on whichever machine reads it, including at what a build leaves behind for the gates to read.
        link = next((path for path in (folder, *folder.rglob("*")) if path.is_symlink()), None)
        if link:
            raise BundleError(f"{folder.name}: {link.relative_to(features_dir)} is a link, and a feature can only hold real files")
        manifest = folder / "feature.json"
        if not manifest.exists():
            raise BundleError(f"{folder.name}: feature.json is missing")
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise BundleError(f"{folder.name}: feature.json isn't valid JSON: {error}") from error
        if data.get("id") != folder.name:
            raise BundleError(f"{folder.name}: id must match the folder name, found {data.get('id')!r}")
        features[folder.name] = {"manifest": data, "dir": folder}
    # Here, so that what one feature adds to another is part of that feature for every gate and for the release.
    problems = others.apply_additions({feature_id: feature["manifest"] for feature_id, feature in features.items()})
    if problems:
        raise BundleError("\n".join(problems))
    return features


def empty_ledger():
    return {"blocks": {}, "items": {}, "mobs": {}, "dimensions": {}, "patches": [], "raw": []}


def assign_slots(features, ledger, pool):
    """Gives every new name the next free slot in its family. Existing assignments never change."""
    used = {family: 0 for family in pool["families"]}
    for entry in ledger["blocks"].values():
        used[entry["family"]] = max(used.get(entry["family"], 0), entry["index"] + 1)
    next_item = max((entry["index"] + 1 for entry in ledger["items"].values()), default=0)

    for feature_id, feature in features.items():
        for name, block in feature["manifest"].get("blocks", {}).items():
            key = f"{feature_id}/{name}"
            family = block.get("family")
            if family not in pool["families"]:
                raise BundleError(f"{key}: unknown family {family!r}, expected one of {sorted(pool['families'])}")
            existing = ledger["blocks"].get(key)
            if existing:
                if existing["family"] != family:
                    raise BundleError(f"{key}: can't move from family {existing['family']} to {family}, "
                                      "because placed blocks keep their slot. Add a new block instead.")
                continue
            index = used[family]
            if index >= pool["families"][family]["count"]:
                raise BundleError(f"{key}: family {family} has no free slots left")
            slot = "s%04d" % (pool["families"][family]["first"] + index)
            ledger["blocks"][key] = {"slot": slot, "family": family, "index": index}
            used[family] = index + 1
        for name in feature["manifest"].get("items", {}):
            key = f"{feature_id}/{name}"
            if key in ledger["items"]:
                continue
            if next_item >= pool["item_count"]:
                raise BundleError(f"{key}: no free item slots left")
            ledger["items"][key] = {"slot": "i%04d" % (next_item + 1), "index": next_item}
            next_item += 1
        for name, mob in feature["manifest"].get("mobs", {}).items():
            _assign_mob(ledger, pool, f"{feature_id}/{name}", mob.get("category"))
        for name, dimension in feature["manifest"].get("dimensions", {}).items():
            _assign_dimension(ledger, f"{feature_id}/{name}", dimension)
    return ledger


def _assign_mob(ledger, pool, key, category):
    """Monsters and creatures are separate ranges, because that's fixed when an entity type is registered."""
    if category not in pool["mobs"]:
        raise BundleError(f"{key}: category must be one of {sorted(pool['mobs'])}, found {category!r}")
    table = ledger.setdefault("mobs", {})
    existing = table.get(key)
    if existing:
        if existing["category"] != category:
            raise BundleError(f"{key}: can't change category from {existing['category']} to {category}, because "
                              "mobs in the world keep their slot. Add a new mob instead.")
        return
    index = sum(1 for entry in table.values() if entry["category"] == category)
    if index >= pool["mobs"][category]:
        raise BundleError(f"{key}: no free {category} slots left")
    offset = pool["mobs"]["monster"] if category == "creature" else 0
    table[key] = {"slot": "e%04d" % (offset + index + 1), "category": category, "index": index}


def _assign_dimension(ledger, key, dimension):
    """Remembers what its land is made from as well, because land already made wouldn't match land made from anything else."""
    table = ledger.setdefault("dimensions", {})
    terrain = hashlib.sha256(json.dumps([dimension.get("type"), dimension.get("generator")], sort_keys=True).encode()).hexdigest()[:16]
    existing = table.get(key)
    if existing:
        if existing["terrain"] != terrain:
            raise BundleError(f"{key}: a dimension's type and generator can't change once it's out, because land that's already been made "
                              "wouldn't match what's made next to it. Add a new dimension instead.")
        return
    table[key] = {"slot": "d%04d" % (len(table) + 1), "terrain": terrain}


def _sound_id(feature_id, name):
    return hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:16]


_biome_id = rawpack.biome_id


def _resolver(feature_id, ledger):
    def resolve(match):
        kind, name = match.group(1), match.group(2)
        key = name if "/" in name else f"{feature_id}/{name}"
        if kind == "sound":
            return f"gm:{_sound_id(*key.split('/'))}"
        if kind == "biome":
            return f"gm:{_biome_id(*key.split('/'))}"
        table = {"block": ledger["blocks"], "item": ledger["items"], "mob": ledger.get("mobs", {}), "dimension": ledger.get("dimensions", {})}[kind]
        if key not in table:
            raise BundleError(f"{feature_id}: refers to unknown {kind} {key!r}")
        return f"gm:{table[key]['slot']}"
    return resolve


def _resolve_tokens(value, feature_id, ledger):
    """Keys too, because what gear is enchanted with is written as a key."""
    if isinstance(value, str):
        found = TOKEN.sub(_resolver(feature_id, ledger), value)
        return rawpack.TOKEN.sub(lambda match: rawpack.resolve(match, feature_id), found)
    if isinstance(value, list):
        return [_resolve_tokens(item, feature_id, ledger) for item in value]
    if isinstance(value, dict):
        return {_resolve_tokens(key, feature_id, ledger): _resolve_tokens(item, feature_id, ledger) for key, item in value.items()}
    return value


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _wearable(components):
    """The game only wears something out if it has a damage value as well as a maximum, and it refuses anything that
    both wears out and stacks. Vanilla's tools have both set for them, so a builder shouldn't have to know."""
    if isinstance(components, dict) and "minecraft:max_damage" in components:
        return {"minecraft:damage": 0, "minecraft:max_stack_size": 1, **components}
    return components


def _item_definition(feature, item, slot, parent, pack):
    """How a client picks what to draw for an item, for those that aren't always the same picture. It's None for most, which the mod's own plain one covers."""
    def picture(texture, suffix):
        _copy_texture(feature, "item", f"{slot}_{suffix}", texture, pack)
        _write_json(pack / f"assets/gm/models/item/{slot}_{suffix}.json", {"parent": parent, "textures": {"layer0": f"gm:item/{slot}_{suffix}"}})
        return {"type": "minecraft:model", "model": f"gm:item/{slot}_{suffix}"}

    if not item.get("compass") and not item.get("variants"):
        return None
    model = {"type": "minecraft:model", "model": f"gm:item/{slot}"}
    if item.get("compass"):
        frames = item["compass"]
        model = {"type": "minecraft:range_dispatch", "property": "minecraft:compass", "target": "lodestone", "scale": len(frames),
                 "entries": [{"threshold": index, "model": picture(texture, f"c{index}")} for index, texture in enumerate(frames)]}
    if item.get("variants"):
        model = {"type": "minecraft:select", "property": "minecraft:custom_model_data", "fallback": model,
                 "cases": [{"when": name, "model": picture(texture, f"v{index}")} for index, (name, texture) in enumerate(item["variants"].items())]}
    return model


def _copy_texture(feature, kind, slot, texture, pack):
    source = feature["dir"] / "assets" / "textures" / f"{texture}.png"
    if not source.exists():
        raise BundleError(f"{feature['manifest']['id']}: texture {texture}.png is missing")
    target = pack / "assets/gm/textures" / kind / f"{slot}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    meta = source.with_suffix(".png.mcmeta")
    if meta.exists():
        shutil.copyfile(meta, target.with_suffix(".png.mcmeta"))


def _flat_icon(feature, block, name, slot, pack):
    """Draws a block in an inventory, in hand and on the ground the way an item is, instead of using its block model."""
    _copy_texture(feature, "item", slot, block.get("texture", name), pack)
    _write_json(pack / f"assets/gm/models/item/{slot}.json", {"parent": "minecraft:item/generated", "textures": {"layer0": f"gm:item/{slot}"}})
    model = {"type": "minecraft:model", "model": f"gm:item/{slot}"}
    if block["family"] == "tinted_plant":
        model["tints"] = [HELD_PLANT_TINT]
    _write_json(pack / f"assets/gm/items/{slot}.json", {"model": model})


def _lit_cube(textures):
    """A cube that draws at full brightness whatever light it's in. Only a model's own elements can say so, not one that inherits them."""
    return {"parent": BLOCK_DISPLAY, "textures": {"particle": textures["particle"], **{side: textures[side] for side in CUBE_FACES}},
            "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "light_emission": LIGHT_EMISSION_FULL,
                          "faces": {side: {"texture": f"#{side}", "cullface": side} for side in CUBE_FACES}}]}


def _connected_model(slot, shape):
    """A small cube in the middle, and an arm for each direction this shape reaches out in."""
    boxes = [((6, 6, 6), (10, 10, 10))] + [arm for bit, arm in enumerate(CONNECTED_ARMS) if shape >> bit & 1]
    return {"textures": {"particle": f"gm:block/{slot}", "all": f"gm:block/{slot}"},
            "elements": [{"from": list(low), "to": list(high), "faces": {side: {"texture": "#all"} for side in CUBE_FACES}} for low, high in boxes]}


def _block_model(feature, feature_id, name, block, slot, ledger):
    custom = feature["dir"] / "assets" / "models" / f"{name}.json"
    if custom.exists():
        model = json.loads(custom.read_text(encoding="utf-8"))
        return _resolve_tokens({"parent": BLOCK_DISPLAY, **model}, feature_id, ledger)
    if block.get("emissive"):
        def side(*names):
            found = next((name for name in names if name in block.get("faces", {})), None)
            return f"gm:block/{slot}_{found}" if found else f"gm:block/{slot}"
        return _lit_cube({"particle": side("side", "front"), "up": side("top", "side"), "down": side("bottom", "top", "side"),
                          "north": side("front", "side"), "south": side("back", "side"), "east": side("right", "side"), "west": side("left", "side")})
    if block.get("faces"):
        def face(*names):
            found = next((name for name in names if name in block["faces"]), None)
            return f"gm:block/{slot}_{found}" if found else f"gm:block/{slot}"
        return {"parent": "minecraft:block/cube", "textures": {
            "particle": face("side", "front"), "up": face("top", "side"), "down": face("bottom", "top", "side"),
            "north": face("front", "side"), "south": face("back", "side"), "east": face("right", "side"), "west": face("left", "side")}}
    if block["family"] == "ladder":
        return {"parent": "minecraft:block/ladder", "textures": {"particle": f"gm:block/{slot}", "texture": f"gm:block/{slot}"}}
    # Only tinted_cross takes the biome's colour. On plain cross a tinted plant would stay the grey it's drawn in.
    parents = {"plant": "minecraft:block/cross", "glow_plant": "minecraft:block/cross", "tinted_plant": "minecraft:block/tinted_cross", "crop": "minecraft:block/cross"}
    parent = parents.get(block["family"], "minecraft:block/cube_all")
    key = "cross" if "cross" in parent else "all"
    return {"parent": parent, "textures": {key: f"gm:block/{slot}"}}


def _drop_entry(drops, feature_id, ledger, *bonuses):
    """One thing dropped, in Minecraft 26's loot format. The game ignores fields it doesn't know without saying so,
    so the older "functions" and "conditions" look fine and do nothing. A vanilla item goes by its own name."""
    modifiers = []
    count = drops.get("count")
    if isinstance(count, list):
        modifiers.append({"type": "minecraft:set_count", "count": {"type": "minecraft:uniform", "min": count[0], "max": count[1]}})
    modifiers.extend(bonuses)
    item = drops["item"]
    entry = {"type": "minecraft:item", "name": item if item.startswith("minecraft:") else _resolve_tokens(f"$item:{item}", feature_id, ledger)}
    if modifiers:
        entry["modifier"] = modifiers
    return entry


def _loot_table(block, name, slot, feature_id, ledger):
    """Like vanilla's: a block with its own drops gives itself to silk touch, and an ore's drops respect fortune. A pool only ever
    gives one of what's in it, so of several drops, each after the first has a pool of its own, which silk touch has to turn off."""
    itself = {"type": "minecraft:item", "name": f"gm:{slot}"}
    drops = block.get("drops")
    if drops == "nothing":
        return {"type": "minecraft:block", "pools": []}
    if block.get("family") == "crop":
        return _crop_loot_table(block, slot, feature_id, ledger)
    if drops:
        listed = drops if isinstance(drops, list) else [drops]
        if not all(isinstance(drop, dict) and isinstance(drop.get("item"), str) for drop in listed):
            raise BundleError(f"{feature_id}/{name}: drops is like {{\"item\": \"name\", \"count\": [1, 2]}}, or a list of those, not {drops!r}.")
        bonuses = [{"type": "minecraft:explosion_decay"}]
        if block.get("family") in ORE_FAMILIES:
            bonuses.insert(0, {"type": "minecraft:apply_bonus", "enchantment": "minecraft:fortune", "formula": "minecraft:ore_drops"})
        entries = [_drop_entry(drop, feature_id, ledger, *bonuses) for drop in listed]
        pools = [{"rolls": 1, "entries": [{"type": "minecraft:alternatives", "children": [
            {**itself, "condition": "minecraft:tool/can_silk_touch"},
            entries[0],
        ]}]}]
        no_silk = {"type": "minecraft:inverted", "term": {"type": "minecraft:any_of", "terms": ["minecraft:tool/can_silk_touch"]}}
        pools += [{"rolls": 1, "condition": no_silk, "entries": [entry]} for entry in entries[1:]]
    else:
        pools = [{"rolls": 1, "entries": [{**itself, "condition": {"type": "minecraft:survives_explosion"}}]}]
    return {"type": "minecraft:block", "pools": pools}


def _crop_loot_table(block, slot, feature_id, ledger):
    """What a crop gives depends on whether it's ripe, and silk touch makes no difference, as with vanilla's. Each thing has a pool of its own, because a pool only gives one."""
    ripe = {"type": "minecraft:match_block", "blocks": f"gm:{slot}", "state": {"age": str(CROP_STAGES - 1)}}
    young = {"type": "minecraft:inverted", "term": ripe}
    def listed(field):
        drops = block.get(field) or []
        return drops if isinstance(drops, list) else [drops]
    bonuses = [{"type": "minecraft:explosion_decay"}]
    return {"type": "minecraft:block", "pools": [
        *({"rolls": 1, "condition": ripe, "entries": [_drop_entry(drop, feature_id, ledger, *bonuses)]} for drop in listed("drops")),
        *({"rolls": 1, "condition": young, "entries": [_drop_entry(drop, feature_id, ledger, *bonuses)]} for drop in listed("young_drops")),
    ]}


def _copy_model(feature, feature_id, name, model_name, config):
    """Named by hash, so that nothing in the pack gives away what it's a model of."""
    source = feature["dir"] / "assets" / "models" / f"{model_name}.bbmodel"
    if not source.exists():
        raise BundleError(f"{feature_id}/{name}: model {source.name} is missing")
    raw = source.read_bytes()
    model = "m" + hashlib.sha256(raw).hexdigest()[:16]
    (config / "models").mkdir(parents=True, exist_ok=True)
    (config / "models" / f"{model}.bbmodel").write_bytes(raw)
    return model


def _render_mob(feature, feature_id, name, mob, ledger, pack_lang, datapack, config):
    slot = ledger["mobs"][f"{feature_id}/{name}"]["slot"]
    model = _copy_model(feature, feature_id, name, mob.get("model", name), config)
    pack_lang.name(f"entity.gm.{slot}", mob["display"])
    if mob.get("drops"):
        if not isinstance(mob["drops"], dict) or ":" in str(mob["drops"].get("item")):
            raise BundleError(f"{feature_id}/{name}: a mob drops one of this world's items, like {{\"item\": \"fang\", \"count\": [1, 2]}}, not {mob['drops']!r}.")
        _write_json(datapack / f"data/gm/loot_table/entities/{slot}.json", {
            "type": "minecraft:entity",
            "pools": [{"rolls": 1, "entries": [_drop_entry(mob["drops"], feature_id, ledger, {
                "type": "minecraft:enchanted_count_increase", "enchantment": "minecraft:looting",
                "count": {"type": "minecraft:uniform", "min": 0.0, "max": 1.0},
            })]}],
        })
    fields = ("behaviour", "health", "damage", "speed", "width", "height", "followRange", "armor", "spawn", "display")
    definition = {"model": model, **{field: mob[field] for field in fields if field in mob}}
    if "spawn" in definition:
        definition["spawn"] = _resolve_tokens(definition["spawn"], feature_id, ledger)
    if mob.get("mind"):
        definition["mind"] = _render_mind(mob["mind"], feature_id, ledger)
    if mob.get("sounds"):
        definition["sounds"] = _resolve_tokens(mob["sounds"], feature_id, ledger)
    return slot, definition


def _render_mind(mind, feature_id, ledger):
    """Slot ids for the game's checks, and readable names too, because the model choosing has to know what it's choosing."""
    rendered = _resolve_tokens(mind, feature_id, ledger)
    for original, item in zip(mind.get("stash", []), rendered.get("stash", [])):
        item["name"] = original["item"].rsplit("/", 1)[-1].rsplit(":", 1)[-1].replace("_", " ")
    rendered["teaches"] = {name if "/" in name else f"{feature_id}/{name}": trust for name, trust in mind.get("teaches", {}).items()}
    return rendered


def _render_biome(feature_id, name, biome, vanilla_biome, datapack):
    """Starts from a vanilla biome, so builders only state what's different. Changing only how it looks makes a
    sibling, which is safe to spread into land people have already seen."""
    base = biome.get("base")
    if not base or vanilla_biome is None:
        raise BundleError(f"{feature_id}/{name}: a biome needs a 'base' vanilla biome to start from")
    try:
        merged = json.loads(json.dumps(vanilla_biome(base)))
    except ValueError as error:
        raise BundleError(f"{feature_id}/{name}: {error}. Use one of vanilla's, like minecraft:plains.") from error
    merged.setdefault("effects", {}).update(biome.get("effects", {}))
    climate_changed = False
    for field in ("temperature", "downfall", "has_precipitation", "features", "carvers"):
        if field in biome and biome[field] != merged.get(field):
            merged[field] = biome[field]
            climate_changed = True
    # Sky colour and music are attributes too, and those change nothing anyone has built. Mob spawns are gameplay.
    for key, value in biome.get("attributes", {}).items():
        if merged.setdefault("attributes", {}).get(key) != value:
            merged["attributes"][key] = value
            climate_changed = climate_changed or not key.startswith(LOOKS_ONLY_ATTRIBUTES)
    hashed = _biome_id(feature_id, name)
    _write_json(datapack / f"data/gm/worldgen/biome/{hashed}.json", merged)
    return {"id": f"biome_{hashed}", "from": base, "to": f"gm:{hashed}", "proportion": biome.get("proportion", 0.2), "sibling": not climate_changed}


def _render_dimension(feature_id, name, dimension, ledger, vanilla_type, datapack):
    """A dimension as the server opens it. Its own type starts from a vanilla one, so builders only state what's different, and it
    goes in the data pack, as that's the one part of a dimension the game has to know about when it starts."""
    slot = ledger["dimensions"][f"{feature_id}/{name}"]["slot"]
    kind = dimension.get("type", DEFAULT_DIMENSION_TYPE)
    if isinstance(kind, dict):
        changes = {key: value for key, value in kind.items() if key != "base"}
        unknown = set(changes) - DIMENSION_TYPE_FIELDS
        if unknown:
            raise BundleError(f"{feature_id}/{name}: a dimension's type has nothing called {', '.join(sorted(unknown))}. It can set {', '.join(sorted(DIMENSION_TYPE_FIELDS))}.")
        merged = json.loads(json.dumps(vanilla_type(kind["base"])))
        merged.setdefault("attributes", {}).update(changes.pop("attributes", {}))
        merged.update(changes)
        _write_json(datapack / f"data/gm/dimension_type/{slot}.json", merged)
        kind = f"gm:{slot}"
    return slot, {"type": kind, "generator": _resolve_tokens(dimension["generator"], feature_id, ledger), "spawn": dimension.get("spawn", {"x": 0, "z": 0})}


def _render_ruin(feature_id, name, ruin, ledger, datapack):
    """A ruin's chest loot is a normal loot table, written here under a meaningless name. A chest nobody has opened yet
    finds its loot by that name, so it has to stay the same from one release to the next, whatever's in the table."""
    def write_table(table, where):
        hashed = "l" + hashlib.sha256(where.encode()).hexdigest()[:10]
        _write_json(datapack / f"data/gm/loot_table/chests/{hashed}.json", _resolve_tokens(table, feature_id, ledger))
        return f"gm:chests/{hashed}"

    patch = _resolve_tokens({key: value for key, value in ruin.items() if key != "loot"}, feature_id, ledger)
    patch["id"] = ruin["id"]
    patch["loot"] = write_table(ruin["loot"], f"{feature_id}/{name}") if ruin.get("loot") else None
    for index, layout in enumerate(patch.get("layouts") or [patch.get("parts", [])]):
        for part in layout:
            if part.get("loot"):
                part["loot"] = write_table(part["loot"], f"{feature_id}/{name}/{index}/{part.get('x')}/{part.get('y')}/{part.get('z')}")
    return patch


def _copy_sounds(feature, feature_id, pack, sounds_json):
    for name in feature["manifest"].get("sounds", []):
        source = feature["dir"] / "assets" / "sounds" / f"{name}.ogg"
        if not source.exists():
            raise BundleError(f"{feature_id}: sound {name}.ogg is missing")
        hashed = _sound_id(feature_id, name)
        target = pack / "assets/gm/sounds" / f"{hashed}.ogg"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        sounds_json[hashed] = {"sounds": [f"gm:{hashed}"]}


def panel_chest_slots(panel):
    """Where each thing goes in the real chest underneath a panel, which is what a client with no companion sees, and what a click on
    it really is for one that has. It's in the order they're listed. Returns how many places that takes."""
    used = 0
    for widget in panel.get("widgets", []):
        kind = widget.get("type")
        size = {"slot": 1, "button": 1, "text_field": 1, "tabs": len(widget.get("tabs", [])), "list": widget.get("max_rows", DEFAULT_LIST_ROWS),
                "label": 1 if widget.get("id") else 0, "bar": 1 if widget.get("id") else 0, "icon": 1 if widget.get("id") else 0}.get(kind, 0)
        if size:
            widget["chest_slot"], widget["chest_size"] = used, size
            used += size
    return used


def _panel_image(feature, feature_id, panel_name, name, pack):
    source = feature["dir"] / "assets" / "panels" / f"{name}.png"
    if not source.exists():
        raise BundleError(f"{feature_id}/{panel_name}: panel image {name}.png is missing")
    hashed = "p" + hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:16]
    target = pack / "assets/gm/textures/gui" / f"{hashed}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return f"gm:textures/gui/{hashed}.png"


def _render_panels(feature, feature_id, ledger, pack):
    """A panel as a client and the server will read it: slot names for the game, its art under names that give nothing away, and where it all goes in the chest underneath."""
    rendered = {}
    for name, panel in feature["manifest"].get("panels", {}).items():
        copied = json.loads(json.dumps(panel))
        if copied.get("background"):
            copied["background"] = _panel_image(feature, feature_id, name, copied["background"], pack)
        for widget in copied.get("widgets", []):
            for field in PANEL_IMAGE_FIELDS:
                if widget.get(field):
                    widget[field] = _panel_image(feature, feature_id, name, widget[field], pack)
        copied["widgets"] = _resolve_tokens(copied.get("widgets", []), feature_id, ledger)
        copied["chest_rows"] = max(1, (panel_chest_slots(copied) + CHEST_ROW - 1) // CHEST_ROW)
        rendered[f"{feature_id}/{name}"] = copied
    return rendered


def _fits_on(panel, widget, text):
    """Words in another language can be much longer, and a player can't do anything about one that runs off a button or the panel. It's better left in English."""
    wide = len(text) * wording.CHARACTER_WIDTH
    if widget is None:
        return panel.get("title_x", 8) + wide <= panel.get("width", 0)
    if widget.get("type") == "button":
        return wide <= widget.get("width", 0) - wording.BUTTON_MARGIN
    if widget.get("type") == "label" and not widget.get("width"):
        return widget.get("x", 0) + wide <= panel.get("width", 0)
    return True


def translated_panel(panel, words):
    """The same panel in another language. Everything but what it says stays the same, so it works the same."""
    copied = json.loads(json.dumps(panel))

    def said(holder, field, widget):
        if isinstance(holder.get(field), str):
            translated = words.text(holder[field])
            if field in ("tooltip", "hint") or _fits_on(panel, widget, translated):
                holder[field] = translated

    said(copied, "title", None)
    for widget in copied.get("widgets", []):
        for field in ("text", "tooltip", "hint"):
            said(widget, field, widget)
        tabs = widget.get("tabs", [])
        shown = [words.text(tab.get("text", "")) for tab in tabs]
        if widget.get("x", 0) + sum(len(text) * wording.CHARACTER_WIDTH + TAB_GAP for text in shown) <= panel.get("width", 0):
            for tab, text in zip(tabs, shown):
                tab["text"] = text
    return copied


def _write_panels(panels, languages, config):
    _write_json(config / "panels.json", panels)
    for language, words in languages.items():
        _write_json(config / f"panels.{language}.json", {name: translated_panel(panel, words) for name, panel in panels.items()})


def _effect_id(feature_id, name):
    """The companion works this out the same way, from the name a module asks for."""
    return "p" + _sound_id(feature_id, name)


def _copy_screen_effects(feature, feature_id, pack):
    """A feature writes the shader, and this says how the game should run it: the picture through that, and the result back."""
    for name in feature["manifest"].get("screen_effects", []):
        source = feature["dir"] / "assets" / "shaders" / f"{name}.fsh"
        if not source.exists():
            raise BundleError(f"{feature_id}: screen effect {name}.fsh is missing")
        hashed = _effect_id(feature_id, name)
        target = pack / "assets/gm/shaders/post" / f"{hashed}.fsh"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        # Listing Globals is what lets the shader use the game's clock. The companion takes this fixed value away again.
        _write_json(pack / "assets/gm/post_effect" / f"{hashed}.json", {"targets": {"swap": {}}, "passes": [
            {"vertex_shader": "minecraft:core/screenquad", "fragment_shader": f"gm:post/{hashed}",
             "inputs": [{"sampler_name": "In", "target": "minecraft:main"}], "output": "swap",
             "uniforms": {"Globals": [{"name": "GameTime", "type": "float", "value": 0.0}]}},
            {"vertex_shader": "minecraft:core/screenquad", "fragment_shader": "minecraft:post/blit",
             "inputs": [{"sampler_name": "In", "target": "swap"}], "output": "minecraft:main",
             "uniforms": {"BlitConfig": [{"name": "ColorModulate", "type": "vec4", "value": [1.0, 1.0, 1.0, 1.0]}]}},
        ]})


def _machine_home(features, feature_id, machine):
    """Whose list a machine recipe goes on. A machine's module only asks for what's on its own feature's list, so a recipe for
    another feature's machine has to go there, or it never fires even though recipe viewers show it. A feature can name a
    machine with no block of that name, so that's only taken to be another feature's if exactly one other feature has one."""
    if "/" in machine:
        return machine
    if machine not in features[feature_id]["manifest"].get("blocks", {}):
        owners = [other for other, feature in features.items() if machine in feature["manifest"].get("blocks", {})]
        if len(owners) == 1:
            return f"{owners[0]}/{machine}"
    return f"{feature_id}/{machine}"


def _knowledge_routes(entry, feature_id, name, ledger):
    """What a route needs first goes by full name in what the game reads, because that's how it knows who knows what."""
    routes = _resolve_tokens(entry.get("routes", []), feature_id, ledger)
    for route in routes:
        if "requires" in route:
            if not isinstance(route["requires"], list) or not all(isinstance(need, str) for need in route["requires"]):
                raise BundleError(f"Knowledge {feature_id}/{name} has a route with requires {route['requires']!r}. It's a list of entries a player has to know first, like [\"gem_cutting\"].")
            route["requires"] = [need if "/" in need else f"{feature_id}/{need}" for need in route["requires"]]
    return routes


def _render_raw(feature, feature_id, ledger, pack, datapack, vanilla_tags):
    """A feature's own vanilla files, under names that give nothing away. Additions to vanilla's tags are saved up, because several features can
    add to one. Returns what's now in the world for good, because it's only read when the server starts, and items and worlds hold on to it."""
    try:
        files = rawpack.files(feature["dir"])
    except rawpack.Refused as error:
        raise BundleError(f"{feature_id}: {error}") from error
    kept = []
    for raw in files:
        relative = raw.target(feature_id)
        target = (pack if raw.kind == "assets" else datapack) / relative
        if raw.kind == "data" and not raw.is_vanilla_tag and rawpack.needs_restart(relative):
            kept.append(f"{raw.registry}/{feature_id}/{raw.name}")
        if not raw.is_json:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(raw.path, target)
            continue
        try:
            contents = json.loads(raw.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise BundleError(f"{feature_id}: raw/{raw.relative} isn't valid JSON: {error}") from error
        resolved = _resolve_tokens(contents, feature_id, ledger)
        if raw.is_vanilla_tag:
            values = resolved.get("values", []) if isinstance(resolved, dict) else []
            vanilla_tags.setdefault(f"{raw.registry}/{raw.name}", []).extend(values)
        else:
            _write_json(target, resolved)
    return kept


def _render_loot_additions(features, ledger, vanilla_file, datapack):
    """Vanilla's table with what features add on the end of it. It's read from the game's own jar for each release, so vanilla's part of it can't
    go stale, and nothing in the world remembers it. Several features can add to one, in the order the features are in."""
    added = {}
    for feature_id, feature in features.items():
        for addition in feature["manifest"].get("loot_additions", []):
            table = str(addition.get("table", ""))
            if not table.startswith("minecraft:"):
                raise BundleError(f"{feature_id}: loot_additions is for vanilla's tables, like minecraft:chests/simple_dungeon, not {table!r}. Your own go in raw/data/gm/loot_table/.")
            added.setdefault(table, []).extend(_resolve_tokens(addition.get("pools", []), feature_id, ledger))
    for table, pools in added.items():
        path = f"data/minecraft/loot_table/{table.split(':', 1)[1]}.json"
        try:
            original = vanilla_file(path) if vanilla_file else None
        except KeyError:
            original = None
        if original is None:
            raise BundleError(f"loot_additions: vanilla has no loot table called {table}.")
        _write_json(datapack / path, {**original, "pools": [*original.get("pools", []), *pools]})


def _link_knowledge(entries, gated, recipe_routes):
    """A recipe names the knowledge that unlocks it. Done last, because that may be in a later feature."""
    for recipe_id, source, route in recipe_routes:
        key = route if "/" in route else f"{source.split('/')[0]}/{route}"
        if key not in entries:
            raise BundleError(f"Recipe {source} is learned through {key!r}, which no feature declares")
        gated[recipe_id] = [key]
        entries[key]["recipes"].append(recipe_id)


def _literal(text):
    return text.replace("%", "%%")


def _write_book(features, ledger, entries, machines, names, nodes, pack, lang):
    """The Codex, from the knowledge entries as they are once everything's linked up, in the names players know things by. Patchouli
    finds its pages through the English folder and then prefers the same file from a player's own language's, so that's what's written.
    Titles and text also go in the language files, for the server to say them in chat and for a client with no Patchouli to read."""
    by_machine = {}
    for recipes in machines.values():
        for recipe in recipes:
            for key in recipe["needs"]:
                by_machine.setdefault(key, []).append(recipe["id"])

    def listed(title, text, shown):
        found = []
        for feature_id, feature in features.items():
            manifest = feature["manifest"]
            things = [f"gm:{ledger[table][f'{feature_id}/{name}']['slot']}" for table in ("items", "blocks") for name in manifest.get(table, {})]
            for name, entry in manifest.get("knowledge", {}).items():
                key = f"{feature_id}/{name}"
                resolved = _resolve_tokens(text(entry["text"]), feature_id, ledger)
                entries[key]["guide"] = guide.flag(key)
                found.append({"key": key, "title": title(entry["title"]), "text": re.sub(r"gm:[ise]\d{4}", lambda match: shown.get(match[0], match[0]), resolved),
                              "routes": entries[key]["routes"], "recipes": entries[key]["recipes"] + by_machine.get(key, []), "node": manifest.get("node"),
                              "things": things, "icon": _resolve_tokens(entry.get("icon"), feature_id, ledger)})
        return found

    def keep_words(shown, into):
        for entry in shown:
            into[f"knowledge.gm.{guide.flag(entry['key'])}"] = _literal(entry["title"])
            into[f"knowledge.gm.{guide.flag(entry['key'])}.text"] = entry["text"]

    english = listed(str, str, names)
    keep_words(english, lang.english)
    english_book = guide.book(english, nodes)
    for path, contents in english_book.items():
        _write_json(pack / path, contents)
    for language, words in lang.languages.items():
        translated = listed(words.name, words.text, {thing: words.name(name) for thing, name in names.items()})
        said = {}
        keep_words(translated, said)
        lang.others[language].update({key: text for key, text in said.items() if text != lang.english[key]})
        book_words = wording.engine_words(language, "book")
        node_names = {node: {**info, "name": words.name(info["name"])} if info.get("name") else info for node, info in nodes.items()}
        for path, contents in guide.book(translated, node_names, language, lambda text: book_words.get(text, text)).items():
            if contents != english_book[path.replace(f"/{language}/", f"/{wording.ENGLISH}/")]:
                for variant in wording.SAME_WORDS.get(language, (language,)):
                    _write_json(pack / path.replace(f"/{language}/", f"/{variant}/"), contents)


def render(features, ledger, out, data_format, vanilla_biome=None, scope="shared", nodes=None, vanilla_type=None, languages=None, vanilla_file=None):
    """Writes pack/, datapack/ and config/ under out. Returns nothing: out is the release's content. Languages are what wording.load_languages
    gives, and everything's written in English as well, for any game set to a language that isn't one of them."""
    pack = out / "pack"
    datapack = out / "datapack"
    config = out / "config"
    for folder in (pack, datapack, config):
        folder.mkdir(parents=True, exist_ok=True)

    languages = languages or {}
    lang = LanguageFiles(languages)
    tags = {}
    patches = []
    surface_patches = []
    biome_patches = []
    ruin_patches = []
    dimensions = {}
    item_defaults = {}
    bindings = {}
    recipe_modes = {}
    entries = {}
    gated = {}
    open_recipes = []
    recipe_routes = []
    machines = {}
    names = {}
    mobs = {}
    sounds_json = {}
    block_models = {}
    machine_inventories = {}
    block_settings = {}
    panels = {}
    vanilla_tags = {}
    kept_raw = set(ledger.get("raw", []))

    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        for name, block in manifest.get("blocks", {}).items():
            slot = ledger["blocks"][f"{feature_id}/{name}"]["slot"]
            bindings[f"{feature_id}/{name}"] = slot
            names[f"gm:{slot}"] = block["display"]
            lang.name(f"block.gm.{slot}", block["display"])
            _copy_texture(feature, "block", slot, block.get("texture", name), pack)
            for face, texture in block.get("faces", {}).items():
                if face not in BLOCK_FACES:
                    raise BundleError(f"{feature_id}/{name}: there's no face called {face!r}. Use {', '.join(sorted(BLOCK_FACES))}.")
                _copy_texture(feature, "block", f"{slot}_{face}", texture, pack)
            if (block["family"] == "model") != ("model" in block):
                raise BundleError(f"{feature_id}/{name}: a block in the model family needs a \"model\", and only those can have one.")
            if "model" in block:
                block_models[slot] = _copy_model(feature, feature_id, name, block["model"], config)
            _write_json(pack / f"assets/gm/models/block/{slot}.json",
                        _block_model(feature, feature_id, name, block, slot, ledger))
            if block["family"] in FLAT_ICON_FAMILIES:
                _flat_icon(feature, block, name, slot, pack)
            if block["family"] == "crop":
                for stage, texture in enumerate(block.get("stages") or []):
                    _copy_texture(feature, "block", f"{slot}_{stage}", texture, pack)
                    _write_json(pack / f"assets/gm/models/block/{slot}_{stage}.json", {"parent": "minecraft:block/cross", "textures": {"cross": f"gm:block/{slot}_{stage}"}})
                tags.setdefault("maintains_farmland", []).append(f"gm:{slot}")
            if block["family"] == "ladder":
                tags.setdefault("climbable", []).append(f"gm:{slot}")
            if block["family"] == "connected":
                for shape in range(1 << len(CONNECTED_ARMS)):
                    _write_json(pack / f"assets/gm/models/block/{slot}_c{shape}.json", _connected_model(slot, shape))
            settings = {key: block[key] for key in ("hardness", "growth") if key in block}
            settings.update({key: _resolve_tokens(block[key], feature_id, ledger) for key in ("on", "connects") if key in block})
            if settings:
                block_settings[slot] = settings
            _write_json(datapack / f"data/gm/loot_table/blocks/{slot}.json",
                        _loot_table(block, name, slot, feature_id, ledger))
            if block.get("inventory"):
                machine_inventories[slot] = block["inventory"]
            tool = block.get("tool")
            if tool:
                if tool not in TOOL_TAGS:
                    raise BundleError(f"{feature_id}/{name}: unknown tool {tool!r}")
                tags.setdefault(f"mineable/{TOOL_TAGS[tool]}", []).append(f"gm:{slot}")
            level = block.get("tool_level")
            if level in LEVEL_TAGS:
                tags.setdefault(LEVEL_TAGS[level], []).append(f"gm:{slot}")
        for name, item in manifest.get("items", {}).items():
            slot = ledger["items"][f"{feature_id}/{name}"]["slot"]
            bindings[f"{feature_id}/{name}"] = slot
            names[f"gm:{slot}"] = item["display"]
            lang.name(f"item.gm.{slot}", item["display"])
            _copy_texture(feature, "item", slot, item.get("texture", name), pack)
            # Handheld is how vanilla's tools sit in the hand.
            parent = "minecraft:item/handheld" if item.get("handheld") else "minecraft:item/generated"
            _write_json(pack / f"assets/gm/models/item/{slot}.json", {"parent": parent, "textures": {"layer0": f"gm:item/{slot}"}})
            definition = _item_definition(feature, item, slot, parent, pack)
            if definition:
                _write_json(pack / f"assets/gm/items/{slot}.json", {"model": definition})
            defaults = {key: item[key] for key in ("components", "places") if key in item}
            if "use" in item:
                defaults["components"] = {**defaults.get("components", {}), "minecraft:consumable": {
                    "consume_seconds": item["use"].get("seconds", 1), "animation": item["use"].get("animation", "none"),
                    "sound": USE_SOUND, "has_consume_particles": False}}
                defaults["timed_use"] = True
            if "tooltip" in item:
                # As keys, because a stack keeps what it was made with, whichever language whoever's holding it plays in.
                for index, line in enumerate(item["tooltip"]):
                    lang.literal(f"tooltip.gm.{slot}.{index}", line)
                defaults["components"] = {**defaults.get("components", {}), "minecraft:lore": [
                    {"translate": f"tooltip.gm.{slot}.{index}", "fallback": _literal(line), "italic": False, "color": "gray"} for index, line in enumerate(item["tooltip"])]}
            if "components" in defaults:
                defaults["components"] = _wearable(defaults["components"])
            if defaults:
                item_defaults[f"gm:{slot}"] = _resolve_tokens(defaults, feature_id, ledger)
        for name, recipe in manifest.get("recipes", {}).items():
            source = f"{feature_id}/{name}"
            # Named by hash, so the recipe's file name can't give away what it makes.
            hashed = "r" + hashlib.sha256(source.encode()).hexdigest()[:10]
            recipe_modes[f"gm:{hashed}"] = {"mode": recipe.get("mode"), "route": recipe.get("route"), "source": source,
                                            "machine": recipe.get("machine"), "type": recipe.get("json", {}).get("type")}
            if isinstance(recipe.get("machine"), str):
                route = recipe.get("route")
                machines.setdefault(_machine_home(features, feature_id, recipe["machine"]), []).append({
                    "id": source,
                    "mode": recipe.get("mode"),
                    "inputs": _resolve_tokens(recipe["inputs"], feature_id, ledger),
                    "outputs": _resolve_tokens(recipe.get("outputs") or [recipe["output"]], feature_id, ledger),
                    "needs": [route if "/" in route else f"{feature_id}/{route}"] if route else [],
                })
                continue
            body = _resolve_tokens(recipe["json"], feature_id, ledger)
            if isinstance(body.get("result"), dict) and "components" in body["result"]:
                body["result"]["components"] = _wearable(body["result"]["components"])
            _write_json(datapack / f"data/gm/recipe/{hashed}.json", body)
            if recipe.get("mode") == "known" and recipe.get("route"):
                recipe_routes.append((f"gm:{hashed}", source, recipe["route"]))
            elif recipe.get("mode") == "open":
                open_recipes.append(f"gm:{hashed}")
        for name, entry in manifest.get("knowledge", {}).items():
            entries[f"{feature_id}/{name}"] = {
                "title": entry["title"], "text": entry["text"], "recipes": [],
                "routes": _knowledge_routes(entry, feature_id, name, ledger),
            }
        for name, mob in manifest.get("mobs", {}).items():
            slot, definition = _render_mob(feature, feature_id, name, mob, ledger, lang, datapack, config)
            bindings[f"{feature_id}/{name}"] = slot
            names[f"gm:{slot}"] = mob["display"]
            mobs[f"gm:{slot}"] = definition
        for plant in manifest.get("plants", []):
            surface_patches.append({**_resolve_tokens(plant, feature_id, ledger), "block": _resolve_tokens(f"$block:{plant['block']}", feature_id, ledger)})
        for name, biome in manifest.get("biomes", {}).items():
            patch = _render_biome(feature_id, name, biome, vanilla_biome, datapack)
            # One made for a dimension of its own has no business turning up across the overworld.
            if biome.get("spread", True):
                biome_patches.append(patch)
        for name, dimension in manifest.get("dimensions", {}).items():
            slot, rendered = _render_dimension(feature_id, name, dimension, ledger, vanilla_type, datapack)
            bindings[f"dimension:{feature_id}/{name}"] = slot
            dimensions[f"gm:{slot}"] = rendered
        for name, ruin in manifest.get("ruins", {}).items():
            ruin_patches.append(_render_ruin(feature_id, name, ruin, ledger, datapack))
        _copy_sounds(feature, feature_id, pack, sounds_json)
        _copy_screen_effects(feature, feature_id, pack)
        kept_raw.update(_render_raw(feature, feature_id, ledger, pack, datapack, vanilla_tags))
        panels.update(_render_panels(feature, feature_id, ledger, pack))
        # Marked as sounds, so one can share its name with a block or a mob, which are all in here by bare name.
        bindings.update({f"sound:{feature_id}/{name}": _sound_id(feature_id, name) for name in manifest.get("sounds", [])})
        for ore in manifest.get("ores", []):
            patches.append({
                "id": ore["id"],
                "block": _resolve_tokens(f"$block:{ore['block']}", feature_id, ledger),
                "replaces": ore["replaces"],
                "veinsPerChunk": ore["veinsPerChunk"],
                "veinSize": ore["veinSize"],
                "minY": ore["minY"],
                "maxY": ore["maxY"],
                "biomes": _resolve_tokens(ore.get("biomes", []), feature_id, ledger),
                "touchingAir": bool(ore.get("touchingAir")),
                **({"dimension": _resolve_tokens(ore["dimension"], feature_id, ledger)} if "dimension" in ore else {}),
            })
        for name, text in manifest.get("texts", {}).items():
            lang.text(f"text.gm.{wording.text_id(feature_id, name)}", text)
        lang_file = feature["dir"] / "assets" / "lang.json"
        if lang_file.exists():
            for key, text in json.loads(lang_file.read_text(encoding="utf-8")).items():
                lang.text(key, text)

    # After every mob is rendered, because the one being given a new look may be in a later feature.
    for feature_id, feature in features.items():
        for target, model_name in feature["manifest"].get("reskins", {}).items():
            slot = ledger.get("mobs", {}).get(target, {}).get("slot")
            if slot is None:
                raise BundleError(f"{feature_id}: reskins a mob {target!r}, which no feature declares. Name it as feature/name.")
            mobs[f"gm:{slot}"]["model"] = _copy_model(feature, feature_id, target, model_name, config)

    _link_knowledge(entries, gated, recipe_routes)
    _write_book(features, ledger, entries, machines, names, nodes or {}, pack, lang)
    lang.write(pack)
    if sounds_json:
        _write_json(pack / "assets/gm/sounds.json", sounds_json)
    _render_loot_additions(features, ledger, vanilla_file, datapack)
    for tag, values in tags.items():
        vanilla_tags.setdefault(f"tags/block/{tag}", []).extend(values)
    for tag, values in vanilla_tags.items():
        unique = {json.dumps(value, sort_keys=True): value for value in values}
        _write_json(datapack / f"data/minecraft/{tag}.json", {"replace": False, "values": [unique[key] for key in sorted(unique)]})
    _write_json(datapack / "pack.mcmeta", {
        "pack": {"description": "Living Mod", "min_format": data_format, "max_format": data_format},
    })
    _write_json(config / "ore_patches.json", patches)
    _write_json(config / "surface_patches.json", surface_patches)
    _write_json(config / "biome_patches.json", biome_patches)
    _write_json(config / "ruin_patches.json", ruin_patches)
    _write_json(config / "dimensions.json", dimensions)
    _write_json(config / "bindings.json", bindings)
    _write_json(config / "item_defaults.json", item_defaults)
    _write_json(config / "mobs.json", mobs)
    _write_json(config / "block_models.json", block_models)
    _write_json(config / "machine_inventories.json", machine_inventories)
    _write_json(config / "block_settings.json", block_settings)
    _write_panels(panels, languages, config)
    _write_json(config / "knowledge.json", {"scope": scope, "entries": entries, "gated": gated, "open": sorted(open_recipes),
                                            "machines": machines, "names": names})
    _write_json(out / "recipes.json", recipe_modes)
    ledger["raw"] = sorted(kept_raw)
    ledger["patches"] = sorted(set(ledger.get("patches", []))
                               | {patch["id"] for patch in patches + surface_patches + biome_patches + ruin_patches})


def tree_hash(path, leave_out=lambda relative: False):
    """A hash of everything under a folder, for telling whether a release changed it. Anything leave_out says yes to doesn't count, going by its path from there."""
    digest = hashlib.sha256()
    if path.exists():
        for item in sorted(file for file in path.rglob("*") if file.is_file()):
            relative = item.relative_to(path).as_posix()
            if not leave_out(relative):
                digest.update(relative.encode())
                digest.update(item.read_bytes())
    return digest.hexdigest()


def load_ledger(path):
    return {**empty_ledger(), **json.loads(path.read_text(encoding="utf-8"))} if path.exists() else empty_ledger()


def save_ledger(path, ledger):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def find_modules(features):
    """Which features carry Java modules, as (feature id, side) pairs."""
    found = []
    for feature_id, feature in features.items():
        for side in ("server", "client"):
            if (feature["dir"] / side / "src").is_dir():
                found.append((feature_id, side))
    return found


def find_mixins(features):
    """Which features patch the game's own code. See broker/gates/mixins.py."""
    return [feature_id for feature_id, feature in features.items() if (feature["dir"] / "mixins" / "src").is_dir()]


if __name__ == "__main__":
    print(read_pool(pathlib.Path(__file__).resolve().parent.parent))
