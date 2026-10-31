"""Is the content balanced? Measures what a feature claims, and what its recipes really make, against
vanilla's own numbers, so nothing ships overpowered because it was described well.

Every vanilla number here was read from the 26.3 game jar (ToolMaterial, Items, ArmorMaterials, ArmorType,
OreFeatures and the placed_feature data). Check them again when versions.env moves to a new Minecraft.
"""
import itertools
import json
import math
from collections import Counter
from fractions import Fraction

from broker.bundles import TOKEN
from broker.gates import GateFailed

GATE = "balance"
TIERS = ("wood", "stone", "iron", "diamond", "netherite", "beyond")
MARGIN = 1.1
# beyond has no vanilla curve, so it's measured from netherite. 150% is the highest multiplier at which a
# full armor set (20 points) still lands exactly on the game's cap of 30, so no number is wasted, and it's
# as big a step as vanilla's largest between tiers (netherite's toughness over diamond's).
BEYOND_MARGIN = 1.5

# Tier: tool durability, mining speed, hardest single hit (the axe), sword hit.
TOOLS = {
    "wood": (59, 2.0, 7, 4),
    "stone": (131, 4.0, 9, 5),
    "iron": (250, 6.0, 9, 6),
    "diamond": (1561, 8.0, 9, 7),
    "netherite": (2031, 9.0, 10, 8),
}
# Axes hit harder and swords hit faster, so a tool is held to both: the axe's hit and the sword's damage
# per second. Otherwise an axe's damage at a sword's speed would pass, and that's stronger than either.
SWORD_SPEED = 1.6
# With no attack_speed modifier a player swings at this base rate, so leaving it out is a huge buff.
BASE_ATTACK_SPEED = 4.0
BASE_ATTACK_DAMAGE = 1.0
# Tier: durability factor, armor points by slot, toughness, knockback resistance. Vanilla armor has no wood
# or stone, so those tiers use what's made at that stage: leather and chainmail.
SLOTS = ("head", "chest", "legs", "feet", "body")
ARMOR = {
    "wood": (5, (1, 3, 2, 1, 3), 0, 0),
    "stone": (15, (2, 5, 4, 1, 4), 0, 0),
    "iron": (15, (2, 6, 5, 2, 5), 0, 0),
    "diamond": (33, (3, 8, 6, 3, 11), 2, 0),
    "netherite": (37, (3, 8, 6, 3, 19), 3, 0.1),
}
ARMOR_DURABILITY = (11, 16, 15, 13, 16)
# Tier: hardness and blast resistance of the matching block (planks, stone, then the metal blocks).
BLOCKS = {"wood": (2.0, 3.0), "stone": (1.5, 6.0), "iron": (5.0, 6.0), "diamond": (5.0, 6.0), "netherite": (50.0, 1200.0)}

WEAPON_STATS = ("attack_damage", "attack_speed")
ARMOR_STATS = ("armor", "armor_toughness", "knockback_resistance")
STATS = {"durability", "mining_speed", "hardness", "blast_resistance", *WEAPON_STATS, *ARMOR_STATS}
# Components with real power and no vanilla curve to hold them to. Passing them would let an item carry
# any strength at all past the budget, so they stay out until there's a way to measure them.
UNMEASURED = {"enchantments", "stored_enchantments", "death_protection", "blocks_attacks", "kinetic_weapon",
              "piercing_weapon", "attack_range", "minimum_attack_charge", "damage_type", "glider"}
# Vanilla swords really do carry these. They only apply to a few soft blocks, so they aren't mining power.
SPECIAL_MINING_RULES = {"minecraft:cobweb", "#minecraft:sword_instantly_mines"}

# Mod ores only generate in the overworld (OrePatchQueue), and most of what's above sea level is air, so
# only this band counts. Vanilla's upper coal and iron fall outside it: they're for mountains.
ROCK = (-64, 64)
# Which vanilla ore each tier leans on, as veins per chunk, vein size and Y range. Coal is what you mine with
# wood, and copper is the first thing stone tools open up. Large copper is left out: it's dripstone caves only.
_VANILLA_ORES = {
    "wood": [(20, 17, 0, 192), (30, 17, 136, 320)],
    "stone": [(16, 10, -16, 112)],
    "iron": [(10, 9, -24, 56), (10, 4, -64, 72), (90, 9, 80, 384)],
    "diamond": [(7, 4, -144, 16), (2, 8, -64, -4), (1 / 9, 12, -144, 16), (4, 8, -144, 16)],
}
# Twice or half vanilla's rate. Iron and diamond differ by 2.7 times on this measure, so this keeps every tier's
# ceiling under the next commoner tier's normal rate. The measure itself is rough, since veins overlap and
# hit air, so a tighter limit would be failing ores on noise. Beyond 2x a tier's pacing visibly changes.
ORE_TOLERANCE = 2.0
# More than this many input combinations can only be an attempt to get past the cycle check.
MAX_VARIANTS = 256
# Vanilla's own reversible recipes. Neutral alone, but a feature could close a loop through them.
_VANILLA_STORAGE = [("iron_nugget", "iron_ingot"), ("gold_nugget", "gold_ingot"), ("copper_nugget", "copper_ingot"),
                    ("iron_ingot", "iron_block"), ("gold_ingot", "gold_block"), ("copper_ingot", "copper_block"),
                    ("netherite_ingot", "netherite_block"), ("diamond", "diamond_block"), ("emerald", "emerald_block"),
                    ("lapis_lazuli", "lapis_block"), ("coal", "coal_block"), ("redstone", "redstone_block"),
                    ("raw_iron", "raw_iron_block"), ("raw_gold", "raw_gold_block"), ("raw_copper", "raw_copper_block")]


def _rock_fraction(low, high):
    """The share of a vein's possible heights that are inside rock. Heights are picked evenly, so the rest is lost."""
    span = high - low + 1
    overlap = min(high, ROCK[1]) - max(low, ROCK[0]) + 1
    return max(0, overlap) / span if span > 0 else 0


def _expected(veins, size, low, high):
    return veins * size * _rock_fraction(low, high)


ORE_CURVE = {tier: sum(_expected(*ore) for ore in ores) for tier, ores in _VANILLA_ORES.items()}
# Ancient debris: one vein of 3 and one of 2 per chunk, all of it inside the Nether's rock. Nothing in vanilla
# sits above it, so beyond is set at half, to stay rarer than the rarest thing players already know.
ORE_CURVE.update(netherite=5.0, beyond=2.5)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _key(feature_id, name):
    return name if "/" in name else f"{feature_id}/{name}"


def _node(token, feature_id):
    match = TOKEN.fullmatch(token)
    return f"{match.group(1)}:{_key(feature_id, match.group(2))}" if match else token


def _is_vanilla(node):
    return node.startswith(("minecraft:", "#minecraft:"))


def _things(features):
    """Everything features declare, by the node name recipes refer to it with."""
    things = {}
    for feature_id, feature in features.items():
        for kind, table in (("block", "blocks"), ("item", "items")):
            for name, thing in feature["manifest"].get(table, {}).items():
                things[f"{kind}:{feature_id}/{name}"] = thing
    return things


def _alternatives(ingredient, feature_id):
    """An ingredient is a name, a #tag, a list meaning any of these, or the older {"item": ...} or {"tag": ...}."""
    if isinstance(ingredient, str):
        return [_node(ingredient, feature_id)] if ":" in ingredient else []
    if isinstance(ingredient, list):
        return [node for option in ingredient for node in _alternatives(option, feature_id)]
    if isinstance(ingredient, dict):
        if "tag" in ingredient:
            return [f"#{ingredient['tag']}"]
        for field in ("item", "id", "ingredient", "items"):
            if field in ingredient:
                return _alternatives(ingredient[field], feature_id)
    return []


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 1


# Fields in a recipe that aren't things going in. Anything else with a name in it counts as an input, so a
# machine recipe's own format can't hide what it consumes.
_NOT_INPUTS = {"type", "category", "group", "pattern", "key", "result", "results", "cookingtime", "experience",
               "show_notification", "feedback", "sound"}


def _inputs(body, feature_id):
    """Returns (alternatives, count) for each slot, so 8 of something in a shaped recipe counts as 8."""
    slots = []
    if isinstance(body.get("key"), dict):
        used = Counter(char for row in body.get("pattern", []) for char in row if char != " ")
        slots += [(_alternatives(body["key"].get(char), feature_id), count) for char, count in used.items()]
    for field, value in body.items():
        if field in _NOT_INPUTS:
            continue
        # A list under a plural name is many slots. A list under a singular name is one slot with options.
        for slot in value if field.endswith("s") and isinstance(value, list) else [value]:
            count = _count(slot.get("count")) if isinstance(slot, dict) and "count" in slot else 1
            slots.append((_alternatives(slot, feature_id), count))
    return [slot for slot in slots if slot[0]]


def _outputs(body, feature_id):
    """Returns (node, count, components) for what a recipe makes."""
    results = body.get("results", body.get("result", []))
    outputs = []
    for result in results if isinstance(results, list) else [results]:
        if isinstance(result, str):
            outputs.append((_node(result, feature_id), 1, {}))
        elif isinstance(result, dict) and isinstance(result.get("id", result.get("item")), str):
            components = result.get("components")
            outputs.append((_node(result.get("id", result.get("item")), feature_id),
                            _count(result.get("count", 1)), components if isinstance(components, dict) else {}))
    return outputs


def _read_recipes(features):
    recipes = []
    for feature_id, feature in features.items():
        for name, recipe in feature["manifest"].get("recipes", {}).items():
            # A named machine's recipe has its inputs and output at the top level, not in Minecraft's own json.
            is_machine = isinstance(recipe.get("machine"), str)
            body = {"inputs": recipe.get("inputs", []), "results": [recipe.get("output")]} if is_machine else recipe.get("json", {})
            recipes.append({"source": f"{feature_id}/{name}", "tier": recipe.get("tier"),
                            "inputs": _inputs(body, feature_id), "outputs": _outputs(body, feature_id)})
    return recipes


# Power budget


def _limits(tier, slot, armored):
    """The most each stat may be at this tier, with the allowance already applied."""
    base, margin = ("netherite", BEYOND_MARGIN) if tier == "beyond" else (tier, MARGIN)
    durability, speed, axe_hit, sword_hit = TOOLS[base]
    factor, points, toughness, knockback = ARMOR[base]
    hardness, blast = BLOCKS[base]
    # With no slot named, the chest is the strongest piece, so that's the fair ceiling.
    index = SLOTS.index(slot) if slot in SLOTS else 1
    numbers = {"durability": factor * ARMOR_DURABILITY[index] if armored else durability, "mining_speed": speed,
               "attack_damage": axe_hit, "damage_per_second": sword_hit * SWORD_SPEED, "armor": points[index],
               "armor_toughness": toughness, "knockback_resistance": knockback, "hardness": hardness, "blast_resistance": blast}
    return {stat: number * margin for stat, number in numbers.items()}


def _over_budget(label, tier, claim):
    if tier not in TIERS:
        return [f"{label} declares tier {tier!r}, but a tier must be one of {', '.join(TIERS)}."]
    stats = {stat: value for stat, value in claim.items() if stat != "slot"}
    if any(stat in stats for stat in WEAPON_STATS):
        stats["damage_per_second"] = (stats.get("attack_damage", BASE_ATTACK_DAMAGE)
                                      * stats.get("attack_speed", BASE_ATTACK_SPEED))
    armored = "slot" in claim or any(stat in stats for stat in ARMOR_STATS)
    limits = _limits(tier, claim.get("slot"), armored)
    problems = []
    for stat, value in sorted(stats.items()):
        # Written this way round so NaN, which compares false with everything, fails instead of passing.
        if stat in limits and not value <= limits[stat] + 1e-9:
            hint = {"damage_per_second": " That's attack_damage times attack_speed, and attack_speed is "
                                         f"{BASE_ATTACK_SPEED:g} when it isn't set, so set it."}.get(stat, "")
            problems.append(f"{label} (tier {tier}) has {stat} {value:g}, over its limit of {limits[stat]:g}.{hint} "
                            "Lower it, or use a higher tier if it's meant to be late-game.")
    return problems


def _from_stats(label, thing):
    """Reads a thing's declared numbers."""
    stats = thing.get("stats")
    if not stats:
        return {}, []
    if not isinstance(stats, dict):
        return {}, [f"{label}: stats must be an object of names and numbers."]
    claim, problems = {}, []
    for stat, value in stats.items():
        if stat == "slot":
            if value not in SLOTS:
                problems.append(f"{label}: slot must be one of {', '.join(SLOTS)}, found {value!r}.")
            claim["slot"] = value
        elif stat not in STATS:
            problems.append(f"{label} declares {stat}, which has no vanilla curve to check it against. "
                            f"Use only {', '.join(sorted(STATS))}.")
        elif not _is_number(value):
            problems.append(f"{label}: {stat} must be a number, found {value!r}.")
        else:
            claim[stat] = value
    return claim, problems


def _read_tool(tool):
    """The fastest this mines."""
    rules = tool.get("rules", [])
    speeds = [tool.get("default_mining_speed", 1.0)]
    for rule in rules if isinstance(rules, list) else []:
        blocks = rule.get("blocks")
        special = {blocks} <= SPECIAL_MINING_RULES if isinstance(blocks, str) else set(blocks or ["?"]) <= SPECIAL_MINING_RULES
        if "speed" in rule and not special:
            speeds.append(rule["speed"])
    return max(speeds) if all(_is_number(speed) for speed in speeds) else math.nan


def _read_modifiers(modifiers, label, claim, problems):
    """Adds up attribute modifiers. Only add_value is measurable, because a multiplier's size depends on other gear."""
    if isinstance(modifiers, dict):
        modifiers = modifiers.get("modifiers", [])
    totals = {}
    for modifier in modifiers if isinstance(modifiers, list) else []:
        kind = str(modifier.get("type", "")).removeprefix("minecraft:").removeprefix("generic.")
        amount = modifier.get("amount", 0)
        slot = modifier.get("slot", "any")
        if not _is_number(amount):
            problems.append(f"{label} has a {kind} modifier whose amount isn't a number: {amount!r}.")
        elif kind not in WEAPON_STATS + ARMOR_STATS:
            # Drawbacks are free, and vanilla gear gives none of the other attributes, so no curve allows them.
            if amount > 0:
                problems.append(f"{label} raises {kind}, which has no vanilla curve, so it can't be budgeted. "
                                "Remove it, or give the effect through a server module.")
        elif modifier.get("operation", "add_value") != "add_value" and amount > 0:
            problems.append(f"{label} changes {kind} with {modifier.get('operation')}. Use add_value, "
                            "because a multiplier's strength depends on the rest of a player's gear.")
        else:
            # Worn weapon stats, or armor stats held in hand, would stack with the real thing and beat any budget.
            if amount > 0 and kind in WEAPON_STATS and slot != "mainhand":
                problems.append(f"{label} gives {kind} in slot {slot}. It must be mainhand, or it stacks with a real weapon.")
            if amount > 0 and kind in ARMOR_STATS and slot not in (*SLOTS, "armor"):
                problems.append(f"{label} gives {kind} in slot {slot}. It must be an armor slot, or it stacks with worn armor.")
            if slot in SLOTS:
                claim["slot"] = slot
            totals[kind] = totals.get(kind, 0) + amount
    for kind, amount in totals.items():
        base = {"attack_damage": BASE_ATTACK_DAMAGE, "attack_speed": BASE_ATTACK_SPEED}.get(kind, 0)
        claim[kind] = base + amount


def _from_components(label, components):
    """What a recipe's result really does, read the way the game reads it. Names work without "minecraft:" too."""
    parts = {str(name).removeprefix("minecraft:"): value for name, value in components.items()}
    claim, problems = {}, []
    for name in sorted(parts.keys() & UNMEASURED):
        problems.append(f"{label} sets {name}, which adds power with no vanilla curve to check it against. "
                        "Remove it. Players can enchant things themselves, and a server module can do the rest.")
    if "max_damage" in parts:
        claim["durability"] = parts["max_damage"] if _is_number(parts["max_damage"]) else math.nan
    tool = parts.get("tool")
    if isinstance(tool, dict):
        claim["mining_speed"] = _read_tool(tool)
    weapon = parts.get("weapon")
    # Never wearing out is infinite durability, however it's arranged, and no tier allows that.
    if ("unbreakable" in parts or (isinstance(tool, dict) and tool.get("damage_per_block", 1) == 0)
            or (isinstance(weapon, dict) and weapon.get("item_damage_per_attack", 1) == 0)):
        claim["durability"] = math.inf
    if "attribute_modifiers" in parts:
        _read_modifiers(parts["attribute_modifiers"], label, claim, problems)
    equippable = parts.get("equippable")
    if isinstance(equippable, dict) and equippable.get("slot") in SLOTS:
        claim["slot"] = equippable["slot"]
    return claim, problems


def check_power(features, recipes):
    """Anything with combat or tool numbers must declare a tier and stay within that tier's curve."""
    things = _things(features)
    problems = []
    for node, thing in things.items():
        label = node.split(":", 1)[1]
        claim, found = _from_stats(label, thing)
        problems += found
        tier = thing.get("tier")
        if tier is None:
            if any(stat != "slot" for stat in claim):
                problems.append(f"{label} has stats but no tier. Add \"tier\": one of {', '.join(TIERS)}.")
        else:
            problems += _over_budget(label, tier, claim)
    for recipe in recipes:
        for node, _, components in recipe["outputs"]:
            label = f"Recipe {recipe['source']} makes {node.split(':', 1)[-1] if node in things else node}, which"
            claim, found = _from_components(label, components)
            problems += found
            if not any(stat != "slot" for stat in claim):
                continue
            tier = things[node].get("tier") if node in things else recipe["tier"]
            if tier is None:
                where = "the item" if node in things else "the recipe, since the item is vanilla's"
                problems.append(f"{label} sets {', '.join(sorted(claim))} but has no tier. Add \"tier\" to {where}: "
                                f"one of {', '.join(TIERS)}.")
            else:
                problems += _over_budget(label, tier, claim)
    return problems


# Recipe graph


def _variants(recipe):
    """The net change in materials for each way of filling a recipe's slots."""
    for choice in itertools.product(*([(node, count) for node in alternatives] for alternatives, count in recipe["inputs"])):
        net = Counter()
        for node, count in choice:
            net[node] -= count
        for node, count, _ in recipe["outputs"]:
            net[node] += count
        yield {node: change for node, change in net.items() if change}


def _vanilla_changes():
    for small, big in _VANILLA_STORAGE:
        small, big = f"minecraft:{small}", f"minecraft:{big}"
        yield f"vanilla {big}", {small: -9, big: 1}
        yield f"vanilla {small} from {big}", {big: -1, small: 9}


def _find_free_material(changes):
    """Finds recipes that, repeated in some ratio, leave more of something and less of nothing.

    A plain cycle search can't answer this: recipes take several inputs and the counts matter, so what's being
    asked is whether a non-negative mix of recipes has a net change that's all gains. That's a linear program,
    solved here with an exact simplex (Fractions, because a loop that breaks even must not round into a gain,
    and Bland's rule, because all those zero gains would otherwise let it cycle). Returns the recipes with how
    many times to run each, and what's left over, or None.
    """
    # A recipe can't be in a loop if something it uses never gets made, so most of the graph drops out here.
    while True:
        made = {node for _, net in changes for node, change in net.items() if change > 0}
        kept = [entry for entry in changes if all(change > 0 or node in made for node, change in entry[1].items())]
        if len(kept) == len(changes):
            break
        changes = kept
    if not changes:
        return None
    nodes = sorted({node for _, net in changes for node in net})
    columns = len(changes)
    # One row per material (it must not go down), and one capping the total, so the answer can't run off to infinity.
    rows = [[Fraction(-net.get(node, 0)) for _, net in changes] for node in nodes] + [[Fraction(1)] * columns]
    for index, row in enumerate(rows):
        row += [Fraction(int(index == other)) for other in range(len(rows))] + [Fraction(int(index == len(rows) - 1))]
    objective = [Fraction(-sum(net.values())) for _, net in changes] + [Fraction(0)] * (len(rows) + 1)
    basis = [columns + index for index in range(len(rows))]
    while True:
        entering = next((index for index, value in enumerate(objective[:-1]) if value < 0), None)
        if entering is None:
            break
        _, _, pivot = min((row[-1] / row[entering], basis[index], index)
                          for index, row in enumerate(rows) if row[entering] > 0)
        basis[pivot] = entering
        divisor = rows[pivot][entering]
        rows[pivot] = [value / divisor for value in rows[pivot]]
        for row in [*(row for index, row in enumerate(rows) if index != pivot), objective]:
            factor = row[entering]
            if factor:
                row[:] = [value - factor * other for value, other in zip(row, rows[pivot])]
    if objective[-1] <= 0:
        return None
    amounts = {basis[index]: row[-1] for index, row in enumerate(rows) if basis[index] < columns and row[-1] > 0}
    scale = math.lcm(*(amount.denominator for amount in amounts.values()))
    runs = {changes[column][0]: int(amount * scale) for column, amount in amounts.items()}
    left = Counter()
    for column, amount in amounts.items():
        for node, change in changes[column][1].items():
            left[node] += int(amount * scale) * change
    return runs, {node: change for node, change in left.items() if change}


def _check_cycles(recipes):
    """Fails on loops that make material from nothing. A loop that pays with something from outside isn't one:
    it's a conversion, like vanilla's smithing template duplication, and whether that's a fair price is a design question."""
    problems = []
    changes = list(_vanilla_changes())
    for recipe in recipes:
        combinations = math.prod(len(alternatives) for alternatives, _ in recipe["inputs"])
        if combinations > MAX_VARIANTS:
            problems.append(f"Recipe {recipe['source']} has {combinations} possible input combinations, "
                            f"over the {MAX_VARIANTS} that can be checked. Use fewer alternatives.")
        else:
            changes += [(recipe["source"], net) for net in _variants(recipe)]
    found = _find_free_material(changes)
    if found:
        runs, gains = found
        problems.append("These recipes make material from nothing: "
                        + ", ".join(f"{source} x{count}" for source, count in sorted(runs.items()))
                        + " leaves you with " + ", ".join(f"+{count} {node}" for node, count in sorted(gains.items()))
                        + ". Change the counts so a full loop gives back no more than it took.")
    return problems


def _natural_sources(features):
    """What exists without crafting: blocks the world places, and what mobs and ruin chests hand out."""
    placed, handed_out = set(), set()
    for feature_id, feature in features.items():
        manifest = feature["manifest"]
        for entry in [*manifest.get("ores", []), *manifest.get("plants", [])]:
            placed.add(f"block:{_key(feature_id, entry.get('block', ''))}")
        # A mob with no spawn entry still counts, because a module can summon it.
        for mob in manifest.get("mobs", {}).values():
            if mob.get("drops"):
                handed_out.add(f"item:{_key(feature_id, mob['drops']['item'])}")
        for ruin in manifest.get("ruins", {}).values():
            placed.update(_node(part["block"], feature_id) for part in ruin.get("parts", []) if str(part.get("block")).startswith("$block:"))
            handed_out.update(f"{found.group(1)}:{_key(feature_id, found.group(2))}"
                              for found in TOKEN.finditer(json.dumps(ruin.get("loot") or {})))
    return placed, handed_out


def _drop_of(node, things):
    """What breaking a block gives: itself, unless it says otherwise. This mod's loot tables have no silk touch
    branch, so an ore with its own drops is in the world but never in anyone's inventory."""
    drops = things.get(node, {}).get("drops")
    return f"item:{_key(node.split(':')[1].split('/')[0], drops['item'])}" if drops else node


def _check_obtainable(features, recipes):
    """Fails on anything nobody could ever get. A retired thing is meant to stop being obtainable, so it's exempt."""
    things = _things(features)
    problems = []
    for recipe in recipes:
        for alternatives, _ in recipe["inputs"]:
            for node in alternatives:
                if not _is_vanilla(node) and node not in things:
                    problems.append(f"Recipe {recipe['source']} uses {node}, which no feature declares. "
                                    "Refer to content with $item:name or $block:name.")
    placed, handed_out = _natural_sources(features)
    holdable = handed_out | {_drop_of(node, things) for node in placed}
    # Every recipe mode counts the same. Known recipes get their routes checked elsewhere, and guessable ones can
    # be found by trying, so all that matters here is whether their inputs exist.
    while True:
        reachable = set(holdable)
        for recipe in recipes:
            if all(any(_is_vanilla(node) or node in holdable for node in alternatives) for alternatives, _ in recipe["inputs"]):
                reachable.update(node for node, _, _ in recipe["outputs"])
        reachable.update(_drop_of(node, things) for node in holdable if node.startswith("block:"))
        if reachable == holdable:
            break
        holdable = reachable
    for node, thing in things.items():
        if thing.get("retired") or node in holdable or node in placed:
            continue
        blocked = [f"{recipe['source']} needs {next(iter(alternatives))}" for recipe in recipes
                   if any(output == node for output, _, _ in recipe["outputs"])
                   for alternatives, _ in recipe["inputs"]
                   if not any(_is_vanilla(option) or option in holdable for option in alternatives)]
        reason = f" Recipe {'; '.join(blocked)}, which nobody can get either." if blocked else ""
        problems.append(f"Nobody can obtain {node.split(':', 1)[1]}: no ore, plant, block or mob drop, ruin chest or craftable "
                        f"recipe makes it.{reason} Add a source, or mark it \"retired\": true if it's being phased out.")
    return problems


# Ore rarity


def _highest_tier(tiers):
    known = [tier for tier in tiers if tier in TIERS]
    return max(known, key=TIERS.index) if known else None


def _tiers_fed(start, recipes, things):
    """Every tier a material ends up in. A label can't undercut this: an ore called iron-tier that makes diamond-tier gear feeds diamond."""
    edges = {}
    for recipe in recipes:
        for alternatives, _ in recipe["inputs"]:
            for node in alternatives:
                edges.setdefault(node, set()).update(output for output, _, _ in recipe["outputs"])
    seen, waiting = set(), [start]
    while waiting:
        node = waiting.pop()
        if node not in seen:
            seen.add(node)
            waiting += edges.get(node, ())
    return [things[node].get("tier") for node in seen if node in things]


def check_ores(features, recipes):
    """Compares each ore's yield with the vanilla ore of the tier it feeds, adding up all of a block's entries,
    because splitting one ore into several entries is still one ore."""
    things = _things(features)
    supply = {}
    problems = []
    for feature_id, feature in features.items():
        for ore in feature["manifest"].get("ores", []):
            label = f"{feature_id}/{ore.get('id')}"
            numbers = [ore.get(field) for field in ("veinsPerChunk", "veinSize", "minY", "maxY")]
            if not all(_is_number(number) and not math.isnan(number) for number in numbers):
                problems.append(f"Ore {label} needs numbers for veinsPerChunk, veinSize, minY and maxY.")
                continue
            if "tier" in ore and ore["tier"] not in TIERS:
                problems.append(f"Ore {label} declares tier {ore['tier']!r}, but a tier must be one of {', '.join(TIERS)}.")
            node = f"block:{_key(feature_id, ore.get('block', ''))}"
            block = things.get(node, {})
            count = (block.get("drops") or {}).get("count")
            # Lots of drops per block is the same as lots of blocks, so the check counts what players end up with.
            mean_drop = sum(count) / 2 if isinstance(count, list) and len(count) == 2 and all(map(_is_number, count)) else 1
            entry = supply.setdefault(node, {"amount": 0, "start": _drop_of(node, things), "tiers": [block.get("tier")]})
            entry["amount"] += _expected(*numbers) * mean_drop
            entry["tiers"].append(ore.get("tier"))
    ceiling = max(ORE_CURVE.values()) * ORE_TOLERANCE
    for node, entry in supply.items():
        label, amount = node.split(":", 1)[1], entry["amount"]
        tier = _highest_tier(entry["tiers"] + _tiers_fed(entry["start"], recipes, things))
        about = f"gives about {amount:.1f} per chunk"
        if amount <= 0:
            problems.append(f"Ore {label} never generates: its veins or Y range give nothing inside rock, "
                            f"which is Y {ROCK[0]} to {ROCK[1]}. Fix veinsPerChunk, veinSize, minY or maxY.")
        elif tier is None:
            # With no tier there's no target to hit, so all that's left to catch is absurd amounts.
            if amount > ceiling:
                problems.append(f"Ore {label} {about}, more than {ceiling:.0f}, which is already twice vanilla's commonest ore. Lower it.")
        else:
            vanilla = ORE_CURVE[tier]
            if amount > vanilla * ORE_TOLERANCE:
                problems.append(f"Ore {label} feeds tier {tier} but {about}. Vanilla is about {vanilla:.1f}, and the limit "
                                f"is {vanilla * ORE_TOLERANCE:.1f}. Lower veinsPerChunk, veinSize or the drop count.")
            elif amount < vanilla / ORE_TOLERANCE:
                problems.append(f"Ore {label} feeds tier {tier} but {about}. Vanilla is about {vanilla:.1f}, and the least "
                                f"allowed is {vanilla / ORE_TOLERANCE:.1f}, so players would run dry. Raise it, or use a higher tier.")
    return problems


def run(features):
    """Reports every problem at once, so fixing a batch takes one try and not ten."""
    try:
        recipes = _read_recipes(features)
        problems = (check_power(features, recipes) + _check_cycles(recipes)
                    + _check_obtainable(features, recipes) + check_ores(features, recipes))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        # What couldn't be read hasn't been checked, so it can't pass. A crash here would also leave no answer at all.
        raise GateFailed(GATE, f"A feature.json has something in the wrong shape, so it can't be checked: {error!r}. "
                               "Compare it with docs/feature-format.md.") from error
    if problems:
        raise GateFailed(GATE, "\n".join(problems))
