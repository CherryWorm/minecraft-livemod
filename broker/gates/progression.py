"""Does a release fit the world's progression? Early content leaves players doing the work themselves, later content
has to be earned with what came before, and what players already have stays as it is.

All of the numbers here are starting values, to be tuned in playtests.
"""
import hashlib
import json

from broker.gates import GateFailed, balance
from orchestrator import progression as graph

GATE = "progression"
# The strongest tier each stage may use. Vanilla's iron is about where a first set of gear belongs.
TIER_LIMIT = {"early": "iron", "mid": "beyond", "end": balance.UNLIMITED}
# Health and damage. Early is about a zombie or a spider, and mid about a ravager. The endgame has no ceiling, because
# things that need crazy gear to beat are the point of it.
MOB_LIMIT = {"early": (30, 6), "mid": (150, 15)}
# Per minute. Players are meant to keep going down mines and fighting, so mid-game mining is about a tenth of what a
# player with an iron pick manages, and killing is one mob a minute. Sorting and moving things can run at a hopper's pace.
MID_GAME_AUTOMATION = {"mining": 6, "mob_killing": 1, "crafting": 20, "machining": 20, "farming": 20, "sorting": 150, "transport": 150}
LATE_TIERS = {"diamond", "netherite", "beyond", balance.UNLIMITED}
# Long enough that it has to be a reason rather than a word.
MIN_REASON = 15


def _node_of(thing, features):
    """The progression node something belongs to, from its name like item:feature/name."""
    feature = features.get(thing.split(":", 1)[1].split("/")[0])
    return feature["manifest"].get("node") if feature else None


def _check_features(features, doc):
    problems = []
    for feature_id, feature in features.items():
        node = feature["manifest"].get("node")
        if not node:
            problems.append(f"{feature_id} has no \"node\". Say which step of bible/progression.json it belongs to.")
        elif node not in doc["nodes"]:
            problems.append(f"{feature_id} belongs to node {node!r}, which isn't in bible/progression.json.")
    return problems


def _check_recipes_follow_graph(features, doc, recipes):
    """Nothing may need something from later on or from a branch that doesn't lead here, or the graph would be a lie."""
    problems = []
    for recipe in recipes:
        feature_id = recipe["source"].split("/")[0]
        made = [_node_of(output, features) for output, _, _ in recipe["outputs"] if not balance._is_vanilla(output)]
        node = next((found for found in made if found), features[feature_id]["manifest"].get("node"))
        if node not in doc["nodes"]:
            continue
        allowed = graph.before(doc, node) | {node}
        for alternatives, _ in recipe["inputs"]:
            nodes = [_node_of(option, features) for option in alternatives if not balance._is_vanilla(option)]
            if any(balance._is_vanilla(option) for option in alternatives) or not nodes:
                continue
            if not any(found in allowed for found in nodes):
                problems.append(f"Recipe {recipe['source']} makes something in node {node}, but uses {alternatives[0].split(':', 1)[1]} "
                                f"from node {nodes[0]}, which doesn't come before {node}. Change the recipe, or use something earlier.")
    return problems


def _is_gated(recipe, node, doc, features, recipes_by_output, seen):
    """True if this recipe can't be made without something from a step right before this node. It has to be the step
    right before, or the endgame's strongest sword could be made of the first ore anyone found."""
    gates = doc["nodes"][node].get("requires", [])

    def material_gated(thing):
        if balance._is_vanilla(thing) or thing in seen:
            return False
        if _node_of(thing, features) in gates:
            return True
        made_by = recipes_by_output.get(thing, [])
        return bool(made_by) and all(_is_gated(other, node, doc, features, recipes_by_output, seen | {thing}) for other in made_by)

    return any(alternatives and all(material_gated(option) for option in alternatives) for alternatives, _ in recipe["inputs"])


def _check_gating(features, doc, recipes):
    """Tiered gear and machines past the first steps have to be paid for with what came before, like vanilla's own tech."""
    things = balance._things(features)
    recipes_by_output = {}
    for recipe in recipes:
        for output, _, _ in recipe["outputs"]:
            recipes_by_output.setdefault(output, []).append(recipe)
    problems = []
    for thing, definition in things.items():
        node = _node_of(thing, features)
        if node not in doc["nodes"] or not doc["nodes"][node].get("requires") or definition.get("retired"):
            continue
        if definition.get("tier") is None and definition.get("family") not in ("machine", "model"):
            continue
        for recipe in recipes_by_output.get(thing, []):
            if not _is_gated(recipe, node, doc, features, recipes_by_output, {thing}):
                needs = ", ".join(sorted(doc["nodes"][node]["requires"]))
                problems.append(f"Recipe {recipe['source']} makes {thing.split(':', 1)[1]} in node {node} without needing anything from "
                                f"the step right before it ({needs}), so nothing gates it. Add a material from one of those.")
    return problems


def _check_tiers(features, doc, recipes):
    problems = []
    limit_of = lambda node: TIER_LIMIT[doc["nodes"][node]["stage"]]  # noqa: E731

    def check(label, tier, node):
        if tier in balance.TIERS and node in doc["nodes"] and balance.TIERS.index(tier) > balance.TIERS.index(limit_of(node)):
            stage = doc["nodes"][node]["stage"]
            problems.append(f"{label} is tier {tier}, but node {node} is {stage} game, where the strongest allowed is {limit_of(node)}.")

    for thing, definition in balance._things(features).items():
        check(thing.split(":", 1)[1], definition.get("tier"), _node_of(thing, features))
    for recipe in recipes:
        check(f"Recipe {recipe['source']}", recipe["tier"], features[recipe["source"].split("/")[0]]["manifest"].get("node"))
    return problems


def _check_mobs(features, doc):
    problems = []
    for feature_id, feature in features.items():
        node = feature["manifest"].get("node")
        limit = MOB_LIMIT.get(doc["nodes"][node]["stage"]) if node in doc["nodes"] else None
        for name, mob in feature["manifest"].get("mobs", {}).items():
            if limit and (mob.get("health", 0) > limit[0] or mob.get("damage", 0) > limit[1]):
                stage = doc["nodes"][node]["stage"]
                problems.append(f"Mob {feature_id}/{name} has {mob.get('health', 0)} health and {mob.get('damage', 0)} damage, over the "
                                f"{stage} game's limit of {limit[0]} and {limit[1]}. Weaken it, or move it to a later node.")
    return problems


def _check_automation(features, doc):
    """What a machine does by itself has to be declared. Players should still have to go and do things early on."""
    problems = []
    for feature_id, feature in features.items():
        node = feature["manifest"].get("node")
        if node not in doc["nodes"]:
            continue
        stage = doc["nodes"][node]["stage"]
        for entry in feature["manifest"].get("automation", []):
            what, rate = entry.get("what"), entry.get("per_minute")
            if what not in MID_GAME_AUTOMATION:
                problems.append(f"{feature_id} automates {what!r}. Say which of {', '.join(sorted(MID_GAME_AUTOMATION))} it is.")
            elif not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
                problems.append(f"{feature_id} automates {what}, so it needs a per_minute rate.")
            elif stage == "early":
                problems.append(f"{feature_id} automates {what} in the early game, where players still do this themselves. "
                                "Make it a help to a player who's there, or move it to a mid-game node.")
            elif stage == "mid" and rate > MID_GAME_AUTOMATION[what]:
                problems.append(f"{feature_id} automates {what} at {rate} a minute, over the mid game's limit of "
                                f"{MID_GAME_AUTOMATION[what]}. Players should still have to go and do this. Slow it down, or move it to the endgame.")
    return problems


def _check_minds(features, doc):
    """A mob can't hand out or teach its way around the progression, so what it gives has to be what its own step has earned."""
    problems = []
    for feature_id, feature in features.items():
        node = feature["manifest"].get("node")
        if node not in doc["nodes"]:
            continue
        allowed = graph.before(doc, node) | {node}
        for name, mob in feature["manifest"].get("mobs", {}).items():
            for item in (mob.get("mind") or {}).get("stash", []):
                found = balance._node(item.get("item", ""), feature_id)
                if not balance._is_vanilla(found) and _node_of(found, features) not in allowed:
                    problems.append(f"Mob {feature_id}/{name} can hand out {found.split(':', 1)[1]}, from node {_node_of(found, features)}, which doesn't come before {node}.")
    return problems


def _check_knowledge_follows_graph(features, doc):
    """A route can need something from anywhere, like a late way of learning something early. But if every route to an
    entry needs something from later on, then what it unlocks is really later on too, and the graph would be a lie."""
    problems = []
    for feature_id, feature in features.items():
        node = feature["manifest"].get("node")
        if node not in doc["nodes"]:
            continue
        allowed = graph.before(doc, node) | {node}
        for name, entry in feature["manifest"].get("knowledge", {}).items():
            needs = [[balance._key(feature_id, need) for need in route.get("requires", [])] for route in entry.get("routes", [])]
            if needs and all(any(features.get(need.split("/")[0], {"manifest": {}})["manifest"].get("node") not in allowed for need in route) for route in needs):
                problems.append(f"Knowledge {feature_id}/{name} is in node {node}, but every route to it requires something from a node that doesn't come before that. "
                                "Give it a route that can be taken from here, or require something earlier.")
    return problems


def _mythic_without_a_place(features, recipes):
    """Unlimited power is only fair at the end of a progression, so it can't exist in a world without one."""
    tiers = [thing.get("tier") for thing in balance._things(features).values()] + [recipe["tier"] for recipe in recipes]
    return ["Tier mythic needs an endgame node, but this world has no bible/progression.json."] if balance.UNLIMITED in tiers else []


# What players already have


def snapshot(features):
    """A fingerprint of each thing a player could hold: what it is, what makes it, where it comes from and its art."""
    recipes = balance._read_recipes(features)
    prints = {}
    tables = [("block", "blocks"), ("item", "items"), ("mob", "mobs")]
    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        for kind, table in tables:
            for name, definition in manifest.get(table, {}).items():
                digest = hashlib.sha256(json.dumps(definition, sort_keys=True).encode())
                node = f"{kind}:{feature_id}/{name}"
                for recipe in recipes:
                    if any(output == node for output, _, _ in recipe["outputs"]):
                        owner, recipe_name = recipe["source"].split("/")
                        digest.update(json.dumps(features[owner]["manifest"]["recipes"][recipe_name], sort_keys=True).encode())
                for entry in [*manifest.get("ores", []), *manifest.get("plants", [])]:
                    if entry.get("block") == name:
                        digest.update(json.dumps(entry, sort_keys=True).encode())
                assets = feature["dir"] / "assets"
                art = [assets / "textures" / f"{texture}.png" for texture in [definition.get("texture", name), *definition.get("faces", {}).values()]]
                art += [assets / "models" / f"{model}.bbmodel" for model in [definition.get("model")] if isinstance(model, str)]
                for path in art:
                    if path.exists():
                        digest.update(path.read_bytes())
                prints[f"{feature_id}/{name}"] = digest.hexdigest()
    return prints


def reached_slots(knowledge_file):
    """Everything anyone has ever held or killed, on or offline. It's a ledger the game keeps, so it only ever grows."""
    if not knowledge_file.exists():
        return set()
    found = json.loads(knowledge_file.read_text(encoding="utf-8")).get("found", {})
    return {thing for things in found.values() for thing in things}


def _check_reached(features, ledger, old_prints, reached, new_prints):
    """Things players already have stay as they are, unless there's a reason that a reviewer can then weigh up."""
    names = {f"gm:{entry['slot']}": key for table in ("blocks", "items", "mobs") for key, entry in ledger.get(table, {}).items()}
    problems = []
    for slot in sorted(reached):
        key = names.get(slot)
        if not key or key not in old_prints or old_prints[key] == new_prints.get(key):
            continue
        feature_id, name = key.split("/")
        reason = features.get(feature_id, {"manifest": {}})["manifest"].get("changes_reached", {}).get(name, "")
        if len(str(reason).strip()) < MIN_REASON:
            problems.append(f"Players already have {key}, and this release changes it. What players have is left alone unless there's a "
                            f"clear reason or feedback. Undo the change, or give the reason in feature.json as \"changes_reached\": "
                            f"{{\"{name}\": \"why\"}}.")
    return problems


def run(features, bible, ledger, old_prints, knowledge_file, new_prints):
    recipes = balance._read_recipes(features)
    doc = graph.read(bible / "progression.json")
    problems = _check_reached(features, ledger, old_prints, reached_slots(knowledge_file), new_prints)
    if doc is None:
        problems += _mythic_without_a_place(features, recipes)
    else:
        found = graph.problems(doc)
        if found:
            raise GateFailed(GATE, "bible/progression.json has problems:\n" + "\n".join(found))
        problems += (_check_features(features, doc) + _check_recipes_follow_graph(features, doc, recipes)
                     + _check_gating(features, doc, recipes) + _check_tiers(features, doc, recipes)
                     + _check_mobs(features, doc) + _check_automation(features, doc) + _check_minds(features, doc)
                     + _check_knowledge_follows_graph(features, doc))
    if problems:
        raise GateFailed(GATE, "\n".join(problems))
