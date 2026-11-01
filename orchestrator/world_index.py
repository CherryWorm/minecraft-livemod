"""A generated list of everything that's been built, so a builder doesn't have to read every feature to fit in with
them, and the director and tuner can see what exists and what its numbers are.
"""
import json
import re

from orchestrator import progression as graph

STAGE_ORDER = {stage: index for index, stage in enumerate(graph.STAGES)}
REFERENCE = re.compile(r"\$(?:block|item|mob):(?:(\w+)/)?(\w+)")
INDEX_DESCRIPTION = 200  # Enough to tell what something is, and the rest comes from its entry.
ENTRY_LIMIT = 12000
PLANS = re.compile(r"\b(later|future|upcoming|eventually|not yet|next stage|coming)\b", re.I)
A_PART = re.compile(r",? part \d+( of [^:.]+)?", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


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


def _guide_recipe(recipe, say):
    if isinstance(recipe.get("machine"), str):
        made = say(recipe.get("output", {}).get("item"))
        if recipe.get("mode") == "guessable":
            return f"{made}: worked out by experimenting at {say(recipe['machine'])}, which reacts to a near miss"
        how = f"made at {say(recipe['machine'])} from {', '.join(say(slot.get('item')) for slot in recipe.get('inputs', []))}"
    else:
        body = recipe.get("json", {})
        result = body.get("result", {})
        made = say(result.get("id") if isinstance(result, dict) else result)
        kind = str(body.get("type", "")).removeprefix("minecraft:").replace("_", " ")
        if body.get("key"):
            used = ", ".join(f"{letter} is {say(item)}" for letter, item in body["key"].items())
            how = f"{kind}, pattern {' / '.join(body.get('pattern', []))}, where {used}"
        else:
            how = f"{kind} from {', '.join(say(item) for item in body.get('ingredients') or [body.get('ingredient')])}"
    return f"{made}: {how}" + (", once it's been learned" if recipe.get("mode") == "known" else "")


def _without_plans(summary, not_out):
    """Summaries are written for builders, and can mention what's still to come. Those sentences are left out altogether,
    because not showing a model something is stronger than telling it not to repeat it."""
    node = re.compile(r"\b(" + "|".join(map(re.escape, sorted(not_out))) + r")\b") if not_out else None
    return " ".join(sentence for sentence in SENTENCE.split(A_PART.sub("", summary))
                    if not PLANS.search(sentence) and not (node and node.search(sentence)))


def _guide_feature(manifest, say, not_out):
    lines = [f"### {_without_plans(say(manifest.get('summary', '')), not_out)}"]

    def block_name(block):
        return say(block if "$" in str(block) or ":" in str(block) else f"$block:{block}")

    def places(thing):
        where = [f"Y {thing['minY']} to {thing['maxY']}"] if "minY" in thing else []
        if thing.get("underground"):
            where.append("underground")
        if thing.get("biomes"):
            where.append("only in " + ", ".join(say(biome) for biome in thing["biomes"]))
        return ", ".join(where) or "anywhere"

    for ore in manifest.get("ores", []):
        lines.append(f"- {block_name(ore.get('block'))}: ore veins, {places(ore)}, in {', '.join(say(block) for block in ore.get('replaces', []))}")
    for name, block in manifest.get("blocks", {}).items():
        facts = [f"needs {block['tool_level']} tool or better"] if block.get("tool_level") else []
        if block.get("drops"):
            facts.append(f"drops {say(block['drops'].get('item'))}")
        if facts:
            lines.append(f"- {block.get('display', name)}: {', '.join(facts)}")
    for name, mob in manifest.get("mobs", {}).items():
        drops = f", drops {say(mob['drops'].get('item'))}" if mob.get("drops") else ""
        lines.append(f"- {mob.get('display', name)}: {mob.get('behaviour')} creature, {places(mob.get('spawn') or {})}{drops}")
    for plant in manifest.get("plants", []):
        lines.append(f"- {block_name(plant.get('block'))}: grows {places(plant)}")
    for name, ruin in manifest.get("ruins", {}).items():
        side = "underground" if ruin.get("underground") else "on the surface"
        chance = f", about one chunk in {round(1 / ruin['chance'])}" if ruin.get("chance") else ""
        loot = [say(entry.get("name")) for pool in (ruin.get("loot") or {}).get("pools", []) for entry in pool.get("entries", []) if entry.get("name")]
        holds = f", its chest can hold {', '.join(dict.fromkeys(loot))}" if loot else ""
        lines.append(f"- site {name.replace('_', ' ')}: {side}, {places({**ruin, 'underground': False})}{chance}{holds}")
    for name in manifest.get("biomes", {}):
        lines.append(f"- biome {name.replace('_', ' ')}")
    for recipe in manifest.get("recipes", {}).values():
        lines.append(f"- recipe for {_guide_recipe(recipe, say)}")
    for name, entry in manifest.get("knowledge", {}).items():
        routes = " or ".join(f"{route.get('type')} {say(route.get('id', ''))}".strip() for route in entry.get("routes", []))
        lines.append(f"- to learn \"{entry.get('title', name)}\": {routes}. It reads: {say(entry.get('text', ''))}")
    return lines


def _readable(features_dir):
    """What's out, a way to say things in the names players see, and the parts of the graph that nothing's out for yet.
    Only what's been released is ever merged into main, so nothing still being built can reach anyone through here."""
    manifests = {path.parent.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(features_dir.glob("*/feature.json"))}
    names = {(feature_id, name): thing["display"] for feature_id, manifest in manifests.items()
             for table in ("blocks", "items", "mobs") for name, thing in manifest.get(table, {}).items() if thing.get("display")}

    def saying(feature_id):
        def say(value):
            text = REFERENCE.sub(lambda found: names.get((found.group(1) or feature_id, found.group(2)), found.group(2).replace("_", " ")), str(value))
            return re.sub(r"#?minecraft:(\w+)", lambda found: found.group(1).replace("_", " "), text)
        return say

    bible = features_dir.parent.parent.parent / "bible" / "progression.json"
    nodes = json.loads(bible.read_text(encoding="utf-8")).get("nodes", {}) if bible.exists() else {}
    return manifests, saying, set(nodes) - {manifest.get("node") for manifest in manifests.values()}


def _shown_names(manifest):
    shown = [thing["display"] for table in ("blocks", "items", "mobs") for thing in manifest.get(table, {}).values() if thing.get("display")]
    return shown + [name.replace("_", " ") for table in ("biomes", "ruins") for name in manifest.get(table, {})]


def player_index(features_dir):
    """A line for everything that's out, for the voices that help players. It's never cut short, because what isn't here
    doesn't exist as far as they're concerned, and it stays small because the detail is in player_entry."""
    manifests, saying, not_out = _readable(features_dir)
    lines = []
    for feature_id, manifest in manifests.items():
        description = SENTENCE.split(_without_plans(saying(feature_id)(manifest.get("summary", "")), not_out))[0]
        if len(description) > INDEX_DESCRIPTION:
            description = description[:INDEX_DESCRIPTION].rsplit(" ", 1)[0] + "..."
        shown = _shown_names(manifest)
        lines.append(f"- {feature_id}: {description}" + (f" ({', '.join(shown)})" if shown else ""))
    return "\n".join(lines) or "Nothing yet."


def player_entry(features_dir, wanted):
    """The whole entry for one thing, by its id or a name players see. What's wanted comes from a model, so it's only ever
    compared with what's there."""
    manifests, saying, not_out = _readable(features_dir)
    key = str(wanted).strip().lower()
    found = key if key in manifests else next((feature_id for feature_id, manifest in manifests.items()
                                               if key in (name.lower() for name in _shown_names(manifest))), None)
    if found is None:
        return "There's nothing by that name. Use an id from the guide."
    return "\n".join(_guide_feature(manifests[found], saying(found), not_out))[:ENTRY_LIMIT]


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
