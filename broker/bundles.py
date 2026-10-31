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

TOKEN = re.compile(r"\$(block|item|mob|sound):([a-z0-9_]+(?:/[a-z0-9_]+)?)")

TOOL_TAGS = {"pickaxe": "pickaxe", "axe": "axe", "shovel": "shovel", "hoe": "hoe"}
LEVEL_TAGS = {"stone": "needs_stone_tool", "iron": "needs_iron_tool", "diamond": "needs_diamond_tool"}


class BundleError(Exception):
    """A problem with a bundle, worded so the agent can fix it."""


def read_pool(repo):
    """Reads the slot pool from the mod's own source, so this can't drift from what's registered."""
    source = (repo / "mods/conduit/src/main/java/gm/conduit/slots/SlotFamily.java").read_text(encoding="utf-8")
    families = {}
    for name, first, count in re.findall(r"^\s+([A-Z_]+)\((\d+), (\d+), BlockModelType", source, re.MULTILINE):
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
    return features


def empty_ledger():
    return {"blocks": {}, "items": {}, "mobs": {}, "patches": []}


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


def _sound_id(feature_id, name):
    return hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:16]


def _resolver(feature_id, ledger):
    def resolve(match):
        kind, name = match.group(1), match.group(2)
        key = name if "/" in name else f"{feature_id}/{name}"
        if kind == "sound":
            return f"gm:{_sound_id(*key.split('/'))}"
        table = {"block": ledger["blocks"], "item": ledger["items"], "mob": ledger.get("mobs", {})}[kind]
        if key not in table:
            raise BundleError(f"{feature_id}: refers to unknown {kind} {key!r}")
        return f"gm:{table[key]['slot']}"
    return resolve


def _resolve_tokens(value, feature_id, ledger):
    if isinstance(value, str):
        return TOKEN.sub(_resolver(feature_id, ledger), value)
    if isinstance(value, list):
        return [_resolve_tokens(item, feature_id, ledger) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_tokens(item, feature_id, ledger) for key, item in value.items()}
    return value


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")


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


def _block_model(feature, feature_id, name, block, slot, ledger):
    custom = feature["dir"] / "assets" / "models" / f"{name}.json"
    if custom.exists():
        model = json.loads(custom.read_text(encoding="utf-8"))
        return _resolve_tokens(model, feature_id, ledger)
    parent = "minecraft:block/cross" if block["family"] in ("plant", "tinted_plant") else "minecraft:block/cube_all"
    key = "cross" if "cross" in parent else "all"
    return {"parent": parent, "textures": {key: f"gm:block/{slot}"}}


def _drop_entry(drops, fallback, feature_id, ledger):
    entry_name = fallback
    functions = []
    if drops:
        entry_name = _resolve_tokens(f"$item:{drops['item']}", feature_id, ledger)
        count = drops.get("count")
        if isinstance(count, list):
            functions.append({"function": "minecraft:set_count",
                              "count": {"type": "minecraft:uniform", "min": count[0], "max": count[1]}})
    return {"type": "minecraft:item", "name": entry_name, "functions": functions}


def _loot_table(block, slot, feature_id, ledger):
    return {
        "type": "minecraft:block",
        "pools": [{
            "rolls": 1,
            "entries": [_drop_entry(block.get("drops"), f"gm:{slot}", feature_id, ledger)],
            "conditions": [{"condition": "minecraft:survives_explosion"}],
        }],
    }


def _render_mob(feature, feature_id, name, mob, ledger, pack_lang, datapack, config):
    slot = ledger["mobs"][f"{feature_id}/{name}"]["slot"]
    source = feature["dir"] / "assets" / "models" / f"{mob.get('model', name)}.bbmodel"
    if not source.exists():
        raise BundleError(f"{feature_id}/{name}: model {source.name} is missing")
    raw = source.read_bytes()
    model = "m" + hashlib.sha256(raw).hexdigest()[:16]
    (config / "models").mkdir(parents=True, exist_ok=True)
    (config / "models" / f"{model}.bbmodel").write_bytes(raw)
    pack_lang[f"entity.gm.{slot}"] = mob["display"]
    if mob.get("drops"):
        _write_json(datapack / f"data/gm/loot_table/entities/{slot}.json", {
            "type": "minecraft:entity",
            "pools": [{"rolls": 1, "entries": [_drop_entry(mob["drops"], "", feature_id, ledger)]}],
        })
    fields = ("behaviour", "health", "damage", "speed", "width", "height", "followRange", "armor", "spawn")
    return slot, {"model": model, **{field: mob[field] for field in fields if field in mob}}


def _render_biome(feature_id, name, biome, vanilla_biome, datapack):
    """Starts from a vanilla biome, so builders only state what's different. Changing only how it looks makes a
    sibling, which is safe to spread into land people have already seen."""
    base = biome.get("base")
    if not base or vanilla_biome is None:
        raise BundleError(f"{feature_id}/{name}: a biome needs a 'base' vanilla biome to start from")
    merged = json.loads(json.dumps(vanilla_biome(base)))
    merged.setdefault("effects", {}).update(biome.get("effects", {}))
    climate_changed = False
    for field in ("temperature", "downfall", "has_precipitation", "spawners", "spawn_costs", "features", "carvers"):
        if field in biome and biome[field] != merged.get(field):
            merged[field] = biome[field]
            climate_changed = True
    hashed = "b" + hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:10]
    _write_json(datapack / f"data/gm/worldgen/biome/{hashed}.json", merged)
    return {"id": f"biome_{hashed}", "from": base, "to": f"gm:{hashed}", "proportion": biome.get("proportion", 0.2), "sibling": not climate_changed}


def _render_ruin(feature_id, name, ruin, ledger, datapack):
    """A ruin's chest loot is a normal loot table, written here under a meaningless name."""
    patch = _resolve_tokens({key: value for key, value in ruin.items() if key != "loot"}, feature_id, ledger)
    patch["id"] = ruin["id"]
    patch["loot"] = None
    if ruin.get("loot"):
        hashed = "l" + hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:10]
        _write_json(datapack / f"data/gm/loot_table/chests/{hashed}.json", _resolve_tokens(ruin["loot"], feature_id, ledger))
        patch["loot"] = f"gm:chests/{hashed}"
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


def _link_knowledge(entries, gated, recipe_routes):
    """A recipe names the knowledge that unlocks it. Done last, because that may be in a later feature."""
    for recipe_id, source, route in recipe_routes:
        key = route if "/" in route else f"{source.split('/')[0]}/{route}"
        if key not in entries:
            raise BundleError(f"Recipe {source} is learned through {key!r}, which no feature declares")
        gated[recipe_id] = [key]
        entries[key]["recipes"].append(recipe_id)


def render(features, ledger, out, data_format, vanilla_biome=None, scope="shared"):
    """Writes pack/, datapack/ and config/ under out. Returns nothing: out is the release's content."""
    pack = out / "pack"
    datapack = out / "datapack"
    config = out / "config"
    for folder in (pack, datapack, config):
        folder.mkdir(parents=True, exist_ok=True)

    lang = {}
    tags = {}
    patches = []
    surface_patches = []
    biome_patches = []
    ruin_patches = []
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

    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        for name, block in manifest.get("blocks", {}).items():
            slot = ledger["blocks"][f"{feature_id}/{name}"]["slot"]
            bindings[f"{feature_id}/{name}"] = slot
            names[f"gm:{slot}"] = block["display"]
            lang[f"block.gm.{slot}"] = block["display"]
            _copy_texture(feature, "block", slot, block.get("texture", name), pack)
            _write_json(pack / f"assets/gm/models/block/{slot}.json",
                        _block_model(feature, feature_id, name, block, slot, ledger))
            _write_json(datapack / f"data/gm/loot_table/blocks/{slot}.json",
                        _loot_table(block, slot, feature_id, ledger))
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
            lang[f"item.gm.{slot}"] = item["display"]
            _copy_texture(feature, "item", slot, item.get("texture", name), pack)
            _write_json(pack / f"assets/gm/models/item/{slot}.json",
                        {"parent": "minecraft:item/generated", "textures": {"layer0": f"gm:item/{slot}"}})
        for name, recipe in manifest.get("recipes", {}).items():
            source = f"{feature_id}/{name}"
            # Named by hash, so the recipe's file name can't give away what it makes.
            hashed = "r" + hashlib.sha256(source.encode()).hexdigest()[:10]
            recipe_modes[f"gm:{hashed}"] = {"mode": recipe.get("mode"), "route": recipe.get("route"), "source": source,
                                            "machine": recipe.get("machine"), "type": recipe.get("json", {}).get("type")}
            if isinstance(recipe.get("machine"), str):
                route = recipe.get("route")
                machines.setdefault(f"{feature_id}/{recipe['machine']}", []).append({
                    "id": source,
                    "mode": recipe.get("mode"),
                    "inputs": _resolve_tokens(recipe["inputs"], feature_id, ledger),
                    "output": _resolve_tokens(recipe["output"], feature_id, ledger),
                    "needs": [route if "/" in route else f"{feature_id}/{route}"] if route else [],
                })
                continue
            _write_json(datapack / f"data/gm/recipe/{hashed}.json", _resolve_tokens(recipe["json"], feature_id, ledger))
            if recipe.get("mode") == "known" and recipe.get("route"):
                recipe_routes.append((f"gm:{hashed}", source, recipe["route"]))
            elif recipe.get("mode") == "open":
                open_recipes.append(f"gm:{hashed}")
        for name, entry in manifest.get("knowledge", {}).items():
            entries[f"{feature_id}/{name}"] = {
                "title": entry["title"], "text": entry["text"], "recipes": [],
                "routes": _resolve_tokens(entry.get("routes", []), feature_id, ledger),
            }
        for name, mob in manifest.get("mobs", {}).items():
            slot, definition = _render_mob(feature, feature_id, name, mob, ledger, lang, datapack, config)
            bindings[f"{feature_id}/{name}"] = slot
            names[f"gm:{slot}"] = mob["display"]
            mobs[f"gm:{slot}"] = definition
        for plant in manifest.get("plants", []):
            surface_patches.append({**plant, "block": _resolve_tokens(f"$block:{plant['block']}", feature_id, ledger)})
        for name, biome in manifest.get("biomes", {}).items():
            biome_patches.append(_render_biome(feature_id, name, biome, vanilla_biome, datapack))
        for name, ruin in manifest.get("ruins", {}).items():
            ruin_patches.append(_render_ruin(feature_id, name, ruin, ledger, datapack))
        _copy_sounds(feature, feature_id, pack, sounds_json)
        for ore in manifest.get("ores", []):
            patches.append({
                "id": ore["id"],
                "block": _resolve_tokens(f"$block:{ore['block']}", feature_id, ledger),
                "replaces": ore["replaces"],
                "veinsPerChunk": ore["veinsPerChunk"],
                "veinSize": ore["veinSize"],
                "minY": ore["minY"],
                "maxY": ore["maxY"],
                "biomes": ore.get("biomes", []),
            })
        lang_file = feature["dir"] / "assets" / "lang.json"
        if lang_file.exists():
            lang.update(json.loads(lang_file.read_text(encoding="utf-8")))

    _link_knowledge(entries, gated, recipe_routes)
    _write_json(pack / "assets/gm/lang/en_us.json", lang)
    if sounds_json:
        _write_json(pack / "assets/gm/sounds.json", sounds_json)
    for tag, values in tags.items():
        _write_json(datapack / f"data/minecraft/tags/block/{tag}.json", {"replace": False, "values": sorted(values)})
    _write_json(datapack / "pack.mcmeta", {
        "pack": {"description": "Living Mod", "min_format": data_format, "max_format": data_format},
    })
    _write_json(config / "ore_patches.json", patches)
    _write_json(config / "surface_patches.json", surface_patches)
    _write_json(config / "biome_patches.json", biome_patches)
    _write_json(config / "ruin_patches.json", ruin_patches)
    _write_json(config / "bindings.json", bindings)
    _write_json(config / "mobs.json", mobs)
    _write_json(config / "knowledge.json", {"scope": scope, "entries": entries, "gated": gated, "open": sorted(open_recipes),
                                            "machines": machines, "names": names})
    _write_json(out / "recipes.json", recipe_modes)
    ledger["patches"] = sorted(set(ledger.get("patches", []))
                               | {patch["id"] for patch in patches + surface_patches + biome_patches + ruin_patches})


def tree_hash(path):
    """A hash of everything under a folder, for telling whether a release changed it."""
    digest = hashlib.sha256()
    if path.exists():
        for item in sorted(file for file in path.rglob("*") if file.is_file()):
            digest.update(str(item.relative_to(path)).encode())
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


if __name__ == "__main__":
    print(read_pool(pathlib.Path(__file__).resolve().parent.parent))
