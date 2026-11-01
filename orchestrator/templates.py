"""Starting points for the routine parts of a feature, so a builder only has to add what's special.

Each function merges into <folder>/feature.json, writes its art under <folder>/assets and returns
{"added": [names], "summary": text}. Nothing reaches the disk until the whole call is known to work, and a name
that already exists is refused, so a template can't overwrite a builder's work.
"""
import hashlib
import io
import json
import math
import os
import pathlib
import re

from assetkit import textures as tx, bbmodel

NAME = re.compile(r"[a-z0-9_]+")
TOKEN = re.compile(r"\$(block|item):([a-z0-9_]+)(?:/([a-z0-9_]+))?")
VANILLA = re.compile(r"#?minecraft:[a-z0-9_./-]+")
PLAIN_ID = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
THINGS = ("blocks", "items", "mobs")

# These are a copy of the numbers in broker/gates/balance.py, because broker/ isn't in the agent's container.
# test_templates compares the two, so they can't drift apart quietly.
TIERS = ("wood", "stone", "iron", "diamond", "netherite", "beyond", "mythic")
# Tier: tool durability, mining speed, and the damage bonus every tool of that material gets.
TOOLS = {"wood": (59, 2.0, 0), "stone": (131, 4.0, 1), "iron": (250, 6.0, 2), "diamond": (1561, 8.0, 3), "netherite": (2031, 9.0, 4)}
# Axes and hoes differ by material in vanilla. What a modifier adds to the base damage, before the bonus, and to the base speed.
AXES = {"wood": (6, -3.2), "stone": (7, -3.2), "iron": (6, -3.1), "diamond": (5, -3.0), "netherite": (5, -3.0)}
HOE_SPEEDS = {"wood": -3.0, "stone": -2.0, "iron": -1.0, "diamond": 0.0, "netherite": 0.0}
# Tier: durability factor, armor points for head, chest, legs and feet, toughness, knockback resistance.
ARMOR = {"wood": (5, (1, 3, 2, 1), 0, 0), "stone": (15, (2, 5, 4, 1), 0, 0), "iron": (15, (2, 6, 5, 2), 0, 0),
         "diamond": (33, (3, 8, 6, 3), 2, 0), "netherite": (37, (3, 8, 6, 3), 3, 0.1)}
ARMOR_DURABILITY = (11, 16, 15, 13)
# Yield per chunk of the vanilla ore each tier leans on.
ORE_CURVE = {"wood": 114.5, "stone": 100.47, "iron": 127.66, "diamond": 46.86, "netherite": 5.0, "beyond": 2.5, "mythic": 1.25}
ORE_TOLERANCE = 2.0
ROCK = (-64, 64)
MAX_VEIN_SIZE = 16

# Tiers past vanilla are netherite scaled up. Beyond's limit is 150%, so this leaves a builder room to go higher.
# Mythic has no limit at all.
STRONGER = {"beyond": 1.4, "mythic": 3}

# What vanilla asks of its ore at each tier: iron ore takes a stone pick, diamond an iron one and ancient debris a
# diamond one. Diamond is the highest tag that exists.
ORE_TOOL_LEVEL = {"wood": "wood", "stone": "stone", "iron": "stone", "diamond": "iron", "netherite": "diamond",
                  "beyond": "diamond", "mythic": "diamond"}
# Tier: usual vein size, where a lone ore sits, and where a pair sits. A pair has to cross into both kinds of rock.
ORE_SHAPE = {"wood": (12, (0, 64), (-16, 64)), "stone": (10, (0, 64), (-16, 64)), "iron": (9, (0, 56), (-24, 56)),
             "diamond": (6, (-64, -4), (-64, 16)), "netherite": (5, (-64, -16), (-64, 16)),
             "beyond": (2, (-64, -32), (-64, 12)), "mythic": (1, (-64, -48), (-64, 12))}
# Stone is gone below 0, and deepslate fades in from 8.
STONE_FLOOR, DEEPSLATE_TOP = 0, 8
STONE_ROCK = ["minecraft:stone", "minecraft:granite", "minecraft:diorite", "minecraft:andesite"]
DEEP_ROCK = ["minecraft:deepslate", "minecraft:tuff"]
# A pair's two ores are judged one at a time, and each has to reach half of vanilla, so this keeps their total near it.
PAIR_SHARE = 0.55

TOOL_KINDS = ("pickaxe", "axe", "shovel", "hoe", "sword")
TOOL_PATTERNS = {"pickaxe": ["XXX", " # ", " # "], "axe": ["XX", "X#", " #"], "shovel": ["X", "#", "#"], "hoe": ["XX", " #", " #"],
                 "sword": ["X", "X", "#"]}
# Vanilla's iron sword, read from the game's item report. Its fast rules are only for cobwebs and soft plants.
SWORD_TOOL = {"rules": [{"blocks": "minecraft:cobweb", "speed": 15.0, "correct_for_drops": True},
                        {"blocks": "#minecraft:sword_instantly_mines", "speed": 3.4028235e38},
                        {"blocks": "#minecraft:sword_efficient", "speed": 1.5}],
              "damage_per_block": 2, "can_destroy_blocks_in_creative": False}
# What stops a tier's pick from dropping harder ores. Netherite's is empty, so that's the right one past it too.
INCORRECT_FOR = {"wood": "wooden", "stone": "stone", "iron": "iron", "diamond": "diamond", "netherite": "netherite",
                 "beyond": "netherite", "mythic": "netherite"}

ARMOR_SLOTS = ("head", "chest", "legs", "feet")
# Slot: name, what vanilla's modifiers are called, recipe, and icon. Each piece needs its own modifier id, or wearing
# a second piece replaces the first one's armor.
ARMOR_PIECES = {
    "head": ("helmet", "armor.helmet", ["XXX", "X X"],
             ["................", "................", "................", "................", ".....555544.....",
              "....55444443....", "...5544444332...", "...5444443332...", "...5443333322...", "...544....322...",
              "...44......22...", "...43......21...", "................", "................", "................", "................"]),
    "chest": ("chestplate", "armor.chestplate", ["X X", "XXX", "XXX"],
              ["................", "................", "...554....443...", "..55544..44332..", "..544444444332..",
               "..54.444433.32..", "....54444332....", "....54444332....", "....54443322....", "....44443322....",
               "....44433322....", "....43333221....", "....33322211....", "................", "................", "................"]),
    "legs": ("leggings", "armor.leggings", ["XXX", "X X", "X X"],
             ["................", "................", "................", "....55554443....", "....54444332....",
              "....54433322....", "....544..322....", "....544..322....", "....543..322....", "....443..321....",
              "....433..221....", "....433..221....", "....332..211....", "................", "................", "................"]),
    "feet": ("boots", "armor.boots", ["X X", "X X"],
             ["................", "................", "................", "................", "................",
              "...544....332...", "...544....332...", "...543....322...", "...443....322...", "..5443....3321..",
              ".54443....33221.", ".44332....22211.", "................", "................", "................", "................"]),
}
# Vanilla's worn looks, by tier, with the sound each one makes. A feature can't ship its own yet.
WORN_LOOK = {"wood": "leather", "stone": "chainmail", "iron": "iron", "diamond": "diamond", "netherite": "netherite",
             "beyond": "netherite", "mythic": "netherite"}
EQUIP_SOUNDS = {"leather": "leather", "copper": "copper", "chainmail": "chain", "iron": "iron", "gold": "gold", "diamond": "diamond",
                "turtle_scute": "turtle", "netherite": "netherite"}

PLANT_FAMILIES = ("plant", "glow_plant", "tinted_plant")
PLANT_KINDS = ("flower", "tulip", "grass", "sapling", "mushroom", "crystal")
FOOD_WORDS = {"fruit": "Fruit", "berries": "Berries", "loaf": "Loaf", "meat": "Meat", "stew": "Stew", "cookie": "Cookie"}
SURFACE_Y, CAVE_Y = (40, 200), (-50, 40)
GROUND = ["minecraft:grass_block"]
CAVE_FLOOR = ["minecraft:stone", "minecraft:deepslate", "minecraft:tuff"]

MOB_CATEGORIES = ("monster", "creature")
MOB_BEHAVIOURS = ("hostile", "neutral", "passive", "skittish")
FIGHTERS = ("hostile", "neutral")
# Width and height in blocks, about what each kind of model fills.
MOB_SIZES = {"humanoid": (0.6, 1.95), "quadruped": (0.9, 1.1), "slime": (1.0, 1.0), "flying": (0.8, 0.8)}
LIGHTS = ("dark", "bright", "any")


def _swing(phase):
    return math.sin(math.pi * phase)


# Each one starts and ends at rest, because it plays once on top of whatever else is running.
ATTACKS = {
    "humanoid": {"arm_right": {"rotation": lambda p: (-100 * _swing(p), 0, 0)},
                 "arm_left": {"rotation": lambda p: (-100 * _swing(p), 0, 0)},
                 "body": {"rotation": lambda p: (6 * _swing(p), 0, 0)}},
    "quadruped": {"head": {"rotation": lambda p: (22 * _swing(p), 0, 0)},
                  "body": {"position": lambda p: (0, 0, -2 * _swing(p))}},
    "slime": {"body": {"position": lambda p: (0, 3 * _swing(p), -4 * _swing(p)),
                       "scale": lambda p: (1 + 0.12 * _swing(p), 1 - 0.12 * _swing(p), 1 + 0.12 * _swing(p))}},
    "flying": {"body": {"rotation": lambda p: (-24 * _swing(p), 0, 0), "position": lambda p: (0, 0, -3 * _swing(p))},
               "head": {"rotation": lambda p: (16 * _swing(p), 0, 0)}},
}

# A package name can't be one of these, or start with a digit, and the module's package has to be the feature's id.
JAVA_WORDS = set("abstract assert boolean break byte case catch char class const continue default do double else enum extends "
                 "false final finally float for goto if implements import instanceof int interface long native new null package "
                 "private protected public return short static strictfp super switch synchronized this throw throws transient "
                 "true try void volatile while".split())

MODULE = """package gm.feature.@ID@;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.MachineAttempt;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.util.Prediction;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

import java.util.List;

/** A starting point: the machine keeps count of its running time, and tries what a player holds against its recipes. */
public final class @CLASS@ implements ServerModule {
	private static final String MACHINE = "@MACHINE@";
	// A machine ticks 20 times a second for every one placed, so real work should only run now and then.
	private static final int WORK_EVERY_TICKS = 20;

	@Override
	public void enable(ServerModuleContext context) {
		context.bindMachine(MACHINE, @CLASS@::tick);
		context.bindBlock(MACHINE, new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				return tryRecipe(context, player);
			}
		});
	}

	private static void tick(SlotBlockEntity machine) {
		if (machine.getLevel().getGameTime() % WORK_EVERY_TICKS != 0) {
			return;
		}
		// Everything it remembers goes in here, because this survives the module being replaced.
		CompoundTag data = machine.data();
		data.putInt("seconds_running", data.getIntOr("seconds_running", 0) + 1);
		machine.setChanged();
	}

	private static InteractionResult tryRecipe(ServerModuleContext context, Player player) {
		ItemStack main = player.getMainHandItem();
		ItemStack off = player.getOffhandItem();
		MachineAttempt attempt = context.attemptRecipe(player, MACHINE, List.of(main, off));
		if (attempt.succeeded()) {
			// This takes one of each, so a recipe that needs more than one of something has to take more here.
			main.shrink(1);
			off.shrink(1);
			player.getInventory().placeItemBackInInventory(attempt.output(), Prediction.SERVER_ONLY);
			player.sendSystemMessage(Component.literal("@DISPLAY@ makes something."));
		} else if (attempt.locked()) {
			player.sendSystemMessage(Component.literal("@DISPLAY@ waits, as if you were missing something."));
		} else if (attempt.nearMiss()) {
			player.sendSystemMessage(Component.literal("@DISPLAY@ stirs."));
		}
		return InteractionResult.SUCCESS;
	}
}
"""


class TemplateError(Exception):
    """Why a template refused, worded so a builder can fix it."""


class _Draft:
    """One call's changes. They stay in here until commit, so a refused call leaves the folder as it was."""

    def __init__(self, folder, node=None, phase=None):
        self.folder = pathlib.Path(folder)
        self.id = self.folder.name
        if not NAME.fullmatch(self.id):
            raise TemplateError(f"The folder's name is the feature's id, so it must be lowercase letters, digits and underscores, not {self.id!r}.")
        self.path = self.folder / "feature.json"
        self.manifest = {"id": self.id}
        if self.path.exists():
            try:
                self.manifest = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise TemplateError(f"{self.path} isn't valid JSON, so there's nothing safe to add to: {error}") from error
            if not isinstance(self.manifest, dict) or self.manifest.get("id") != self.id:
                raise TemplateError(f"{self.path} has to have \"id\": \"{self.id}\", matching its folder.")
        if node is not None:
            self.manifest["node"] = node
        if phase is not None:
            self.manifest["phase"] = phase
        self.files, self.added, self.notes = {}, [], []

    def thing(self, table, name, entry):
        """Blocks, items and mobs share one set of names, because bindings.json looks all of them up by bare name."""
        _check_name(name)
        for other in THINGS:
            if name in self.manifest.get(other, {}):
                raise TemplateError(f"{name} already exists in {other}. Use another name, or edit it by hand.")
        self.manifest.setdefault(table, {})[name] = entry
        self.mention(name)

    def recipe(self, name, entry):
        _check_name(name)
        if name in self.manifest.get("recipes", {}):
            raise TemplateError(f"There's already a recipe called {name}. Use another name, or edit it by hand.")
        self.manifest.setdefault("recipes", {})[name] = entry
        self.mention(name)

    def placement(self, table, entry):
        if any(existing.get("id") == entry["id"] for existing in self.manifest.get(table, [])):
            raise TemplateError(f"{table} already has an entry with id {entry['id']}, and an id can never be reused.")
        self.manifest.setdefault(table, []).append(entry)
        self.mention(entry["id"])

    def mention(self, name):
        """A recipe usually has the name of what it makes, and that's one name to report."""
        if name not in self.added:
            self.added.append(name)

    def has(self, table, name):
        return name in self.manifest.get(table, {})

    def file(self, relative, data):
        if relative in self.files or (self.folder / relative).exists():
            raise TemplateError(f"{relative} already exists, and a template won't overwrite it. Use another name, or remove it first.")
        self.files[relative] = data

    def texture(self, name, image):
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        self.file(f"assets/textures/{name}.png", buffer.getvalue())

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def ask_host(self, text):
        requests = self.manifest.setdefault("host_requests", [])
        if text not in requests:
            requests.append(text)

    def commit(self, about, summary):
        self.manifest.setdefault("summary", about)
        for relative, data in self.files.items():
            target = self.folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        # The art goes first, and this replaces the file whole, so feature.json never mentions something missing.
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name("feature.json.tmp")
        temporary.write_text(json.dumps(self.manifest, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        return {"added": self.added, "summary": " ".join([summary, *self.notes])}


def _check_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise TemplateError(f"A name must be lowercase letters, digits and underscores, not {name!r}.")


def _check_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise TemplateError(f"{label} has to be some text, not {value!r}.")


def _check_tier(tier):
    if tier not in TIERS:
        raise TemplateError(f"Tier must be one of {', '.join(TIERS)}, not {tier!r}.")


def _check_color(color, label):
    try:
        tx.rgb(color)
    except (TypeError, ValueError, IndexError) as error:
        raise TemplateError(f"{label} must be \"#rrggbb\" or [r, g, b], not {color!r}.") from error


def _whole(value, label):
    """Gson reads these into an int on the server, and 1.5 stops the whole file loading, so they have to be whole here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value != int(value):
        raise TemplateError(f"{label} must be a whole number, not {value!r}.")
    return int(value)


def _number(value, label, lowest=0.0, above=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < lowest or (above and value == lowest):
        raise TemplateError(f"{label} must be a number {'above' if above else 'of at least'} {lowest:g}, not {value!r}.")
    return value


def _exact_ids(values, label):
    """The server looks these up one by one and has no way to read a tag, and one that can't be parsed stops every patch loading."""
    if not isinstance(values, (list, tuple)) or not values:
        raise TemplateError(f"{label} must be a list of ids, not {values!r}.")
    for value in values:
        if not isinstance(value, str) or not PLAIN_ID.fullmatch(value):
            raise TemplateError(f"{label} takes exact ids like minecraft:stone, not tags or names: {value!r}.")
    return list(values)


def _drop_count(count, label):
    if not isinstance(count, (list, tuple)) or len(count) != 2:
        raise TemplateError(f"{label} must be [lowest, highest], not {count!r}.")
    low, high = _whole(count[0], label), _whole(count[1], label)
    if low < 0 or high < low or high == 0:
        raise TemplateError(f"{label} must be [lowest, highest] with something to drop, not {count!r}.")
    return [low, high]


def _y_range(low, high):
    low, high = _whole(low, "min_y"), _whole(high, "max_y")
    if low >= high:
        raise TemplateError(f"min_y has to be below max_y, not {low} and {high}.")
    return low, high


def _ingredient(draft, value, label):
    """A bare name counts as no ingredient at all without anything saying so, and an unknown one stops the render, so this says now."""
    if isinstance(value, str) and VANILLA.fullmatch(value):
        return value
    found = TOKEN.fullmatch(value) if isinstance(value, str) else None
    if not found:
        raise TemplateError(f"{label} must be like $item:name, $block:name, $item:other_feature/name, minecraft:id or #minecraft:tag, not {value!r}.")
    kind, first, second = found.groups()
    table = f"{kind}s"
    if second is None or first == draft.id:
        if not draft.has(table, second or first):
            raise TemplateError(f"{label} is {value}, which this feature doesn't declare yet. Add that first.")
        return value
    other = draft.folder.parent / first / "feature.json"
    try:
        declared = json.loads(other.read_text(encoding="utf-8")).get(table, {})
    except (OSError, ValueError, AttributeError):
        draft.note(f"{first} isn't here to check, so make sure it declares {second}.")
        return value
    if second not in declared:
        raise TemplateError(f"{label} is {value}, but feature {first} doesn't declare {second}.")
    return value


def _how_found(draft, mode, route):
    if mode == "open":
        return {"mode": "open"}
    if mode != "known":
        raise TemplateError(f"mode must be open or known here, not {mode!r}. Guessable is only for machine recipes.")
    if not route:
        raise TemplateError("A known recipe needs a route, naming the knowledge entry that unlocks it.")
    if "/" not in route and not draft.has("knowledge", route):
        draft.note(f"Add a knowledge entry called {route}, or the recipes that need it won't pass.")
    return {"mode": "known", "route": route}


def _shaped(pattern, key, result, category, how):
    return {**how, "json": {"type": "minecraft:crafting_shaped", "category": category, "pattern": pattern, "key": key,
                            "result": {"id": result, "count": 1}}}


def _shapeless(ingredients, result, count, how):
    return {**how, "json": {"type": "minecraft:crafting_shapeless", "category": "misc", "ingredients": ingredients,
                            "result": {"id": result, "count": count}}}


def _furnace(kind, ingredient, result, ticks):
    return {"mode": "open", "json": {"type": f"minecraft:{kind}", "category": "misc", "ingredient": ingredient, "cookingtime": ticks,
                                     "experience": 0.7, "result": {"id": result}}}


def _repairable(ingredient):
    """A bad tag in a recipe only loses that recipe, but one here loses every item's defaults, so repairs only use exact ids."""
    return {} if ingredient.startswith("#") else {"minecraft:repairable": {"items": ingredient}}


def _modifier(attribute, modifier_id, amount, slot):
    return {"type": f"minecraft:{attribute}", "id": f"minecraft:{modifier_id}", "amount": amount, "operation": "add_value", "slot": slot}


# Ores


def _rock_fraction(low, high):
    overlap = min(high, ROCK[1]) - max(low, ROCK[0]) + 1
    return max(0, overlap) / (high - low + 1)


def _fit_veins(tier, want, size, fixed_size, low, high, mean_drop, label):
    """Whole numbers of veins and blocks, because the server reads both as ints, closest to what's wanted and near this tier's size."""
    fraction = _rock_fraction(low, high)
    if fraction <= 0:
        raise TemplateError(f"{label} would never generate: Y {low} to {high} has no rock in it, which is Y {ROCK[0]} to {ROCK[1]}.")
    floor, ceiling = ORE_CURVE[tier] / ORE_TOLERANCE, ORE_CURVE[tier] * ORE_TOLERANCE
    best = None
    for candidate in [fixed_size] if fixed_size else range(1, MAX_VEIN_SIZE + 1):
        unit = candidate * fraction * mean_drop
        for veins in {max(1, math.floor(want / unit)), max(1, math.ceil(want / unit))}:
            amount = veins * unit
            if floor <= amount <= ceiling:
                miss = abs(amount - want) / want + abs(candidate - size) * 0.02
                if best is None or miss < best[0]:
                    best = (miss, veins, candidate, amount)
    if best is None:
        raise TemplateError(f"{label} can't reach tier {tier}'s yield of {floor:g} to {ceiling:g} per chunk with whole veins at these settings. "
                            "Change the Y range, vein size or drop count.")
    return best[1:]


def _ore_entry(draft, block, tier, want, shape, low, high, mean_drop, replaces, biomes):
    size, fixed = shape
    veins, vein_size, amount = _fit_veins(tier, want, size, fixed, low, high, mean_drop, block)
    entry = {"id": f"{draft.id}_{block}_v1", "block": block, "replaces": replaces, "veinsPerChunk": veins, "veinSize": vein_size,
             "minY": low, "maxY": high, "tier": tier}
    if biomes:
        entry["biomes"] = biomes
    # Chunks remember ids across every feature, so the feature's id keeps two features' tin apart.
    draft.placement("ores", entry)
    return amount


def new_ore(folder, *, name, display, color, tier, deep=False, biomes=None, min_y=None, max_y=None, stone_color=None, seed=1,
            drop_count=None, vein_size=None, tool_level=None, block_style="plate", node=None, phase=None):
    """An ore with a raw item, an ingot and a storage block, and the recipes between them. Makes <name>_ore (and deep_<name>_ore
    if deep), raw_<name>, <name>_ingot and <name>_block. Its yield is set from the tier, with depth to match unless you give
    min_y and max_y. biomes are exact ids, not tags. Colors are "#rrggbb"."""
    draft = _Draft(folder, node, phase)
    _check_name(name)
    _check_text(display, "display")
    _check_tier(tier)
    _check_color(color, "color")
    if stone_color is not None:
        _check_color(stone_color, "stone_color")
    usual_size, lone, pair = ORE_SHAPE[tier]
    default_low, default_high = pair if deep else lone
    low, high = _y_range(default_low if min_y is None else min_y, default_high if max_y is None else max_y)
    biomes = _exact_ids(biomes, "biomes") if biomes else []
    count = _drop_count(drop_count, "drop_count") if drop_count is not None else [1, 1]
    mean_drop = sum(count) / 2
    fixed = None
    if vein_size is not None:
        fixed = _whole(vein_size, "vein_size")
        if not 1 <= fixed <= MAX_VEIN_SIZE:
            raise TemplateError(f"vein_size must be from 1 to {MAX_VEIN_SIZE}, not {vein_size!r}.")
    level = ORE_TOOL_LEVEL[tier] if tool_level is None else tool_level
    if level not in ("wood", "stone", "iron", "diamond"):
        raise TemplateError(f"tool_level must be wood, stone, iron or diamond, not {level!r}.")
    if block_style not in ("plate", "rivets", "gem"):
        raise TemplateError(f"block_style must be plate, rivets or gem, not {block_style!r}.")
    # There's no tag for wood, because any pickaxe will do.
    needs = {"tool": "pickaxe", **({"tool_level": level} if level != "wood" else {})}

    ore, raw, ingot, storage = f"{name}_ore", f"raw_{name}", f"{name}_ingot", f"{name}_block"
    drops = {"item": raw, "count": count}
    curve = ORE_CURVE[tier]
    shape = (usual_size, fixed)
    if deep:
        shallow = (max(low, STONE_FLOOR), high)
        under = (low, min(high, DEEPSLATE_TOP))
        if shallow[0] >= shallow[1] or under[0] >= under[1]:
            raise TemplateError(f"A deep pair needs a range that crosses Y {STONE_FLOOR}, with stone above and deepslate below, not {low} to {high}. "
                                "Widen it, or set deep to false.")
        deep_ore = f"deep_{name}_ore"
        draft.thing("blocks", ore, {"family": "ore", "display": f"{display} Ore", "texture": ore, "tier": tier, **needs, "drops": drops})
        draft.thing("blocks", deep_ore, {"family": "deep_ore", "display": f"Deep {display} Ore", "texture": deep_ore, "tier": tier, **needs, "drops": drops})
        draft.texture(ore, tx.ore(color, seed=seed, stone_color=stone_color))
        draft.texture(deep_ore, tx.ore(color, base="deepslate", seed=seed))
        amount = _ore_entry(draft, ore, tier, curve * PAIR_SHARE, shape, *shallow, mean_drop, STONE_ROCK, biomes)
        amount += _ore_entry(draft, deep_ore, tier, curve * PAIR_SHARE, shape, *under, mean_drop, DEEP_ROCK, biomes)
    else:
        only_deep = high <= STONE_FLOOR
        only_stone = low >= STONE_FLOOR
        family, base = ("deep_ore", "deepslate") if only_deep else ("ore", "stone")
        replaces = DEEP_ROCK if only_deep else STONE_ROCK if only_stone else STONE_ROCK + DEEP_ROCK
        draft.thing("blocks", ore, {"family": family, "display": f"{display} Ore", "texture": ore, "tier": tier, **needs, "drops": drops})
        draft.texture(ore, tx.ore(color, base=base, seed=seed, stone_color=stone_color))
        amount = _ore_entry(draft, ore, tier, curve, shape, low, high, mean_drop, replaces, biomes)
    draft.thing("blocks", storage, {"family": "metal", "display": f"Block of {display}", "texture": storage, **needs})
    draft.thing("items", raw, {"display": f"Raw {display}", "texture": raw})
    draft.thing("items", ingot, {"display": f"{display} Ingot", "texture": ingot})
    draft.texture(raw, tx.raw_chunk(color, seed=seed))
    draft.texture(ingot, tx.ingot(color, seed=seed))
    draft.texture(storage, tx.metal(color, seed=seed, style=block_style))
    draft.recipe(f"{ingot}_smelting", _furnace("smelting", f"$item:{raw}", f"$item:{ingot}", 200))
    draft.recipe(f"{ingot}_blasting", _furnace("blasting", f"$item:{raw}", f"$item:{ingot}", 100))
    draft.recipe(storage, _shaped(["XXX", "XXX", "XXX"], {"X": f"$item:{ingot}"}, f"$block:{storage}", "building", {"mode": "open"}))
    draft.recipe(f"{ingot}_from_block", _shapeless([f"$block:{storage}"], f"$item:{ingot}", 9, {"mode": "open"}))
    needed = "any pickaxe" if level == "wood" else f"at least a {level} pickaxe"
    return draft.commit(f"{display}: an ore, ingot and storage block at tier {tier}.",
                        f"Added {display} at tier {tier}: about {amount:.1f} per chunk from Y {low} to {high}, needing {needed}, with raw item, ingot, "
                        "storage block, smelting, blasting and block recipes. Left to decide: where it forms and what the ingot makes.")


# Tools


def _scaled(tier):
    return ("netherite", STRONGER[tier]) if tier in STRONGER else (tier, 1)


def tool_numbers(tier):
    """Returns durability, mining speed, and for each kind what its modifiers add to the base damage and speed."""
    base, scale = _scaled(tier)
    durability, speed, bonus = TOOLS[base]
    axe_damage, axe_speed = AXES[base]
    kinds = {"sword": (3 + bonus, -2.4), "shovel": (1.5 + bonus, -3.0), "pickaxe": (1 + bonus, -2.8),
             "axe": (axe_damage + bonus, axe_speed), "hoe": (0, HOE_SPEEDS[base])}
    # Scaling what a tooltip shows, not the modifier, because the base of 1 is the player's own.
    return int(durability * scale), round(speed * scale, 3), {kind: (round((1 + damage) * scale - 1, 3), swing) for kind, (damage, swing) in kinds.items()}


def _strength(tier):
    return f"{STRONGER[tier]:g} times netherite's numbers" if tier in STRONGER else "vanilla's numbers"


def _tool_item(kind, display, texture, tier, repair):
    durability, speed, kinds = tool_numbers(tier)
    damage, swing = kinds[kind]
    if kind == "sword":
        tool, weapon = SWORD_TOOL, {"item_damage_per_attack": 1}
    else:
        tool = {"rules": [{"blocks": f"#minecraft:incorrect_for_{INCORRECT_FOR[tier]}_tool", "correct_for_drops": False},
                          {"blocks": f"#minecraft:mineable/{kind}", "speed": speed, "correct_for_drops": True}]}
        weapon = {"item_damage_per_attack": 2}
    if kind == "axe":
        weapon["disable_blocking_for_seconds"] = 5.0
    # Without minecraft:damage a stack with max_damage never wears out.
    components = {"minecraft:max_damage": durability, "minecraft:damage": 0, "minecraft:max_stack_size": 1, "minecraft:tool": tool,
                  "minecraft:weapon": weapon,
                  "minecraft:attribute_modifiers": [_modifier("attack_damage", "base_attack_damage", damage, "mainhand"),
                                                    _modifier("attack_speed", "base_attack_speed", swing, "mainhand")],
                  **repair}
    # Stripping logs, tilling and making paths are this component in 26.3, not code on a tool class.
    if kind in ("axe", "shovel", "hoe"):
        components["minecraft:block_transformer"] = f"minecraft:{kind}"
    return {"display": display, "texture": texture, "tier": tier, "handheld": True, "components": components}


def new_tool_set(folder, *, material, display, tier, ingredient, color, kinds=TOOL_KINDS, mode="open", route=None, seed=1,
                 handle_ingredient="minecraft:stick", handle_color=None, node=None, phase=None):
    """Tools with vanilla's numbers for the tier, each with its art and crafting recipe, named <material>_pickaxe and so on. ingredient
    is like $item:tin_ingot or minecraft:iron_ingot. Past a progression's first nodes, give handle_ingredient something from an
    earlier node, so the recipes are gated. mode is open or known, and known needs a route."""
    draft = _Draft(folder, node, phase)
    _check_name(material)
    _check_text(display, "display")
    _check_tier(tier)
    _check_color(color, "color")
    if handle_color is not None:
        _check_color(handle_color, "handle_color")
    kinds = list(kinds)
    if not kinds or any(kind not in TOOL_KINDS for kind in kinds):
        raise TemplateError(f"kinds must come from {', '.join(TOOL_KINDS)}, not {kinds!r}.")
    ingredient = _ingredient(draft, ingredient, "ingredient")
    handle_ingredient = _ingredient(draft, handle_ingredient, "handle_ingredient")
    how = _how_found(draft, mode, route)
    repair = _repairable(ingredient)
    handle = {"handle": handle_color} if handle_color is not None else {}
    for kind in kinds:
        name = f"{material}_{kind}"
        draft.thing("items", name, _tool_item(kind, f"{display} {kind.capitalize()}", name, tier, repair))
        draft.texture(name, getattr(tx, kind)(color, seed=seed, **handle))
        draft.recipe(name, _shaped(TOOL_PATTERNS[kind], {"X": ingredient, "#": handle_ingredient}, f"$item:{name}", "equipment", how))
    if ingredient.startswith("$"):
        draft.note(f"Whatever ore makes {ingredient} now counts as feeding tier {tier}, so keep the two matched.")
    return draft.commit(f"{display} tools at tier {tier}.",
                        f"Added {', '.join(kinds)} in {display} at tier {tier}, with {_strength(tier)}. Left to decide: what makes these more than a reskin.")


# Armor


def armor_numbers(tier, slot):
    """Returns durability, armor, toughness and knockback resistance for one piece."""
    base, scale = _scaled(tier)
    factor, points, toughness, knockback = ARMOR[base]
    index = ARMOR_SLOTS.index(slot)
    return int(factor * scale * ARMOR_DURABILITY[index]), round(points[index] * scale, 3), round(toughness * scale, 3), round(knockback * scale, 3)


def _armor_look(worn_look, tier):
    if worn_look == "auto":
        return WORN_LOOK[tier]
    if worn_look is None:
        return None
    look = str(worn_look).removeprefix("minecraft:")
    if look not in EQUIP_SOUNDS:
        raise TemplateError(f"worn_look must be one of vanilla's, {', '.join(EQUIP_SOUNDS)}, or \"auto\", or null for nothing at all, not {worn_look!r}.")
    return look


def _armor_item(slot, display, texture, tier, look, repair):
    durability, armor, toughness, knockback = armor_numbers(tier, slot)
    _, modifier_id, _, _ = ARMOR_PIECES[slot]
    modifiers = [_modifier("armor", modifier_id, armor, slot)]
    if toughness:
        modifiers.append(_modifier("armor_toughness", modifier_id, toughness, slot))
    if knockback:
        modifiers.append(_modifier("knockback_resistance", modifier_id, knockback, slot))
    equippable = {"slot": slot}
    if look:
        equippable.update(asset_id=f"minecraft:{look}", equip_sound=f"minecraft:item.armor.equip_{EQUIP_SOUNDS[look]}")
    return {"display": display, "texture": texture, "tier": tier,
            "components": {"minecraft:max_damage": durability, "minecraft:damage": 0, "minecraft:max_stack_size": 1,
                           "minecraft:equippable": equippable, "minecraft:attribute_modifiers": modifiers, **repair}}


def _fill_gap(pattern):
    """Puts E in a pattern's first gap, the one spot that doesn't change how much of the main material a piece costs."""
    row = next(index for index, text in enumerate(pattern) if " " in text)
    return [*pattern[:row], pattern[row].replace(" ", "E", 1), *pattern[row + 1:]]


def new_armor_set(folder, *, material, display, tier, ingredient, color, slots=ARMOR_SLOTS, mode="open", route=None, seed=1,
                  extra_ingredient=None, worn_look="auto", node=None, phase=None):
    """Armor pieces with vanilla's numbers for the tier, each with its art and crafting recipe, named <material>_helmet, _chestplate,
    _leggings and _boots. ingredient is like $item:tin_ingot. Past a progression's first nodes, give extra_ingredient something from an
    earlier node, so the recipes are gated. A feature can't ship its own worn look yet, so worn_look borrows one of vanilla's."""
    draft = _Draft(folder, node, phase)
    _check_name(material)
    _check_text(display, "display")
    _check_tier(tier)
    _check_color(color, "color")
    slots = list(slots)
    if not slots or any(slot not in ARMOR_SLOTS for slot in slots):
        raise TemplateError(f"slots must come from {', '.join(ARMOR_SLOTS)}, not {slots!r}. Animal armor isn't covered by this template.")
    ingredient = _ingredient(draft, ingredient, "ingredient")
    extra = _ingredient(draft, extra_ingredient, "extra_ingredient") if extra_ingredient is not None else None
    how = _how_found(draft, mode, route)
    look = _armor_look(worn_look, tier)
    repair = _repairable(ingredient)
    # No generator draws armor icons yet, so these use the same sprite code as the tools, from the template's own shapes.
    tint = tx._jitter(color, tx._rng(seed, 31))
    for slot in slots:
        word, _, pattern, icon = ARMOR_PIECES[slot]
        name = f"{material}_{word}"
        draft.thing("items", name, _armor_item(slot, f"{display} {word.capitalize()}", name, tier, look, repair))
        draft.texture(name, tx._sprite(icon, tint))
        key = {"X": ingredient}
        if extra:
            pattern = _fill_gap(pattern)
            key["E"] = extra
        draft.recipe(name, _shaped(pattern, key, f"$item:{name}", "equipment", how))
    if ingredient.startswith("$"):
        draft.note(f"Whatever ore makes {ingredient} now counts as feeding tier {tier}, so keep the two matched.")
    if sum(armor_numbers(tier, slot)[1] for slot in ARMOR_SLOTS) > 30:
        draft.note("The game caps total armor at 30, so a full set wastes the rest.")
    worn = f"borrow vanilla's {look} look" if look else "show nothing"
    draft.ask_host(f"Let a feature ship its own worn armor art. {display} armor has to {worn} when worn, because equipment assets aren't allowed in the pack.")
    return draft.commit(f"{display} armor at tier {tier}.",
                        f"Added {', '.join(slots)} in {display} at tier {tier}, with {_strength(tier)}. Worn, they {worn}, because a feature can't ship its own "
                        "worn art yet, and that's now in host_requests. Left to decide: what makes these more than a reskin.")


# Plants


def _food_item(food, name, display):
    """Returns the food's art kind, its name and its item."""
    if not isinstance(food, dict) or "nutrition" not in food or "saturation" not in food:
        raise TemplateError(f"food must be like {{\"nutrition\": 4, \"saturation\": 2.4}}, not {food!r}.")
    kind = food.get("kind", "fruit")
    if kind not in FOOD_WORDS:
        raise TemplateError(f"A food's kind must be one of {', '.join(FOOD_WORDS)}, not {kind!r}.")
    food_name = food.get("name", f"{name}_{kind}")
    food_display = food.get("display", f"{display} {FOOD_WORDS[kind]}")
    _check_text(food_display, "A food's display")
    values = {"nutrition": _whole(food["nutrition"], "nutrition"), "saturation": _number(food["saturation"], "saturation")}
    if values["nutrition"] < 0:
        raise TemplateError("nutrition can't be below 0.")
    if "can_always_eat" in food:
        values["can_always_eat"] = bool(food["can_always_eat"])
    seconds = _number(food.get("consume_seconds", 1.6), "consume_seconds", above=True)
    # Without a consumable the food values do nothing, and the client shows no eating.
    components = {"minecraft:food": values, "minecraft:consumable": {"consume_seconds": seconds}}
    return kind, food_name, {"display": food_display, "texture": food_name, "components": components}


def new_plant(folder, *, name, display, color, family="plant", kind="flower", on=None, per_chunk=1.0, min_y=None, max_y=None, underground=False,
              biomes=None, food=None, seed_item=True, seed=1, stem=None, node=None, phase=None):
    """A plant the world grows, with a permanent plants entry, a seed <name>_seeds that places it, and optionally a food it drops, from
    food = {"nutrition": n, "saturation": s}, which can also take name, display, kind and consume_seconds. on and biomes are exact ids,
    not tags. There are only 5 plant slots and 2 glow_plant slots, ever, so spend them carefully."""
    draft = _Draft(folder, node, phase)
    _check_name(name)
    _check_text(display, "display")
    _check_color(color, "color")
    if family not in PLANT_FAMILIES:
        raise TemplateError(f"family must be one of {', '.join(PLANT_FAMILIES)}, not {family!r}.")
    if kind not in PLANT_KINDS:
        raise TemplateError(f"kind must be one of {', '.join(PLANT_KINDS)}, not {kind!r}.")
    underground = bool(underground)
    default_low, default_high = CAVE_Y if underground else SURFACE_Y
    low, high = _y_range(default_low if min_y is None else min_y, default_high if max_y is None else max_y)
    on = _exact_ids(on if on is not None else (CAVE_FLOOR if underground else GROUND), "on")
    biomes = _exact_ids(biomes, "biomes") if biomes else []
    per_chunk = _number(per_chunk, "per_chunk", above=True)
    # The biome's tint multiplies over the whole texture, so coloured leaves would turn muddy.
    stem = stem if stem is not None else (150, 150, 150) if family == "tinted_plant" else (66, 122, 46)
    _check_color(stem, "stem")

    seed_name = f"{name}_seeds"
    food_kind, food_name, food_item = _food_item(food, name, display) if food is not None else (None, None, None)
    block = {"family": family, "display": display, "texture": name}
    # A block can only drop one thing, so a food comes from the plant and its seed from the food, like melon seeds.
    if food_name or seed_item:
        block["drops"] = {"item": food_name or seed_name, "count": [1, 1]}
    draft.thing("blocks", name, block)
    draft.texture(name, tx.plant(kind, color, stem, seed=seed))
    entry = {"id": f"{draft.id}_{name}_v1", "block": name, "on": on, "perChunk": per_chunk, "minY": low, "maxY": high, "underground": underground}
    if biomes:
        entry["biomes"] = biomes
    draft.placement("plants", entry)
    if food_name:
        draft.thing("items", food_name, food_item)
        draft.texture(food_name, tx.food(food_kind, color, seed=seed))
    if seed_item:
        draft.thing("items", seed_name, {"display": f"{display} Seeds", "texture": seed_name, "places": {"block": f"$block:{name}", "on": on}})
        draft.texture(seed_name, tx.seeds(tx.mix(color, (150, 170, 74), 0.5), seed=seed))
        if food_name:
            draft.recipe(seed_name, _shapeless([f"$item:{food_name}"], f"$item:{seed_name}", 1, {"mode": "open"}))
    where = "cave floors" if underground else "the surface"
    grown = " A seed gives a full plant at once, so drops stay at 1. To raise them, give it growth in a module first, or it's free material." if seed_item else ""
    return draft.commit(f"{display}: a plant.",
                        f"Added {display} as a {family}, about {per_chunk:g} per chunk on {where} from Y {low} to {high}.{grown} Left to decide: what it's for.")


# Mobs


def _mob_spawn(spawn, category):
    if spawn is True:
        spawn = {}
    if not isinstance(spawn, dict):
        raise TemplateError(f"spawn must be an object like {{\"weight\": 10, \"biomes\": [\"#minecraft:is_forest\"]}}, or left out, not {spawn!r}.")
    given = {{"min_y": "minY", "max_y": "maxY"}.get(key, key): value for key, value in spawn.items()}
    underground = bool(given.get("underground", False))
    low, high = CAVE_Y if underground else SURFACE_Y
    filled = {"weight": 10, "light": "dark" if category == "monster" else "any", "minY": low, "maxY": high, "cap": 3, "biomes": [], **given, "underground": underground}
    for field in ("weight", "minY", "maxY", "cap"):
        filled[field] = _whole(filled[field], f"spawn {field}")
    if filled["light"] not in LIGHTS:
        raise TemplateError(f"spawn light must be one of {', '.join(LIGHTS)}, not {filled['light']!r}.")
    for biome in filled["biomes"]:
        if not isinstance(biome, str) or not PLAIN_ID.fullmatch(biome.removeprefix("#")):
            raise TemplateError(f"spawn biomes must be ids or #tags, not {biome!r}.")
    return filled


def _mob_drops(draft, drops, secondary, seed):
    """Drops name an item of this feature, or another's as other/name. A mob's can't be anything else, so a
    vanilla item stops the release, and an item nobody has declared yet gets made here, ready to be given a use."""
    if isinstance(drops, str):
        drops = {"item": drops}
    if not isinstance(drops, dict) or not isinstance(drops.get("item"), str):
        raise TemplateError(f"drops must be like {{\"item\": \"name\", \"count\": [1, 2]}}, not {drops!r}.")
    item = drops["item"].removeprefix("$item:")
    if ":" in item:
        raise TemplateError(f"A mob can only drop this world's items, not {item}, because only a block's drops can name a vanilla item.")
    count = _drop_count(drops.get("count", [1, 2]), "drops count")
    if "/" in item:
        _ingredient(draft, f"$item:{item}", "drops")
    elif not draft.has("items", item):
        draft.thing("items", item, {"display": drops.get("display", item.replace("_", " ").title()), "texture": item})
        draft.texture(item, tx.raw_chunk(secondary, seed=seed))
        draft.note(f"{item} didn't exist yet, so it's been added with plain art. It still needs a use.")
    return {"item": item, "count": count}


def new_mob(folder, *, name, display, category, behaviour, shape="humanoid", primary="#808080", secondary="#404040", health=20, damage=3, speed=0.25,
            drops=None, spawn=None, seed=1, width=None, height=None, follow_range=None, armor=None, eye=None, horns=False, model=None, node=None, phase=None):
    """A mob's stats, drops and spawning. Pass model with the name of one you've sculpted in assets/models, as every creature that
    matters should have. Without it you get a stand-in of a generic shape (humanoid, quadruped, slime or flying), only good for trying
    things out. category is monster or creature, and can't change once released. behaviour is hostile, neutral, passive or skittish.
    drops is like {"item": "name", "count": [1, 2]}. spawn is true or like {"weight": 10, "light": "dark", "cap": 3, "biomes":
    ["#minecraft:is_forest"]}, and leaving it out means only a module can summon it."""
    draft = _Draft(folder, node, phase)
    _check_name(name)
    _check_text(display, "display")
    if category not in MOB_CATEGORIES:
        raise TemplateError(f"category must be one of {', '.join(MOB_CATEGORIES)}, not {category!r}.")
    if behaviour not in MOB_BEHAVIOURS:
        raise TemplateError(f"behaviour must be one of {', '.join(MOB_BEHAVIOURS)}, not {behaviour!r}.")
    if shape not in bbmodel.KINDS:
        raise TemplateError(f"shape must be one of {', '.join(sorted(bbmodel.KINDS))}, not {shape!r}.")
    _check_color(primary, "primary")
    _check_color(secondary, "secondary")
    fights = behaviour in FIGHTERS
    default_width, default_height = MOB_SIZES[shape]
    entry = {"category": category, "display": display, "behaviour": behaviour, "health": _number(health, "health", above=True),
             # Only a fighter ever hits anything, so anything else saying it has damage would only mislead.
             "damage": _number(damage, "damage") if fights else 0, "speed": _number(speed, "speed", above=True),
             "width": _number(default_width if width is None else width, "width", above=True),
             "height": _number(default_height if height is None else height, "height", above=True)}
    if follow_range is not None:
        entry["followRange"] = _number(follow_range, "follow_range", above=True)
    if armor is not None:
        entry["armor"] = _number(armor, "armor")
    options = {"primary": primary, "secondary": secondary, "mood": "angry" if behaviour == "hostile" else "calm", "seed": seed}
    if eye is not None:
        _check_color(eye, "eye")
        options["eye"] = eye
    if horns:
        if shape not in ("humanoid", "quadruped"):
            raise TemplateError(f"A {shape} model has nowhere to put horns.")
        options["horns"] = True
    if model is None:
        # BIL puts names from the model into the pack, where anyone can read them, so this one means nothing.
        model_name = "m" + hashlib.sha256(f"{draft.id}/{name}".encode()).hexdigest()[:12]
        stand_in = bbmodel.KINDS[shape](model_name, **options)
        if fights:
            bbmodel.animate(stand_in, "attack", 0.5, ATTACKS[shape], loop="once")
        problems = bbmodel.check(stand_in)
        if problems:
            raise TemplateError(f"The model has problems: {'; '.join(problems)}")
        draft.file(f"assets/models/{model_name}.bbmodel", json.dumps(stand_in, separators=(",", ":")).encode())
        looks = f"Its model is a generic {shape} stand-in, {model_name}.bbmodel. Sculpt it a real one before this ships. "
    else:
        if not (draft.folder / "assets" / "models" / f"{model}.bbmodel").exists():
            raise TemplateError(f"There's no assets/models/{model}.bbmodel yet. Sculpt it first, or leave model out for a stand-in.")
        model_name = model
        looks = ""
    entry["model"] = model_name
    if drops is not None:
        entry["drops"] = _mob_drops(draft, drops, secondary, seed)
    if spawn is not None and spawn is not False:
        entry["spawn"] = _mob_spawn(spawn, category)
    draft.thing("mobs", name, entry)
    moves = "fights, with an attack animation" if fights else "doesn't fight"
    appears = "spawns on its own" if "spawn" in entry else "only appears if a module summons it"
    return draft.commit(f"{display}: a {behaviour} mob.",
                        f"Added {display}, a {behaviour} {category} that {moves} and {appears}. {looks}"
                        "Left to decide: its drops and spawning if they're not set, and anything it does through context.bindMob.")


# Machines


def _class_name(feature_id):
    return "".join(part.capitalize() for part in feature_id.split("_")) + "Module"


PANEL_MODULE = """package gm.feature.@ID@;

import gm.conduit.api.BlockBehavior;
import gm.conduit.api.MachineAttempt;
import gm.conduit.api.PanelBehavior;
import gm.conduit.api.PanelView;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.core.BlockPos;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;

import java.util.List;

/** A starting point: a screen with an input, an output and a button. Pressing it starts the machine on what's in the input, and it finishes by itself. */
public final class @CLASS@ implements ServerModule {
	private static final String MACHINE = "@MACHINE@";
	private static final int WORK_TICKS = 100;
	private static final int INPUT = 0;
	private static final int OUTPUT = 1;
	private ServerModuleContext context;

	@Override
	public void enable(ServerModuleContext context) {
		this.context = context;
		context.bindMachine(MACHINE, this::tick);
		context.bindBlock(MACHINE, new BlockBehavior() {
			@Override
			public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hit) {
				if (level.getBlockEntity(pos) instanceof SlotBlockEntity machine && player instanceof ServerPlayer serverPlayer) {
					context.openPanel(serverPlayer, MACHINE, machine, new Screen(machine));
				}
				return InteractionResult.SUCCESS;
			}
		});
	}

	private void tick(SlotBlockEntity machine) {
		CompoundTag data = machine.data();
		int left = data.getIntOr("left", 0);
		if (left == 0) {
			return;
		}
		data.putInt("left", left - 1);
		if (left == 1) {
			finish(machine);
		}
		machine.setChanged();
	}

	private void finish(SlotBlockEntity machine) {
		List<ItemStack> inputs = List.of(machine.getItem(INPUT));
		MachineAttempt attempt = this.context.attemptRecipe(null, MACHINE, inputs);
		if (attempt.succeeded() && machine.getItem(OUTPUT).isEmpty()) {
			attempt.consume(inputs);
			machine.setItem(OUTPUT, attempt.outputs().get(0).copy());
		}
	}

	/** One of these for each player looking at it. What's true is kept on the machine, and this only shows it. */
	private final class Screen implements PanelBehavior {
		private final SlotBlockEntity machine;

		Screen(SlotBlockEntity machine) {
			this.machine = machine;
		}

		@Override
		public void tick(PanelView panel) {
			int left = this.machine.data().getIntOr("left", 0);
			panel.setValue("progress", left == 0 ? 0 : 1 - (float) left / WORK_TICKS);
			panel.setText("state", left == 0 ? "Idle" : "Working");
			panel.setEnabled("start", left == 0 && !this.machine.getItem(INPUT).isEmpty());
		}

		@Override
		public void clicked(PanelView panel, String id, int row, boolean rightClick, boolean shift) {
			if (id.equals("start") && this.machine.data().getIntOr("left", 0) == 0) {
				this.machine.data().putInt("left", WORK_TICKS);
				this.machine.setChanged();
			}
		}
	}
}
"""


def _module_files(draft, name, display, template=MODULE):
    if draft.id in JAVA_WORDS or draft.id[0].isdigit():
        raise TemplateError(f"A module's package is gm.feature.<id>, and {draft.id} can't be a Java package name. Give the feature another id.")
    class_name = _class_name(draft.id)
    # json.dumps gives an escaped Java string too. It's quoted in the template, so the outer quotes go.
    spoken = json.dumps(display)[1:-1]
    source = (template.replace("@ID@", draft.id).replace("@CLASS@", class_name).replace("@MACHINE@", name).replace("@DISPLAY@", spoken))
    draft.file(f"server/src/main/java/gm/feature/{draft.id}/{class_name}.java", source.encode())
    draft.file("server/src/main/resources/module.properties", f"entry=gm.feature.{draft.id}.{class_name}\n".encode())
    return class_name


def _automation(entries):
    if not isinstance(entries, (list, tuple)):
        raise TemplateError(f"automation must be a list like [{{\"what\": \"mining\", \"per_minute\": 6}}], not {entries!r}.")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("what"), str):
            raise TemplateError(f"Each automation entry must be like {{\"what\": \"mining\", \"per_minute\": 6}}, not {entry!r}.")
        _number(entry.get("per_minute"), f"{entry['what']}'s per_minute", above=True)
    return [dict(entry) for entry in entries]


def _machine_panel(draft, name, display, casing, accent):
    """A working screen to start from: an input, an output, how far along it is, and a button. Its background is plain, and is there to be drawn over."""
    width, height = 176, 166
    buffer = io.BytesIO()
    tx.panel_back(casing, width, height, slots=[(56, 35), (116, 35)]).save(buffer, "PNG")
    draft.file(f"assets/panels/{name}_back.png", buffer.getvalue())
    accent_text = "#%02x%02x%02x" % tx.rgb(accent)
    draft.manifest.setdefault("panels", {})[name] = {
        "title": display, "width": width, "height": height, "background": f"{name}_back", "inventory": {"x": 8, "y": 84},
        "widgets": [
            {"type": "slot", "x": 56, "y": 35, "slot": 0},
            {"type": "slot", "x": 116, "y": 35, "slot": 1},
            {"type": "bar", "id": "progress", "x": 78, "y": 36, "width": 28, "height": 14, "color": accent_text, "text": "Progress"},
            {"type": "label", "id": "state", "x": 8, "y": 20, "text": "Idle"},
            {"type": "button", "id": "start", "x": 8, "y": 58, "width": 40, "height": 18, "text": "Start", "tooltip": "Starts it working"},
        ],
    }


def new_machine(folder, *, name, display, casing, accent, recipe_ingredients=None, automation=None, seed=1, mode="open", route=None,
                tool_level=None, model=None, node=None, phase=None, panel=False):
    """A machine block with art, and a server module under server/ that binds it, ticks lightly, keeps state in machine.data() and tries
    recipes when used. recipe_ingredients is a list of up to 9 tokens for a shapeless recipe; with none it has no source until you add one.
    automation is a list like [{"what": "machining", "per_minute": 20}]. Add its recipes to feature.json with "machine": "<name>".
    It's a textured cube unless you pass model with the name of one you've sculpted in assets/models, for one with moving parts.
    With panel=True it has an inventory, and a screen of its own to use it with, in place of trying what a player holds."""
    draft = _Draft(folder, node, phase)
    _check_name(name)
    _check_text(display, "display")
    _check_color(casing, "casing")
    _check_color(accent, "accent")
    if tool_level is not None and tool_level not in ("stone", "iron", "diamond"):
        raise TemplateError(f"tool_level must be stone, iron or diamond, not {tool_level!r}.")
    block = {"family": "machine", "display": display, "texture": name, "tool": "pickaxe"}
    if tool_level:
        block["tool_level"] = tool_level
    # In a model block's case, the front is its icon in an inventory.
    draft.texture(name, tx.machine("front", casing, accent, on=True, seed=seed))
    if model is None:
        block["faces"] = {"front": name}
        for face in ("side", "top", "bottom", "back"):
            block["faces"][face] = f"{name}_{face}"
            draft.texture(f"{name}_{face}", tx.machine(face, casing, accent, seed=seed))
    else:
        if not (draft.folder / "assets" / "models" / f"{model}.bbmodel").exists():
            raise TemplateError(f"There's no assets/models/{model}.bbmodel yet. Sculpt it first, or leave model out for a cube.")
        block.update(family="model", model=model)
    if panel:
        block["inventory"] = {"inputs": 1, "outputs": 1}
        _machine_panel(draft, name, display, casing, accent)
    draft.thing("blocks", name, block)
    source = "It needs a source before it can pass, so add a recipe. "
    if recipe_ingredients:
        if not isinstance(recipe_ingredients, (list, tuple)) or len(recipe_ingredients) > 9:
            raise TemplateError(f"recipe_ingredients must be a list of up to 9 tokens, not {recipe_ingredients!r}.")
        ingredients = [_ingredient(draft, value, "recipe_ingredients") for value in recipe_ingredients]
        draft.recipe(name, _shapeless(ingredients, f"$block:{name}", 1, _how_found(draft, mode, route)))
        source = ""
    if automation:
        draft.manifest.setdefault("automation", []).extend(_automation(automation))
    if (draft.folder / "server" / "src").exists():
        module = f"The module that's already in server/ needs its own context.bindMachine(\"{name}\", ...)."
    else:
        module = f"{_module_files(draft, name, display, PANEL_MODULE if panel else MODULE)} is its module, in server/."
    screen = f"Its screen is the panel {name} in feature.json, with assets/panels/{name}_back.png as a plain background for you to draw over. " if panel else ""
    return draft.commit(f"{display}: a machine.",
                        f"Added {display}. {module} {screen}{source}"
                        f"Left to decide: its recipes, with \"machine\": \"{name}\", and what its tick does. If it does anything by itself, declare that in automation.")


TEMPLATES = {"new_ore": new_ore, "new_tool_set": new_tool_set, "new_armor_set": new_armor_set, "new_plant": new_plant,
             "new_mob": new_mob, "new_machine": new_machine}
