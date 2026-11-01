"""Things worth another look that don't stop a release, taken from what reviewers kept sending back.

Each attempt that goes back costs minutes of gates and review, so these get said in the instant check instead.
"""
from broker.gates import balance

# Building blocks are made to be placed, so nothing has to use them.
BUILDING_FAMILIES = {"stone", "wood", "soil", "glow", "metal", "cutout"}


def _used_anywhere(features, recipes):
    """Everything a recipe, seed, ruin or knowledge route mentions."""
    used = {node for recipe in recipes for alternatives, _ in recipe["inputs"] for node in alternatives}
    for feature_id, feature in features.items():
        text = str({key: value for key, value in feature["manifest"].items() if key not in ("recipes", "blocks", "items")})
        for table, kind in (("blocks", "block"), ("items", "item")):
            for name in feature["manifest"].get(table, {}):
                if f"${kind}:{name}" in text or f"${kind}:{feature_id}/{name}" in text:
                    used.add(f"{kind}:{feature_id}/{name}")
        for name, item in feature["manifest"].get("items", {}).items():
            if item.get("places"):
                used.add(f"item:{feature_id}/{name}")
    return used


def only_turns_into_vanilla(recipes):
    """Everything whose only recipes turn it into the game's own things. That isn't a use, because players had those already."""
    uses = {}
    for recipe in recipes:
        for alternatives, _ in recipe["inputs"]:
            for node in alternatives:
                if not balance._is_vanilla(node):
                    uses.setdefault(node, []).append(recipe)
    return {node for node, found in uses.items() if all(balance._is_vanilla(output[0]) for recipe in found for output in recipe["outputs"])}


def run(features):
    recipes = balance._read_recipes(features)
    used = _used_anywhere(features, recipes)
    back_to_vanilla = only_turns_into_vanilla(recipes)
    notes = []
    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        has_module = (feature["dir"] / "server" / "src").is_dir()
        # Ores and drops are the things found in the world on their way to something else.
        dropped = {drop["item"] for table in ("blocks", "mobs") for thing in manifest.get(table, {}).values() for drop in balance.drops_of(thing)}
        for name, item in manifest.get("items", {}).items():
            node = f"item:{feature_id}/{name}"
            components = item.get("components") or {}
            does_something = item.get("tier") or components or item.get("retired") or has_module
            if not does_something and node not in used:
                source = " It drops from something, but" if name in dropped else ""
                notes.append(f"{feature_id}/{name}:{source} nothing uses it yet, so players can't do anything with it.")
            elif node in back_to_vanilla and not components and not item.get("tier"):
                notes.append(f"{feature_id}/{name}: all its recipes turn it into vanilla things, which isn't a real use. Reviewers will send this back unless your module gives it one.")
            if "minecraft:food" in components and "minecraft:consumable" not in components:
                notes.append(f"{feature_id}/{name} has food values but no minecraft:consumable, so it can't be eaten.")
            if "minecraft:tool" in components:
                if not item.get("handheld"):
                    notes.append(f"{feature_id}/{name} is a tool but isn't \"handheld\", so it'll be held like an ingot.")
                if components.get("minecraft:max_stack_size") != 1:
                    notes.append(f"{feature_id}/{name} is a tool that stacks. Set minecraft:max_stack_size to 1.")
        for name, block in manifest.get("blocks", {}).items():
            family = block.get("family")
            if family == "machine" and not has_module:
                notes.append(f"{feature_id}/{name} is a machine, but this feature has no server module to make it do anything.")
            if family not in BUILDING_FAMILIES and family not in ("machine", "model") and block.get("tool") is None and "plant" not in str(family):
                notes.append(f"{feature_id}/{name} doesn't say which tool mines it, so it may drop nothing.")
        if has_module and not manifest.get("automation") and any(block.get("family") == "machine" for block in manifest.get("blocks", {}).values()):
            notes.append(f"{feature_id} has a machine. If it does anything by itself, declare it in \"automation\" with a per_minute rate.")
    return notes
