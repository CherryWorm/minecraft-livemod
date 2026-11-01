#!/usr/bin/env python3
"""Writes broker/gates/vanilla_ids.json, the names the instant checks hold raw pack files to, from the game's own jar and reports.

Run it when versions.env moves to a new Minecraft, on the machine with the server, after the game's data generator has written its reports:

    java -cp <server jar>:<libraries> net.minecraft.data.Main --reports --output /tmp/reports

Usage: refresh-vanilla-ids.py SERVER_JAR REPORTS_DIR
"""
import json
import pathlib
import sys
import zipfile

REGISTRIES = {
    "block": "block", "item": "item", "entity_type": "entity_type", "fluid": "fluid", "game_event": "game_event", "sound_event": "sound_event",
    "attribute": "attribute", "mob_effect": "mob_effect", "trigger": "trigger_type", "loot_function": "loot_function_type",
    "loot_condition": "loot_condition_type", "loot_entry": "loot_pool_entry_type", "enchantment_effect": "enchantment_effect_component_type",
}
JAR_FOLDERS = {"biome": "worldgen/biome", "advancement": "advancement", "loot_table": "loot_table", "damage_type": "damage_type"}
# The registries a raw file is held to the fields of. A field every one of vanilla's has is required, unless it's listed here because the game does without it.
SHAPED = ("advancement", "loot_table", "enchantment", "jukebox_song", "painting_variant", "banner_pattern", "instrument", "decorated_pot_pattern", "damage_type",
          "cat_variant", "cat_sound_variant", "chicken_variant", "chicken_sound_variant", "cow_variant", "cow_sound_variant", "frog_variant", "pig_variant",
          "pig_sound_variant", "wolf_variant", "wolf_sound_variant")
OPTIONAL = {"advancement": {"requirements", "sends_telemetry_event"}, "painting_variant": {"title", "author"}, "enchantment": {"effects", "exclusive_set", "primary_items"},
            "loot_table": {"random_sequence", "pools"}}


def strip(name):
    return name.removeprefix("minecraft:")


def main(jar, reports):
    registries = json.loads((reports / "registries.json").read_text(encoding="utf-8"))
    found = {key: sorted(strip(name) for name in registries[f"minecraft:{registry}"]["entries"]) for key, registry in REGISTRIES.items()}
    with zipfile.ZipFile(jar) as archive:
        names = [name for name in archive.namelist() if name.startswith("data/minecraft/") and name.endswith(".json")]
        for key, folder in JAR_FOLDERS.items():
            prefix = f"data/minecraft/{folder}/"
            found[key] = sorted(name[len(prefix):-len(".json")] for name in names if name.startswith(prefix))
        prefix = "data/minecraft/enchantment/"
        found["enchantment"] = {name[len(prefix):-len(".json")]: json.loads(archive.read(name))["max_level"] for name in sorted(names) if name.startswith(prefix)}
        prefix = "data/minecraft/tags/"
        tags = {}
        for name in names:
            if name.startswith(prefix):
                parts = name[len(prefix):-len(".json")].split("/")
                # A tag's registry is one folder down, or two for worldgen's.
                split = 2 if parts[0] == "worldgen" else 1
                tags.setdefault("/".join(parts[:split]), []).append("/".join(parts[split:]))
        found["tags"] = {registry: sorted(values) for registry, values in sorted(tags.items())}
        found["shapes"] = {}
        for registry in SHAPED:
            prefix = f"data/minecraft/{registry}/"
            files = [json.loads(archive.read(name)) for name in names if name.startswith(prefix)]
            types = {}
            for file in files:
                for field, value in file.items():
                    types.setdefault(field, set()).add(type(value).__name__)
            found["shapes"][registry] = {"required": sorted(set.intersection(*map(set, files)) - OPTIONAL.get(registry, set())), "known": sorted(set.union(*map(set, files))),
                                         "types": {field: sorted(seen) for field, seen in sorted(types.items())}}
    target = pathlib.Path(__file__).resolve().parent.parent / "broker" / "gates" / "vanilla_ids.json"
    target.write_text(json.dumps(found, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target}: {target.stat().st_size} bytes")


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
