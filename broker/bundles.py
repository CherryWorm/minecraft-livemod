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

TOKEN = re.compile(r"\$(block|item):([a-z0-9_]+(?:/[a-z0-9_]+)?)")

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
    return {"families": families, "item_count": item_count}


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
    return {"blocks": {}, "items": {}, "patches": []}


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
    return ledger


def _resolver(feature_id, ledger):
    def resolve(match):
        kind, name = match.group(1), match.group(2)
        key = name if "/" in name else f"{feature_id}/{name}"
        table = ledger["blocks"] if kind == "block" else ledger["items"]
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


def _loot_table(block, slot, feature_id, ledger):
    drops = block.get("drops")
    entry_name = f"gm:{slot}"
    functions = []
    if drops:
        entry_name = _resolve_tokens(f"$item:{drops['item']}", feature_id, ledger)
        count = drops.get("count")
        if isinstance(count, list):
            functions.append({"function": "minecraft:set_count",
                              "count": {"type": "minecraft:uniform", "min": count[0], "max": count[1]}})
    return {
        "type": "minecraft:block",
        "pools": [{
            "rolls": 1,
            "entries": [{"type": "minecraft:item", "name": entry_name, "functions": functions}],
            "conditions": [{"condition": "minecraft:survives_explosion"}],
        }],
    }


def render(features, ledger, out, data_format):
    """Writes pack/, datapack/ and config/ under out. Returns nothing: out is the release's content."""
    pack = out / "pack"
    datapack = out / "datapack"
    config = out / "config"
    for folder in (pack, datapack, config):
        folder.mkdir(parents=True, exist_ok=True)

    lang = {}
    tags = {}
    patches = []
    bindings = {}
    recipe_modes = {}

    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        for name, block in manifest.get("blocks", {}).items():
            slot = ledger["blocks"][f"{feature_id}/{name}"]["slot"]
            bindings[f"{feature_id}/{name}"] = slot
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
            lang[f"item.gm.{slot}"] = item["display"]
            _copy_texture(feature, "item", slot, item.get("texture", name), pack)
            _write_json(pack / f"assets/gm/models/item/{slot}.json",
                        {"parent": "minecraft:item/generated", "textures": {"layer0": f"gm:item/{slot}"}})
        for name, recipe in manifest.get("recipes", {}).items():
            # Named by hash, so the recipe's file name can't give away what it makes.
            hashed = "r" + hashlib.sha256(f"{feature_id}/{name}".encode()).hexdigest()[:10]
            resolved = _resolve_tokens(recipe["json"], feature_id, ledger)
            _write_json(datapack / f"data/gm/recipe/{hashed}.json", resolved)
            recipe_modes[f"gm:{hashed}"] = {"mode": recipe.get("mode"), "route": recipe.get("route"),
                                            "source": f"{feature_id}/{name}"}
        for ore in manifest.get("ores", []):
            patches.append({
                "id": ore["id"],
                "block": _resolve_tokens(f"$block:{ore['block']}", feature_id, ledger),
                "replaces": ore["replaces"],
                "veinsPerChunk": ore["veinsPerChunk"],
                "veinSize": ore["veinSize"],
                "minY": ore["minY"],
                "maxY": ore["maxY"],
            })
        lang_file = feature["dir"] / "assets" / "lang.json"
        if lang_file.exists():
            lang.update(json.loads(lang_file.read_text(encoding="utf-8")))

    _write_json(pack / "assets/gm/lang/en_us.json", lang)
    for tag, values in tags.items():
        _write_json(datapack / f"data/minecraft/tags/block/{tag}.json", {"replace": False, "values": sorted(values)})
    _write_json(datapack / "pack.mcmeta", {
        "pack": {"description": "Living Mod", "min_format": data_format, "max_format": data_format},
    })
    _write_json(config / "ore_patches.json", patches)
    _write_json(config / "bindings.json", bindings)
    _write_json(out / "recipes.json", recipe_modes)
    ledger["patches"] = sorted(set(ledger.get("patches", [])) | {patch["id"] for patch in patches})


def tree_hash(path):
    """A hash of everything under a folder, for telling whether a release changed it."""
    digest = hashlib.sha256()
    if path.exists():
        for item in sorted(file for file in path.rglob("*") if file.is_file()):
            digest.update(str(item.relative_to(path)).encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


def load_ledger(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_ledger()


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
