"""A generated list of everything that's been built, so a builder doesn't have to read every feature to fit in with
them, and the director and tuner can see what exists and what its numbers are.
"""
import json

from orchestrator import progression as graph

STAGE_ORDER = {stage: index for index, stage in enumerate(graph.STAGES)}


def _describe_item(item):
    parts = [f'"{item.get("display", "?")}"']
    if item.get("tier"):
        parts.append(f"tier {item['tier']}")
    if item.get("stats"):
        parts.append(json.dumps(item["stats"]))
    components = item.get("components") or {}
    food = components.get("minecraft:food")
    if food:
        parts.append(f"food {food.get('nutrition')}/{food.get('saturation')}")
    if "minecraft:tool" in components:
        parts.append("tool")
    if "minecraft:max_damage" in components:
        parts.append(f"durability {components['minecraft:max_damage']}")
    if item.get("places"):
        parts.append(f"plants {item['places'].get('block')}")
    if item.get("retired"):
        parts.append("retired")
    return ", ".join(parts)


def _describe_block(block):
    parts = [f'"{block.get("display", "?")}"', str(block.get("family"))]
    if block.get("tool_level"):
        parts.append(f"needs {block['tool_level']} tool")
    if block.get("drops"):
        parts.append(f"drops {block['drops'].get('item')} x{block['drops'].get('count', 1)}")
    return ", ".join(parts)


def _describe_recipe(recipe):
    if isinstance(recipe.get("machine"), str):
        made = recipe.get("output", {}).get("item")
        used = [slot.get("item") for slot in recipe.get("inputs", [])]
        where = f"at {recipe['machine']}"
    else:
        body = recipe.get("json", {})
        result = body.get("result", {})
        made = result.get("id") if isinstance(result, dict) else result
        key = body.get("key") or {}
        used = list(key.values()) or body.get("ingredients") or [body.get("ingredient")]
        where = str(body.get("type", "")).removeprefix("minecraft:")
    return f"{made} from {used} ({where}, {recipe.get('mode')})"


def _describe_feature(feature_id, manifest, reached):
    lines = [f"### {feature_id}: {manifest.get('summary', '')}"]

    def mark(display):
        return " [players have this]" if display in reached else ""

    for name, block in manifest.get("blocks", {}).items():
        lines.append(f"- $block:{feature_id}/{name}: {_describe_block(block)}{mark(block.get('display'))}")
    for name, item in manifest.get("items", {}).items():
        lines.append(f"- $item:{feature_id}/{name}: {_describe_item(item)}{mark(item.get('display'))}")
    for name, mob in manifest.get("mobs", {}).items():
        numbers = {key: mob[key] for key in ("health", "damage", "speed") if key in mob}
        has_mind = ", has a mind" if mob.get("mind") else ""
        lines.append(f"- $mob:{feature_id}/{name}: \"{mob.get('display')}\", {mob.get('behaviour')}, {json.dumps(numbers)}{has_mind}{mark(mob.get('display'))}")
    for ore in manifest.get("ores", []):
        lines.append(f"- ore {ore.get('id')}: {ore.get('block')}, {ore.get('veinsPerChunk')} veins of {ore.get('veinSize')}, Y {ore.get('minY')} to {ore.get('maxY')}")
    for plant in manifest.get("plants", []):
        lines.append(f"- plant {plant.get('id')}: {plant.get('block')}, {plant.get('perChunk')} per chunk")
    for name in manifest.get("ruins", {}):
        lines.append(f"- ruin {feature_id}/{name}")
    for name in manifest.get("biomes", {}):
        lines.append(f"- biome {feature_id}/{name}")
    for name, recipe in manifest.get("recipes", {}).items():
        lines.append(f"- recipe {name}: {_describe_recipe(recipe)}")
    for name, entry in manifest.get("knowledge", {}).items():
        lines.append(f"- knowledge {feature_id}/{name}: \"{entry.get('title')}\", from {[route.get('type') for route in entry.get('routes', [])]}")
    for entry in manifest.get("automation", []):
        lines.append(f"- automates {entry.get('what')} at {entry.get('per_minute')} a minute")
    return lines


def reached_nodes(features_dir, reached):
    """The nodes where players already have something. Those parts of the graph stay as they are."""
    reached = set(reached)
    nodes = set()
    for path in features_dir.glob("*/feature.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        displays = {thing.get("display") for table in ("blocks", "items", "mobs") for thing in manifest.get(table, {}).values()}
        if manifest.get("node") and displays & reached:
            nodes.add(manifest["node"])
    return nodes


def build(features_dir, reached=()):
    """Everything so far, by where it sits in the progression. Reached names are how players know them."""
    doc = graph.read(features_dir.parent.parent.parent / "bible" / "progression.json")
    manifests = {}
    for path in sorted(features_dir.glob("*/feature.json")):
        manifests[path.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    reached = set(reached)
    lines = []
    placed = set()
    if doc:
        lines.append(f"Goal: {doc.get('goal')}\n")
        for node, info in sorted(doc["nodes"].items(), key=lambda pair: (STAGE_ORDER.get(pair[1].get("stage"), 9), pair[0])):
            lines.append(f"## {info.get('stage')}: {node}, \"{info.get('name', '')}\". Comes after: {', '.join(info.get('requires', [])) or 'nothing'}. "
                         f"Opens with: {info.get('opens_with') or 'nothing, it is open from the start'}.")
            inside = [feature_id for feature_id, manifest in manifests.items() if manifest.get("node") == node]
            placed.update(inside)
            if not inside:
                lines.append("Nothing built here yet.")
            for feature_id in inside:
                lines += _describe_feature(feature_id, manifests[feature_id], reached)
            lines.append("")
    others = [feature_id for feature_id in manifests if feature_id not in placed]
    if others:
        lines.append("## Not in the progression")
        for feature_id in others:
            lines += _describe_feature(feature_id, manifests[feature_id], reached)
    return "\n".join(lines) or "Nothing has been built yet."
