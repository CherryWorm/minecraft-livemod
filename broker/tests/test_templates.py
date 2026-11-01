"""The starter templates. What they write has to pass everything that needs no server, at every tier, alone and together.

Usage: python3 -m unittest broker.tests.test_templates
"""
import ast
import hashlib
import inspect
import json
import pathlib
import re
import shutil
import sys
import tempfile
import time
import unittest

from PIL import Image

from assetkit import bbmodel
from broker import bundles
from broker.gates import GateFailed, advice, balance, bytecode, progression, static
from orchestrator import progression as graph
from orchestrator import templates
from orchestrator.templates import TemplateError, new_armor_set, new_machine, new_mob, new_ore, new_plant, new_tool_set

REPO = pathlib.Path(__file__).resolve().parents[2]
# A copy of what's in SlotFamily, NeutralSlots and SlotMobs, because mods/ isn't always beside this. A test compares them.
POOL = {"families": {"stone": {"first": 1000, "count": 150}, "ore": {"first": 1200, "count": 120}, "deep_ore": {"first": 1400, "count": 60},
                     "metal": {"first": 1500, "count": 50}, "wood": {"first": 1600, "count": 60}, "soil": {"first": 1700, "count": 40},
                     "glow": {"first": 1800, "count": 40}, "machine": {"first": 1900, "count": 80}, "cutout": {"first": 2000, "count": 40},
                     "plant": {"first": 2100, "count": 5}, "glow_plant": {"first": 2110, "count": 2}, "tinted_plant": {"first": 2150, "count": 12},
                     "model": {"first": 2300, "count": 200}, "glow_ore": {"first": 2500, "count": 20}, "crop": {"first": 2200, "count": 7},
                     "connected": {"first": 2600, "count": 2}, "ladder": {"first": 2700, "count": 10}, "facing": {"first": 3000, "count": 40}, "facing_machine": {"first": 3100, "count": 40}},
        "item_count": 1200, "effect_count": 100, "fluid_count": 16, "mobs": {"monster": 240, "creature": 480}, "entities": {"projectiles": 240, "vehicles": 120, "props": 480}}
DATA_FORMAT = 88
TIERS = balance.TIERS
VANILLA_TIERS = tuple(balance.TOOLS)
EXACT_ID = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
INGOT = "minecraft:iron_ingot"


def fake_biome(base):
    return {"effects": {}, "attributes": {}, "temperature": 0.8, "downfall": 0.4, "has_precipitation": True}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def folder_print(folder):
    """Every file under a folder and its contents, for telling whether anything changed."""
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.rglob("*")) if path.is_file()}


class Case(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = pathlib.Path(holder.name)
        self.features = self.base / "features"
        self.features.mkdir()

    def at(self, feature="thing"):
        return self.features / feature

    def manifest(self, feature="thing"):
        return read(self.at(feature) / "feature.json")

    def release(self):
        """Everything a release goes through that needs no server. static.run ends with balance.run."""
        features = bundles.load_features(self.features)
        ledger = bundles.assign_slots(features, bundles.empty_ledger(), POOL)
        content = self.base / "content"
        if content.exists():
            shutil.rmtree(content)
        bundles.render(features, ledger, content, DATA_FORMAT, fake_biome)
        try:
            static.run(features, bundles.empty_ledger(), ledger, POOL, content)
        except GateFailed as error:
            self.fail(f"Gate {error.gate} refused it:\n{error.message}")
        self.check_the_server_can_read(ledger, content)
        return features, ledger, content

    def check_the_server_can_read(self, ledger, content):
        """What the gates don't look at but the mod's own parsers need. Most of these failing would lose every patch or item."""
        config = content / "config"
        patches = read(config / "ore_patches.json")
        self.assertEqual(len({patch["id"] for patch in patches}), len(patches), "ore ids must be unique")
        for patch in patches:
            for field in ("veinsPerChunk", "veinSize", "minY", "maxY"):
                self.assertIs(type(patch[field]), int, f"OrePatch reads {field} with Gson into an int: {patch}")
            self.assertTrue(1 <= patch["veinSize"] <= 16, patch)
            self.assertGreaterEqual(patch["veinsPerChunk"], 1, patch)
            self.assertLess(patch["minY"], patch["maxY"], patch)
            for block in patch["replaces"] + patch["biomes"]:
                self.assertRegex(block, EXACT_ID, "OrePatch can't read tags")
        surface = read(config / "surface_patches.json")
        self.assertEqual(len({patch["id"] for patch in surface}), len(surface), "plant ids must be unique")
        for patch in surface:
            self.assertTrue(patch["on"], patch)
            for block in patch["on"] + patch.get("biomes", []):
                self.assertRegex(block, EXACT_ID, "SurfacePatch can't read tags")
            self.assertIs(type(patch["minY"]), int, patch)
            self.assertIs(type(patch["maxY"]), int, patch)
            self.assertIs(type(patch["underground"]), bool, patch)
            self.assertGreater(patch["perChunk"], 0, patch)
        for slot, mob in read(config / "mobs.json").items():
            # MobDefinition.parse calls getAsDouble on these without checking they're there.
            for field in ("model", "behaviour", "health", "damage", "speed", "width", "height"):
                self.assertIn(field, mob, slot)
            if "spawn" in mob:
                for field in ("weight", "light", "minY", "maxY", "cap"):
                    self.assertIn(field, mob["spawn"], slot)
                self.assertIn(mob["spawn"]["light"], ("dark", "bright", "any"))
            model = read(config / "models" / f"{mob['model']}.bbmodel")
            self.assertEqual(bbmodel.check(model), [], slot)
            names = {animation["name"] for animation in model["animations"]}
            self.assertLessEqual({"idle", "walk"}, names)
            if mob["behaviour"] in ("hostile", "neutral"):
                self.assertIn("attack", names, "SlotMob plays attack when it hits something")
        slots = {f"gm:{entry['slot']}" for table in ("blocks", "items", "mobs") for entry in ledger[table].values()}
        defaults = read(config / "item_defaults.json")
        for slot, item in defaults.items():
            self.assertIn(slot, slots)
            self.assertNotIn("$", json.dumps(item), "every token must be resolved")
            for block in item.get("places", {}).get("on", []):
                self.assertRegex(block, EXACT_ID, "readPlacement can't read tags")
            components = item.get("components", {})
            self.assertTrue(all(name.startswith("minecraft:") for name in components), components)
            if "minecraft:max_damage" in components:
                # Without damage the stack never wears out, and a stack over 1 can't be damaged at all.
                self.assertEqual(components["minecraft:damage"], 0, slot)
                self.assertEqual(components["minecraft:max_stack_size"], 1, slot)
        for path in (content / "datapack").rglob("recipe/*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("$", text, "every token must be resolved")
            for used in re.findall(r"gm:[a-z0-9]+", text):
                self.assertIn(used, slots, text)
        language = read(content / "pack" / "assets" / "gm" / "lang" / "en_us.json")
        for table, kind in (("blocks", "block"), ("items", "item")):
            for key, entry in ledger[table].items():
                self.assertIn(f"{kind}.gm.{entry['slot']}", language, key)
                folder = "textures/" + kind
                self.assertTrue((content / "pack" / "assets" / "gm" / folder / f"{entry['slot']}.png").exists(), key)


class TheCopiedNumbers(unittest.TestCase):
    """The agent's container has no broker/, so the templates keep their own copy of these."""

    def test_they_match_the_gate(self):
        self.assertEqual(templates.TIERS, balance.TIERS)
        self.assertEqual(templates.ORE_TOLERANCE, balance.ORE_TOLERANCE)
        self.assertEqual(templates.ROCK, balance.ROCK)
        self.assertEqual(templates.ARMOR_DURABILITY, balance.ARMOR_DURABILITY[:4])
        self.assertEqual(templates.ARMOR_SLOTS, balance.SLOTS[:4])
        for tier, value in balance.ORE_CURVE.items():
            self.assertAlmostEqual(templates.ORE_CURVE[tier], value, delta=0.01, msg=tier)

    def test_tools_are_vanillas_at_vanillas_tiers(self):
        for tier, (durability, speed, axe_hit, sword_hit) in balance.TOOLS.items():
            with self.subTest(tier):
                found_durability, found_speed, kinds = templates.tool_numbers(tier)
                self.assertEqual((found_durability, found_speed), (durability, speed))
                self.assertEqual(1 + kinds["axe"][0], axe_hit)
                self.assertEqual(1 + kinds["sword"][0], sword_hit)

    def test_armor_is_vanillas_at_vanillas_tiers(self):
        for tier, (factor, points, toughness, knockback) in balance.ARMOR.items():
            for index, slot in enumerate(templates.ARMOR_SLOTS):
                with self.subTest(f"{tier} {slot}"):
                    self.assertEqual(templates.armor_numbers(tier, slot), (factor * balance.ARMOR_DURABILITY[index], points[index], toughness, knockback))

    def test_beyond_is_past_netherite_and_under_its_limit(self):
        netherite_durability, netherite_speed, netherite_kinds = templates.tool_numbers("netherite")
        durability, speed, kinds = templates.tool_numbers("beyond")
        self.assertGreater(durability, netherite_durability)
        self.assertGreater(speed, netherite_speed)
        self.assertGreater(kinds["sword"][0], netherite_kinds["sword"][0])
        limits = balance._limits("beyond", None, False)
        self.assertLess(durability, limits["durability"])
        self.assertLess(speed, limits["mining_speed"])
        for slot in templates.ARMOR_SLOTS:
            limits = balance._limits("beyond", slot, True)
            found = templates.armor_numbers("beyond", slot)
            self.assertLess(found[0], limits["durability"])
            self.assertLess(found[1], limits["armor"])
            self.assertLess(found[2], limits["armor_toughness"])
            self.assertLess(found[3], limits["knockback_resistance"])

    def test_mythic_is_about_three_times_netherite(self):
        netherite_durability, netherite_speed, netherite_kinds = templates.tool_numbers("netherite")
        durability, speed, kinds = templates.tool_numbers("mythic")
        self.assertAlmostEqual(durability / netherite_durability, 3)
        self.assertAlmostEqual(speed / netherite_speed, 3)
        self.assertAlmostEqual((1 + kinds["sword"][0]) / (1 + netherite_kinds["sword"][0]), 3)
        self.assertAlmostEqual(templates.armor_numbers("mythic", "chest")[1] / templates.armor_numbers("netherite", "chest")[1], 3)

    def test_the_pool_above_is_the_real_one(self):
        if not (REPO / "mods" / "conduit").exists():
            self.skipTest("mods/ isn't in this copy")
        self.assertEqual(POOL, bundles.read_pool(REPO))


class TheModule(unittest.TestCase):
    def test_it_only_imports_the_standard_library_and_assetkit(self):
        # The agent's container runs this, and has no broker/. The tools' host imports the SDK, so this shouldn't have to.
        tree = ast.parse(pathlib.Path(templates.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                root = name.split(".")[0]
                self.assertTrue(root == "assetkit" or root in sys.stdlib_module_names, name)

    def test_the_comment_says_why_the_numbers_are_copied(self):
        self.assertIn("broker/ isn't in the agent's container", pathlib.Path(templates.__file__).read_text(encoding="utf-8"))

    def test_signatures_keep_the_names_they_were_asked_for(self):
        wanted = {
            "new_ore": "name display color tier deep biomes min_y max_y stone_color seed",
            "new_tool_set": "material display tier ingredient color kinds mode route seed",
            "new_armor_set": "material display tier ingredient color slots mode route seed",
            "new_plant": "name display color family kind on per_chunk min_y max_y underground biomes food seed_item seed",
            "new_mob": "name display category behaviour shape primary secondary health damage speed drops spawn seed",
            "new_machine": "name display casing accent recipe_ingredients automation seed",
        }
        self.assertEqual(set(templates.TEMPLATES), set(wanted))
        for name, function in templates.TEMPLATES.items():
            parameters = inspect.signature(function).parameters
            self.assertEqual(next(iter(parameters)), "folder")
            for other in list(parameters)[1:]:
                self.assertIs(parameters[other].kind, inspect.Parameter.KEYWORD_ONLY, f"{name} {other}")
            self.assertLessEqual({*wanted[name].split(), "node", "phase"}, set(parameters), name)
            self.assertEqual(parameters["seed"].default, 1, name)
            self.assertTrue(function.__doc__, f"{name}'s docstring is its description as a builder's tool")


class Ores(Case):
    def test_every_tier_alone_and_with_a_deep_variant(self):
        for tier in TIERS:
            for deep in (False, True):
                with self.subTest(f"{tier} deep={deep}"):
                    folder = self.at(f"ore_{tier}_{deep}".lower())
                    result = new_ore(folder, name="tin", display="Tin", color="#d8c8a0", tier=tier, deep=deep)
                    self.assertTrue(result["summary"])
                    self.release()
                    shutil.rmtree(folder)

    def yields(self, feature="thing"):
        """Each block's yield per chunk, the way the gate measures it."""
        manifest = self.manifest(feature)
        found = {}
        for ore in manifest["ores"]:
            count = manifest["blocks"][ore["block"]]["drops"]["count"]
            found[ore["block"]] = balance._expected(ore["veinsPerChunk"], ore["veinSize"], ore["minY"], ore["maxY"]) * sum(count) / 2
        return found

    def test_a_lone_ore_lands_near_the_vanilla_curve(self):
        for tier in TIERS:
            with self.subTest(tier):
                folder = self.at(tier)
                new_ore(folder, name="tin", display="Tin", color="#d8c8a0", tier=tier)
                amount = self.yields(tier)["tin_ore"]
                self.assertLessEqual(abs(amount - balance.ORE_CURVE[tier]) / balance.ORE_CURVE[tier], 0.21, amount)

    def test_a_deep_pair_lands_near_it_together_and_passes_alone(self):
        for tier in TIERS:
            with self.subTest(tier):
                folder = self.at(tier)
                new_ore(folder, name="tin", display="Tin", color="#d8c8a0", tier=tier, deep=True)
                amounts = self.yields(tier)
                curve = balance.ORE_CURVE[tier]
                self.assertEqual(set(amounts), {"tin_ore", "deep_tin_ore"})
                for amount in amounts.values():
                    self.assertGreaterEqual(amount, curve / balance.ORE_TOLERANCE)
                # One whole vein of one block is as rare as this can go, which is what the top two tiers hit.
                self.assertLessEqual(sum(amounts.values()) / curve, 1.3 if tier not in ("beyond", "mythic") else 1.61)

    def test_what_it_makes(self):
        result = new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron", deep=True)
        manifest = self.manifest()
        self.assertEqual(set(manifest["blocks"]), {"tin_ore", "deep_tin_ore", "tin_block"})
        self.assertEqual(set(manifest["items"]), {"raw_tin", "tin_ingot"})
        self.assertEqual(manifest["blocks"]["tin_ore"]["family"], "ore")
        self.assertEqual(manifest["blocks"]["deep_tin_ore"]["family"], "deep_ore")
        self.assertEqual(manifest["blocks"]["tin_block"]["family"], "metal")
        self.assertEqual(manifest["blocks"]["tin_ore"]["drops"]["item"], "raw_tin")
        types = {name: recipe["json"]["type"] for name, recipe in manifest["recipes"].items()}
        self.assertEqual(types, {"tin_ingot_smelting": "minecraft:smelting", "tin_ingot_blasting": "minecraft:blasting",
                                 "tin_block": "minecraft:crafting_shaped", "tin_ingot_from_block": "minecraft:crafting_shapeless"})
        self.assertLessEqual({"tin_ore", "deep_tin_ore", "raw_tin", "tin_ingot", "tin_block", "tin_ingot_smelting"}, set(result["added"]))
        self.assertEqual(manifest["id"], "thing")
        self.assertTrue(manifest["summary"])
        self.release()

    def test_every_recipe_is_open_because_a_furnace_cant_be_locked(self):
        new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        self.assertEqual({recipe["mode"] for recipe in self.manifest()["recipes"].values()}, {"open"})

    def test_ingot_and_block_turn_back_and_forth_for_free_and_no_more(self):
        new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        manifest = self.manifest()
        self.assertEqual(manifest["recipes"]["tin_ingot_from_block"]["json"]["result"]["count"], 9)
        self.assertEqual("".join(manifest["recipes"]["tin_block"]["json"]["pattern"]), "X" * 9)
        features = bundles.load_features(self.features)
        self.assertEqual(balance._check_cycles(features, balance._read_recipes(features)), [])

    def test_tool_level_follows_the_tier(self):
        wanted = {"wood": None, "stone": "stone", "iron": "stone", "diamond": "iron", "netherite": "diamond", "beyond": "diamond", "mythic": "diamond"}
        for tier, level in wanted.items():
            with self.subTest(tier):
                new_ore(self.at(tier), name="tin", display="Tin", color="#d8c8a0", tier=tier)
                blocks = self.manifest(tier)["blocks"]
                self.assertEqual(blocks["tin_ore"].get("tool_level"), level)
                self.assertEqual(blocks["tin_block"].get("tool_level"), level)
                self.assertEqual(blocks["tin_ore"]["tool"], "pickaxe", "these families drop nothing without the right tool")
                self.assertEqual(blocks["tin_block"]["tool"], "pickaxe")

    def test_depth_gets_deeper_with_the_tier(self):
        tops = []
        for tier in TIERS:
            new_ore(self.at(tier), name="tin", display="Tin", color="#d8c8a0", tier=tier)
            tops.append(self.manifest(tier)["ores"][0]["maxY"])
        self.assertEqual(tops, sorted(tops, reverse=True))

    def test_a_lone_ore_only_replaces_the_rock_it_looks_like(self):
        new_ore(self.at("high"), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        new_ore(self.at("low"), name="tin", display="Tin", color="#d8c8a0", tier="diamond")
        new_ore(self.at("both"), name="tin", display="Tin", color="#d8c8a0", tier="iron", min_y=-30, max_y=30)
        self.assertNotIn("minecraft:deepslate", self.manifest("high")["ores"][0]["replaces"])
        self.assertNotIn("minecraft:stone", self.manifest("low")["ores"][0]["replaces"])
        self.assertEqual(self.manifest("low")["blocks"]["tin_ore"]["family"], "deep_ore")
        self.assertLessEqual({"minecraft:stone", "minecraft:deepslate"}, set(self.manifest("both")["ores"][0]["replaces"]))
        self.release()

    def test_a_pair_splits_by_rock(self):
        new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron", deep=True)
        stone, deep = self.manifest()["ores"]
        self.assertGreaterEqual(stone["minY"], 0)
        self.assertLess(deep["minY"], 0)
        self.assertIn("minecraft:stone", stone["replaces"])
        self.assertNotIn("minecraft:deepslate", stone["replaces"])
        self.assertIn("minecraft:deepslate", deep["replaces"])
        self.assertNotIn("minecraft:stone", deep["replaces"])

    def test_a_given_range_still_lands_on_the_curve(self):
        # Most of the first is up in the air, and the gate only counts what's inside rock.
        for low, high in ((-64, 320), (-10, 10), (30, 120), (-64, 64)):
            with self.subTest(f"{low} to {high}"):
                folder = self.at(f"range_{abs(low)}_{high}")
                new_ore(folder, name="tin", display="Tin", color="#d8c8a0", tier="iron", min_y=low, max_y=high)
                self.assertLessEqual(abs(self.yields(folder.name)["tin_ore"] - balance.ORE_CURVE["iron"]) / balance.ORE_CURVE["iron"], 0.1)
        self.release()

    def test_drop_count_lowers_the_veins_rather_than_the_yield(self):
        new_ore(self.at("one"), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        new_ore(self.at("many"), name="tin", display="Tin", color="#d8c8a0", tier="iron", drop_count=[2, 4])
        one, many = self.manifest("one")["ores"][0], self.manifest("many")["ores"][0]
        self.assertLess(many["veinsPerChunk"] * many["veinSize"], one["veinsPerChunk"] * one["veinSize"])
        self.assertLessEqual(abs(self.yields("many")["tin_ore"] - balance.ORE_CURVE["iron"]) / balance.ORE_CURVE["iron"], 0.1)
        self.release()

    def test_options_reach_the_entry(self):
        new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron", biomes=["minecraft:plains"], vein_size=5, stone_color="#8a7a70", tool_level="iron")
        manifest = self.manifest()
        self.assertEqual(manifest["ores"][0]["biomes"], ["minecraft:plains"])
        self.assertEqual(manifest["ores"][0]["veinSize"], 5)
        self.assertEqual(manifest["blocks"]["tin_ore"]["tool_level"], "iron")
        self.release()

    def test_ids_are_unique_across_features(self):
        # Chunks remember ids across every feature, so a second feature's tin_ore_v1 would never generate.
        new_ore(self.at("one"), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        new_ore(self.at("two"), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        self.assertNotEqual(self.manifest("one")["ores"][0]["id"], self.manifest("two")["ores"][0]["id"])
        self.release()

    def test_veins_are_whole_at_every_tier_and_range(self):
        for tier in TIERS:
            for deep in (False, True):
                folder = self.at(f"whole_{tier}_{deep}".lower())
                new_ore(folder, name="tin", display="Tin", color="#d8c8a0", tier=tier, deep=deep)
                for ore in self.manifest(folder.name)["ores"]:
                    self.assertIs(type(ore["veinsPerChunk"]), int, ore)
                    self.assertIs(type(ore["veinSize"]), int, ore)


class Tools(Case):
    def test_every_tier_and_kind(self):
        for tier in TIERS:
            for kind in templates.TOOL_KINDS:
                with self.subTest(f"{tier} {kind}"):
                    folder = self.at("tools")
                    new_tool_set(folder, material="tin", display="Tin", tier=tier, ingredient=INGOT, color="#d8c8a0", kinds=[kind])
                    self.release()
                    shutil.rmtree(folder)

    def test_a_full_set_at_every_tier(self):
        for tier in TIERS:
            with self.subTest(tier):
                folder = self.at("tools")
                result = new_tool_set(folder, material="tin", display="Tin", tier=tier, ingredient=INGOT, color="#d8c8a0")
                # A recipe has its item's name, and that's reported once.
                self.assertEqual(set(result["added"]), {f"tin_{kind}" for kind in templates.TOOL_KINDS})
                self.assertEqual(set(self.manifest("tools")["recipes"]), set(result["added"]))
                self.release()
                shutil.rmtree(folder)

    def test_what_a_tool_carries(self):
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0")
        items = self.manifest()["items"]
        pick = items["tin_pickaxe"]
        self.assertEqual(pick["tier"], "iron")
        self.assertIs(pick["handheld"], True)
        self.assertEqual(pick["display"], "Tin Pickaxe")
        self.assertEqual(pick["texture"], "tin_pickaxe")
        components = pick["components"]
        self.assertEqual(components["minecraft:max_damage"], 250)
        self.assertEqual(components["minecraft:damage"], 0)
        self.assertEqual(components["minecraft:max_stack_size"], 1)
        self.assertEqual(components["minecraft:tool"]["rules"][0], {"blocks": "#minecraft:incorrect_for_iron_tool", "correct_for_drops": False})
        self.assertEqual(components["minecraft:tool"]["rules"][1], {"blocks": "#minecraft:mineable/pickaxe", "speed": 6.0, "correct_for_drops": True})
        self.assertEqual(components["minecraft:repairable"], {"items": INGOT})
        # The numbers the game's item report gives for iron_pickaxe and iron_sword.
        modifiers = {modifier["type"]: modifier for modifier in components["minecraft:attribute_modifiers"]}
        self.assertEqual(modifiers["minecraft:attack_damage"]["amount"], 3)
        self.assertEqual(modifiers["minecraft:attack_speed"]["amount"], -2.8)
        self.assertEqual(modifiers["minecraft:attack_damage"]["slot"], "mainhand")
        self.assertEqual(modifiers["minecraft:attack_damage"]["operation"], "add_value")
        sword = {modifier["type"]: modifier["amount"] for modifier in items["tin_sword"]["components"]["minecraft:attribute_modifiers"]}
        self.assertEqual(sword, {"minecraft:attack_damage": 5, "minecraft:attack_speed": -2.4})
        self.assertEqual(items["tin_axe"]["components"]["minecraft:block_transformer"], "minecraft:axe")
        self.assertEqual(items["tin_axe"]["components"]["minecraft:weapon"], {"item_damage_per_attack": 2, "disable_blocking_for_seconds": 5.0})
        self.assertEqual(items["tin_hoe"]["components"]["minecraft:block_transformer"], "minecraft:hoe")
        self.assertEqual(items["tin_shovel"]["components"]["minecraft:block_transformer"], "minecraft:shovel")
        self.assertNotIn("minecraft:block_transformer", pick["components"])

    def test_past_netherite_the_tag_stays_on_netherites(self):
        for tier in ("netherite", "beyond", "mythic"):
            new_tool_set(self.at(tier), material="tin", display="Tin", tier=tier, ingredient=INGOT, color="#d8c8a0", kinds=["pickaxe"])
            rules = self.manifest(tier)["items"]["tin_pickaxe"]["components"]["minecraft:tool"]["rules"]
            self.assertEqual(rules[0]["blocks"], "#minecraft:incorrect_for_netherite_tool")

    def test_each_kind_has_a_recipe_for_its_shape(self):
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0")
        recipes = self.manifest()["recipes"]
        self.assertEqual(recipes["tin_pickaxe"]["json"]["pattern"], ["XXX", " # ", " # "])
        self.assertEqual(recipes["tin_pickaxe"]["json"]["key"], {"X": INGOT, "#": "minecraft:stick"})
        self.assertEqual(recipes["tin_pickaxe"]["json"]["result"], {"id": "$item:tin_pickaxe", "count": 1})
        self.assertEqual(recipes["tin_pickaxe"]["mode"], "open")

    def test_a_tag_works_as_an_ingredient_and_isnt_used_for_repairs(self):
        # Only an item tag would parse, and a bad one in repairable would lose every item's defaults.
        new_tool_set(self.at(), material="oak", display="Oak", tier="wood", ingredient="#minecraft:planks", color="#a0804a")
        self.assertNotIn("minecraft:repairable", self.manifest()["items"]["oak_pickaxe"]["components"])
        self.release()

    def test_a_custom_handle(self):
        new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient="$item:tin_ingot", color="#d8c8a0", handle_ingredient="minecraft:blaze_rod", handle_color="#e0a040")
        self.assertEqual(self.manifest()["recipes"]["tin_sword"]["json"]["key"]["#"], "minecraft:blaze_rod")
        self.release()


class Armor(Case):
    def test_every_tier_and_slot(self):
        for tier in TIERS:
            for slot in templates.ARMOR_SLOTS:
                with self.subTest(f"{tier} {slot}"):
                    folder = self.at("armor")
                    new_armor_set(folder, material="tin", display="Tin", tier=tier, ingredient=INGOT, color="#d8c8a0", slots=[slot])
                    self.release()
                    shutil.rmtree(folder)

    def test_a_full_set_at_every_tier(self):
        for tier in TIERS:
            with self.subTest(tier):
                folder = self.at("armor")
                new_armor_set(folder, material="tin", display="Tin", tier=tier, ingredient=INGOT, color="#d8c8a0")
                self.assertEqual(len(self.manifest("armor")["items"]), 4)
                self.release()
                shutil.rmtree(folder)

    def test_what_a_piece_carries(self):
        new_armor_set(self.at(), material="tin", display="Tin", tier="diamond", ingredient=INGOT, color="#d8c8a0")
        items = self.manifest()["items"]
        self.assertEqual(set(items), {"tin_helmet", "tin_chestplate", "tin_leggings", "tin_boots"})
        chest = items["tin_chestplate"]
        self.assertEqual(chest["tier"], "diamond")
        self.assertNotIn("handheld", chest)
        components = chest["components"]
        self.assertEqual(components["minecraft:max_damage"], 528)
        self.assertEqual(components["minecraft:damage"], 0)
        self.assertEqual(components["minecraft:max_stack_size"], 1)
        self.assertEqual(components["minecraft:equippable"],
                         {"slot": "chest", "asset_id": "$equipment:tin", "equip_sound": "minecraft:item.armor.equip_diamond"})
        amounts = {modifier["type"]: modifier["amount"] for modifier in components["minecraft:attribute_modifiers"]}
        self.assertEqual(amounts, {"minecraft:armor": 8, "minecraft:armor_toughness": 2})
        for modifier in components["minecraft:attribute_modifiers"]:
            self.assertEqual(modifier["slot"], "chest")
            self.assertEqual(modifier["operation"], "add_value")

    def test_each_piece_has_its_own_modifier_id(self):
        # The game replaces a modifier with the same id, so sharing one would make a full set count as one piece.
        new_armor_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0")
        ids = [item["components"]["minecraft:attribute_modifiers"][0]["id"] for item in self.manifest()["items"].values()]
        self.assertEqual(len(set(ids)), 4)

    def test_it_draws_what_it_looks_like_worn(self):
        result = new_armor_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0")
        manifest = self.manifest()
        self.assertEqual(manifest["items"]["tin_boots"]["components"]["minecraft:equippable"]["asset_id"], "$equipment:tin")
        self.assertNotIn("host_requests", manifest)
        self.assertIn("raw/assets/gm/textures/entity/equipment/", result["summary"])
        root = self.at()
        with Image.open(root / "raw/assets/gm/textures/entity/equipment/humanoid/tin.png") as image:
            self.assertEqual(image.size, (64, 32))
        with Image.open(root / "raw/assets/gm/textures/entity/equipment/humanoid_leggings/tin.png") as image:
            self.assertEqual(image.size, (64, 32))
        self.assertEqual(json.loads((root / "raw/assets/gm/equipment/tin.json").read_text(encoding="utf-8"))["layers"]["humanoid"], [{"texture": "$texture:tin"}])
        self.release()

    def test_a_second_call_for_more_pieces_keeps_the_same_art(self):
        new_armor_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", slots=["head"])
        new_armor_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", slots=["feet"])
        self.assertEqual(self.manifest()["items"]["tin_boots"]["components"]["minecraft:equippable"]["asset_id"], "$equipment:tin")
        self.release()

    def test_worn_look_can_be_chosen(self):
        new_armor_set(self.at("gold"), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", worn_look="minecraft:gold")
        new_armor_set(self.at("bare"), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", worn_look=None)
        self.assertEqual(self.manifest("gold")["items"]["tin_boots"]["components"]["minecraft:equippable"]["asset_id"], "minecraft:gold")
        self.assertEqual(self.manifest("bare")["items"]["tin_boots"]["components"]["minecraft:equippable"], {"slot": "feet"})
        self.release()

    def test_an_extra_ingredient_goes_in_the_gap(self):
        new_armor_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", extra_ingredient="minecraft:blaze_rod")
        recipes = self.manifest()["recipes"]
        self.assertEqual(recipes["tin_helmet"]["json"]["pattern"], ["XXX", "XEX"])
        self.assertEqual(recipes["tin_chestplate"]["json"]["pattern"], ["XEX", "XXX", "XXX"])
        self.assertEqual(recipes["tin_leggings"]["json"]["pattern"], ["XXX", "XEX", "X X"])
        self.assertEqual(recipes["tin_boots"]["json"]["pattern"], ["XEX", "X X"])
        self.assertEqual(recipes["tin_boots"]["json"]["key"]["E"], "minecraft:blaze_rod")
        self.release()

    def test_the_icons_are_all_the_right_size(self):
        for slot, (_, _, _, icon) in templates.ARMOR_PIECES.items():
            self.assertEqual(len(icon), 16, slot)
            self.assertEqual({len(row) for row in icon}, {16}, slot)
            self.assertTrue(set("".join(icon)) <= set(".12345"), slot)


class Plants(Case):
    def test_every_family_and_kind(self):
        for family in templates.PLANT_FAMILIES:
            for kind in templates.PLANT_KINDS:
                with self.subTest(f"{family} {kind}"):
                    folder = self.at("plant")
                    new_plant(folder, name="moss", display="Moss", color="#d04060", family=family, kind=kind)
                    self.release()
                    shutil.rmtree(folder)

    def test_a_plant_with_a_seed_comes_from_its_own_drop(self):
        result = new_plant(self.at(), name="moss", display="Moss", color="#d04060")
        manifest = self.manifest()
        self.assertEqual(manifest["blocks"]["moss"]["family"], "plant")
        self.assertEqual(manifest["blocks"]["moss"]["drops"], {"item": "moss_seeds", "count": [1, 1]})
        self.assertEqual(manifest["items"]["moss_seeds"]["places"], {"block": "$block:moss", "on": ["minecraft:grass_block"]})
        entry = manifest["plants"][0]
        self.assertEqual(entry["id"], "thing_moss_v1")
        self.assertEqual(entry["block"], "moss")
        self.assertEqual(entry["on"], ["minecraft:grass_block"])
        self.assertEqual(entry["perChunk"], 1.0)
        self.assertIs(entry["underground"], False)
        self.assertLessEqual({"moss", "moss_seeds", "thing_moss_v1"}, set(result["added"]))
        self.release()

    def test_a_food_drops_and_the_seed_comes_from_the_food(self):
        new_plant(self.at(), name="moss", display="Moss", color="#d04060", food={"nutrition": 4, "saturation": 2.4})
        manifest = self.manifest()
        food = manifest["items"]["moss_fruit"]
        # Eating these is what m8_test proves on a real client.
        self.assertEqual(food["components"]["minecraft:food"], {"nutrition": 4, "saturation": 2.4})
        self.assertIn("consume_seconds", food["components"]["minecraft:consumable"])
        self.assertEqual(manifest["blocks"]["moss"]["drops"]["item"], "moss_fruit")
        self.assertEqual(manifest["recipes"]["moss_seeds"]["json"]["ingredients"], ["$item:moss_fruit"])
        self.assertEqual(manifest["recipes"]["moss_seeds"]["json"]["result"], {"id": "$item:moss_seeds", "count": 1})
        self.release()

    def test_a_seed_and_its_drop_cant_multiply(self):
        # A seed gives a full plant at once, so more than one back per plant would be free material.
        new_plant(self.at("seed"), name="moss", display="Moss", color="#d04060")
        new_plant(self.at("food"), name="moss", display="Moss", color="#d04060", food={"nutrition": 4, "saturation": 2.4})
        self.assertEqual(self.manifest("seed")["blocks"]["moss"]["drops"]["count"], [1, 1])
        self.assertEqual(self.manifest("food")["blocks"]["moss"]["drops"]["count"], [1, 1])

    def test_no_seed(self):
        new_plant(self.at("alone"), name="moss", display="Moss", color="#d04060", seed_item=False)
        new_plant(self.at("eaten"), name="moss", display="Moss", color="#d04060", seed_item=False, food={"nutrition": 4, "saturation": 2.4})
        self.assertNotIn("drops", self.manifest("alone")["blocks"]["moss"])
        self.assertNotIn("items", self.manifest("alone"))
        self.assertEqual(set(self.manifest("eaten")["items"]), {"moss_fruit"})
        self.assertNotIn("recipes", self.manifest("eaten"))
        self.release()

    def test_food_can_be_described_further(self):
        food = {"nutrition": 2, "saturation": 1.2, "name": "dew", "display": "Dew", "kind": "berries", "consume_seconds": 0.8, "can_always_eat": True}
        new_plant(self.at(), name="moss", display="Moss", color="#d04060", food=food)
        item = self.manifest()["items"]["dew"]
        self.assertEqual(item["display"], "Dew")
        self.assertEqual(item["components"]["minecraft:consumable"], {"consume_seconds": 0.8})
        self.assertIs(item["components"]["minecraft:food"]["can_always_eat"], True)
        self.release()

    def test_underground_defaults(self):
        new_plant(self.at(), name="moss", display="Moss", color="#d04060", underground=True)
        entry = self.manifest()["plants"][0]
        self.assertIs(entry["underground"], True)
        self.assertLess(entry["minY"], 0)
        self.assertIn("minecraft:stone", entry["on"])
        self.assertEqual(self.manifest()["items"]["moss_seeds"]["places"]["on"], entry["on"])
        self.release()

    def test_options_reach_the_entry(self):
        new_plant(self.at(), name="moss", display="Moss", color="#d04060", on=["minecraft:sand"], per_chunk=0.5, min_y=60, max_y=90, biomes=["minecraft:beach"])
        entry = self.manifest()["plants"][0]
        self.assertEqual((entry["on"], entry["perChunk"], entry["minY"], entry["maxY"], entry["biomes"]), (["minecraft:sand"], 0.5, 60, 90, ["minecraft:beach"]))
        self.release()

    def test_a_tinted_plant_has_a_grey_stem(self):
        new_plant(self.at(), name="moss", display="Moss", color="#d04060", family="tinted_plant", kind="grass")
        image = Image.open(self.at() / "assets" / "textures" / "moss.png").convert("RGBA")
        colours = [pixel[:3] for pixel in image.getdata() if pixel[3]]
        greys = [colour for colour in colours if max(colour) - min(colour) < 24]
        self.assertGreater(len(greys), len(colours) / 4)


class Mobs(Case):
    def test_every_shape_behaviour_and_category(self):
        for shape in bbmodel.KINDS:
            for behaviour in templates.MOB_BEHAVIOURS:
                for category in templates.MOB_CATEGORIES:
                    with self.subTest(f"{shape} {behaviour} {category}"):
                        folder = self.at("mob")
                        new_mob(folder, name="husk", display="Husk", category=category, behaviour=behaviour, shape=shape)
                        self.release()
                        shutil.rmtree(folder)

    def model_of(self, feature="thing", mob="husk"):
        name = self.manifest(feature)["mobs"][mob]["model"]
        return read(self.at(feature) / "assets" / "models" / f"{name}.bbmodel"), name

    def test_fighters_have_an_attack_and_others_dont(self):
        for behaviour, fights in (("hostile", True), ("neutral", True), ("passive", False), ("skittish", False)):
            with self.subTest(behaviour):
                new_mob(self.at(behaviour), name="husk", display="Husk", category="monster", behaviour=behaviour)
                model, _ = self.model_of(behaviour)
                names = {animation["name"]: animation for animation in model["animations"]}
                self.assertEqual("attack" in names, fights)
                if fights:
                    self.assertEqual(names["attack"]["loop"], "once")
                self.assertEqual(self.manifest(behaviour)["mobs"]["husk"]["damage"], 3 if fights else 0)

    def test_the_attack_starts_and_ends_at_rest(self):
        for shape in bbmodel.KINDS:
            with self.subTest(shape):
                folder = self.at(shape)
                new_mob(folder, name="husk", display="Husk", category="monster", behaviour="hostile", shape=shape)
                model, _ = self.model_of(shape)
                attack = next(animation for animation in model["animations"] if animation["name"] == "attack")
                self.assertTrue(attack["animators"])
                for animator in attack["animators"].values():
                    for channel in {key["channel"] for key in animator["keyframes"]}:
                        keys = sorted((key for key in animator["keyframes"] if key["channel"] == channel), key=lambda key: key["time"])
                        rest = 1 if channel == "scale" else 0
                        for key in (keys[0], keys[-1]):
                            for axis in "xyz":
                                self.assertAlmostEqual(key["data_points"][0][axis], rest, places=2)

    def test_the_model_gives_nothing_away(self):
        new_mob(self.at(), name="ember_husk", display="Ember Husk", category="monster", behaviour="hostile")
        model, name = self.model_of(mob="ember_husk")
        self.assertRegex(name, r"^m[0-9a-f]{12}$")
        self.assertEqual(model["name"], name)
        self.assertEqual(model["model_identifier"], name)
        text = json.dumps({key: value for key, value in model.items() if key != "textures"})
        self.assertNotIn("ember", text)
        self.assertNotIn("husk", text)
        self.assertEqual(list((self.at() / "assets" / "models").iterdir())[0].name, f"{name}.bbmodel")

    def test_the_numbers_reach_the_entry(self):
        new_mob(self.at(), name="husk", display="Husk", category="creature", behaviour="neutral", shape="quadruped", health=40, damage=6, speed=0.3,
                width=1.2, height=1.4, follow_range=16, armor=4)
        mob = self.manifest()["mobs"]["husk"]
        self.assertEqual((mob["health"], mob["damage"], mob["speed"], mob["width"], mob["height"], mob["followRange"], mob["armor"]), (40, 6, 0.3, 1.2, 1.4, 16, 4))
        self.assertEqual(mob["category"], "creature")
        self.release()

    def test_a_drop_nobody_has_declared_gets_made(self):
        result = new_mob(self.at(), name="husk", display="Husk", category="monster", behaviour="hostile", drops={"item": "husk_fang", "count": [0, 2]})
        manifest = self.manifest()
        self.assertEqual(manifest["mobs"]["husk"]["drops"], {"item": "husk_fang", "count": [0, 2]})
        self.assertEqual(manifest["items"]["husk_fang"]["display"], "Husk Fang")
        self.assertIn("husk_fang", result["added"])
        self.assertIn("husk_fang", result["summary"])
        self.release()

    def test_a_drop_can_be_this_features_or_anothers(self):
        new_ore(self.at("metal"), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        new_mob(self.at("metal"), name="husk", display="Husk", category="monster", behaviour="hostile", drops={"item": "$item:raw_tin"})
        self.assertEqual(self.manifest("metal")["mobs"]["husk"]["drops"], {"item": "raw_tin", "count": [1, 2]})
        new_mob(self.at("elsewhere"), name="crab", display="Crab", category="creature", behaviour="passive", drops="metal/raw_tin")
        self.assertEqual(self.manifest("elsewhere")["mobs"]["crab"]["drops"]["item"], "metal/raw_tin")
        self.assertNotIn("items", self.manifest("elsewhere"))
        self.release()

    def test_spawn_gets_what_the_server_needs(self):
        new_mob(self.at("yes"), name="husk", display="Husk", category="monster", behaviour="hostile", spawn=True)
        new_mob(self.at("some"), name="crab", display="Crab", category="creature", behaviour="passive", spawn={"weight": 4, "biomes": ["#minecraft:is_forest"]})
        new_mob(self.at("cave"), name="grub", display="Grub", category="monster", behaviour="hostile", spawn={"underground": True, "min_y": -40})
        new_mob(self.at("no"), name="boss", display="Boss", category="monster", behaviour="hostile")
        self.assertEqual(self.manifest("yes")["mobs"]["husk"]["spawn"], {"weight": 10, "light": "dark", "minY": 40, "maxY": 200, "cap": 3, "biomes": [], "underground": False})
        some = self.manifest("some")["mobs"]["crab"]["spawn"]
        self.assertEqual((some["weight"], some["light"], some["biomes"]), (4, "any", ["#minecraft:is_forest"]))
        cave = self.manifest("cave")["mobs"]["grub"]["spawn"]
        self.assertEqual((cave["underground"], cave["minY"], cave["maxY"]), (True, -40, 40))
        self.assertNotIn("spawn", self.manifest("no")["mobs"]["boss"])
        self.release()

    def test_options_for_the_model(self):
        new_mob(self.at(), name="husk", display="Husk", category="monster", behaviour="hostile", shape="quadruped", horns=True, eye="#ffb040")
        model, _ = self.model_of()
        self.assertIn("horn_a", {element["name"] for element in model["elements"]})
        self.release()


class Machines(Case):
    def test_what_it_makes(self):
        result = new_machine(self.at("rune_forge"), name="crucible", display="Rune Crucible", casing="#70707a", accent="#e88e36",
                             recipe_ingredients=["minecraft:cauldron", "minecraft:iron_ingot"], automation=[{"what": "machining", "per_minute": 20}])
        manifest = self.manifest("rune_forge")
        self.assertEqual(manifest["blocks"]["crucible"], {
            "family": "machine", "display": "Rune Crucible", "texture": "crucible", "tool": "pickaxe",
            "faces": {"front": "crucible", "side": "crucible_side", "top": "crucible_top", "bottom": "crucible_bottom", "back": "crucible_back"}})
        self.assertEqual(manifest["recipes"]["crucible"]["json"]["ingredients"], ["minecraft:cauldron", "minecraft:iron_ingot"])
        self.assertEqual(manifest["recipes"]["crucible"]["json"]["result"], {"id": "$block:crucible", "count": 1})
        self.assertEqual(manifest["automation"], [{"what": "machining", "per_minute": 20}])
        self.assertIn("crucible", result["added"])
        self.assertIn("RuneForgeModule", result["summary"])
        features, _, _ = self.release()
        self.assertEqual(bundles.find_modules(features), [("rune_forge", "server")])
        self.assertEqual(advice_on_the_template(features), [])

    def test_each_face_has_its_own_art(self):
        new_machine(self.at("rune_forge"), name="crucible", display="Rune Crucible", casing="#70707a", accent="#e88e36", recipe_ingredients=["minecraft:iron_block"])
        _, ledger, content = self.release()
        slot = ledger["blocks"]["rune_forge/crucible"]["slot"]
        for face in ("front", "side", "top", "bottom", "back"):
            self.assertTrue((content / "pack/assets/gm/textures/block" / f"{slot}_{face}.png").exists(), face)
        textures = read(content / "pack/assets/gm/models/block" / f"{slot}.json")["textures"]
        self.assertEqual(textures["north"], f"gm:block/{slot}_front")
        self.assertEqual(textures["up"], f"gm:block/{slot}_top")
        self.assertEqual(textures["east"], f"gm:block/{slot}_side")

    def test_a_machine_can_be_drawn_by_a_model(self):
        models = self.at("rune_forge") / "assets" / "models"
        models.mkdir(parents=True)
        (models / "press.bbmodel").write_text(json.dumps(bbmodel.slime("press")), encoding="utf-8")
        new_machine(self.at("rune_forge"), name="press", display="Press", casing="#70707a", accent="#e88e36", recipe_ingredients=["minecraft:iron_block"], model="press")
        self.assertEqual(self.manifest("rune_forge")["blocks"]["press"]["family"], "model")
        _, ledger, content = self.release()
        slot = ledger["blocks"]["rune_forge/press"]["slot"]
        self.assertEqual(slot, "s2300")
        hashed = read(content / "config/block_models.json")[slot]
        self.assertTrue((content / "config/models" / f"{hashed}.bbmodel").exists())
        self.assertNotIn("press", hashed)

    def test_a_model_has_to_be_sculpted_first(self):
        with self.assertRaisesRegex(TemplateError, "Sculpt it first"):
            new_machine(self.at(), name="press", display="Press", casing="#70707a", accent="#e88e36", model="nothing")
        with self.assertRaisesRegex(TemplateError, "Sculpt it first"):
            new_mob(self.at(), name="toad", display="Toad", category="creature", behaviour="passive", model="nothing")

    def test_a_mob_can_use_a_sculpted_model(self):
        models = self.at() / "assets" / "models"
        models.mkdir(parents=True)
        (models / "toad.bbmodel").write_text(json.dumps(bbmodel.slime("toad")), encoding="utf-8")
        result = new_mob(self.at(), name="toad", display="Toad", category="creature", behaviour="passive", model="toad")
        self.assertEqual(self.manifest()["mobs"]["toad"]["model"], "toad")
        self.assertEqual(sorted(path.name for path in models.iterdir()), ["toad.bbmodel"])
        self.assertNotIn("stand-in", result["summary"])

    def test_the_module_is_laid_out_the_way_the_build_wants(self):
        new_machine(self.at("rune_forge"), name="crucible", display="Rune Crucible", casing="#70707a", accent="#e88e36")
        server = self.at("rune_forge") / "server" / "src" / "main"
        self.assertEqual((server / "resources" / "module.properties").read_text(encoding="utf-8"), "entry=gm.feature.rune_forge.RuneForgeModule\n")
        source = (server / "java" / "gm" / "feature" / "rune_forge" / "RuneForgeModule.java").read_text(encoding="utf-8")
        self.assertIn("package gm.feature.rune_forge;", source)
        self.assertIn("public final class RuneForgeModule implements ServerModule", source)
        self.assertIn('MACHINE = "crucible"', source)
        for call in ("context.bindMachine(MACHINE", "context.attemptRecipe(player, MACHINE", "machine.data()", "attempt.succeeded()", "attempt.nearMiss()", "attempt.locked()"):
            self.assertIn(call, source)
        self.assertNotIn("@", re.sub(r"@Override", "", source), "every placeholder must be filled in")

    def test_the_bytecode_gate_allows_what_the_module_names(self):
        new_machine(self.at("rune_forge"), name="crucible", display="Rune Crucible", casing="#70707a", accent="#e88e36")
        source = next((self.at("rune_forge") / "server").rglob("*.java")).read_text(encoding="utf-8")
        for name in re.findall(r"^import ([\w.]+);", source, re.MULTILINE):
            self.assertIsNone(bytecode._class_problem(name.replace(".", "/"), "server"), name)

    def test_a_display_name_cant_break_the_java(self):
        new_machine(self.at(), name="crucible", display='The "Big" One\\', casing="#70707a", accent="#e88e36")
        manifest = json.loads((self.at() / "feature.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["texts"]["made"], 'The "Big" One\\ makes something.')
        self.assertIn('context.text("made")', next((self.at() / "server").rglob("*.java")).read_text(encoding="utf-8"))

    def test_a_second_machine_leaves_the_module_alone(self):
        new_machine(self.at(), name="one", display="One", casing="#70707a", accent="#e88e36")
        before = folder_print(self.at() / "server")
        result = new_machine(self.at(), name="two", display="Two", casing="#70707a", accent="#e88e36")
        self.assertEqual(folder_print(self.at() / "server"), before)
        self.assertIn('bindMachine("two"', result["summary"])
        self.assertIn("two", self.manifest()["blocks"])

    def test_with_no_recipe_it_has_no_source_and_says_so(self):
        result = new_machine(self.at(), name="crucible", display="Crucible", casing="#70707a", accent="#e88e36")
        self.assertIn("source", result["summary"])
        features = bundles.load_features(self.features)
        with self.assertRaises(GateFailed) as caught:
            balance.run(features)
        self.assertIn("Nobody can obtain thing/crucible", caught.exception.message)

    def test_automation_adds_to_what_was_there(self):
        new_machine(self.at(), name="one", display="One", casing="#70707a", accent="#e88e36", automation=[{"what": "sorting", "per_minute": 60}])
        new_machine(self.at(), name="two", display="Two", casing="#70707a", accent="#e88e36", automation=[{"what": "machining", "per_minute": 10}])
        self.assertEqual([entry["what"] for entry in self.manifest()["automation"]], ["sorting", "machining"])

    def test_ids_java_cant_use(self):
        for feature in ("class", "1forge"):
            with self.subTest(feature), self.assertRaises(TemplateError):
                new_machine(self.at(feature), name="crucible", display="Crucible", casing="#70707a", accent="#e88e36")
            self.assertFalse(self.at(feature).exists())


def advice_on_the_template(features):
    """A template leaves nothing for a reviewer to send back, except a feature's page in the Codex, which is its builder's own writing."""
    return [note for note in advice.run(features) if "no page in the Codex" not in note]


class Together(Case):
    def chain(self, tier, ore_at="metal", tools_at="metal", armor_at="metal"):
        token = "$item:tin_ingot" if tools_at == ore_at else f"$item:{ore_at}/tin_ingot"
        new_ore(self.at(ore_at), name="tin", display="Tin", color="#d8c8a0", tier=tier, deep=True)
        new_tool_set(self.at(tools_at), material="tin", display="Tin", tier=tier, ingredient=token, color="#d8c8a0")
        token = "$item:tin_ingot" if armor_at == ore_at else f"$item:{ore_at}/tin_ingot"
        new_armor_set(self.at(armor_at), material="tin", display="Tin", tier=tier, ingredient=token, color="#d8c8a0")

    def test_ore_tools_and_armor_in_one_feature_at_every_tier(self):
        for tier in TIERS:
            with self.subTest(tier):
                # Whatever happens, because the next tier starts from nothing, and one failure shouldn't look like seven.
                try:
                    self.chain(tier)
                    features, _, _ = self.release()
                    self.assertEqual(advice_on_the_template(features), [])
                finally:
                    shutil.rmtree(self.at("metal"), ignore_errors=True)

    def test_ore_tools_and_armor_across_features_at_every_tier(self):
        for tier in TIERS:
            with self.subTest(tier):
                try:
                    self.chain(tier, ore_at="metal", tools_at="gear", armor_at="plate")
                    features, _, _ = self.release()
                    self.assertEqual(advice_on_the_template(features), [])
                finally:
                    for feature in ("metal", "gear", "plate"):
                        shutil.rmtree(self.at(feature), ignore_errors=True)

    def test_tools_from_a_better_ingot_than_they_need_pass(self):
        new_ore(self.at("metal"), name="tin", display="Tin", color="#d8c8a0", tier="diamond")
        new_tool_set(self.at("gear"), material="tin", display="Tin", tier="stone", ingredient="$item:metal/tin_ingot", color="#d8c8a0")
        self.release()

    def test_tools_from_a_much_commoner_ore_fail_the_way_the_summary_warned(self):
        new_ore(self.at("metal"), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        result = new_tool_set(self.at("gear"), material="tin", display="Tin", tier="netherite", ingredient="$item:metal/tin_ingot", color="#d8c8a0")
        self.assertIn("feeding tier netherite", result["summary"])
        with self.assertRaises(GateFailed) as caught:
            balance.run(bundles.load_features(self.features))
        self.assertIn("feeds tier netherite", caught.exception.message)

    def test_everything_in_one_feature(self):
        new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron", deep=True)
        new_ore(self.at(), name="ash", display="Ash", color="#808080", tier="stone")
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient="$item:tin_ingot", color="#d8c8a0")
        new_armor_set(self.at(), material="tin", display="Tin", tier="iron", ingredient="$item:tin_ingot", color="#d8c8a0")
        new_plant(self.at(), name="moss", display="Moss", color="#d04060", food={"nutrition": 4, "saturation": 2.4})
        new_plant(self.at(), name="fern", display="Fern", color="#d04060", family="tinted_plant", kind="grass")
        new_mob(self.at(), name="husk", display="Husk", category="monster", behaviour="hostile", drops={"item": "raw_tin"}, spawn=True)
        new_mob(self.at(), name="crab", display="Crab", category="creature", behaviour="skittish", shape="quadruped", spawn=True)
        new_machine(self.at(), name="forge", display="Forge", casing="#70707a", accent="#e88e36", recipe_ingredients=["$block:tin_block", "minecraft:furnace"])
        features, ledger, _ = self.release()
        manifest = self.manifest()
        self.assertEqual(manifest["id"], "thing")
        self.assertEqual(len(ledger["mobs"]), 2)
        self.assertEqual(len(manifest["ores"]), 3)
        self.assertEqual(bundles.find_modules(features), [("thing", "server")])

    def test_a_mid_game_recipe_can_be_gated_by_an_earlier_node(self):
        # progression's gate refuses tiered gear that nothing from before it is needed for, so the options have to make that possible.
        world = {"goal": "Wake the machine", "nodes": {
            "first": {"stage": "early", "name": "First", "requires": [], "opens_with": "", "holds": ""},
            "second": {"stage": "mid", "name": "Second", "requires": ["first"], "opens_with": "something", "holds": ""},
            "last": {"stage": "end", "name": "Last", "requires": ["second"], "opens_with": "something", "holds": ""},
        }}
        new_ore(self.at("early"), name="tin", display="Tin", color="#d8c8a0", tier="iron", node="first")
        new_tool_set(self.at("early"), material="tin", display="Tin", tier="iron", ingredient="$item:tin_ingot", color="#d8c8a0")
        new_ore(self.at("mid"), name="zinc", display="Zinc", color="#a0c0c8", tier="beyond", node="second")
        new_tool_set(self.at("mid"), material="zinc", display="Zinc", tier="beyond", ingredient="$item:zinc_ingot", color="#a0c0c8", handle_ingredient="$item:early/tin_ingot")
        new_armor_set(self.at("mid"), material="zinc", display="Zinc", tier="beyond", ingredient="$item:zinc_ingot", color="#a0c0c8", extra_ingredient="$item:early/tin_ingot")
        new_machine(self.at("mid"), name="press", display="Press", casing="#70707a", accent="#e88e36", recipe_ingredients=["$block:early/tin_block", "minecraft:piston"],
                    automation=[{"what": "machining", "per_minute": 20}])
        new_tool_set(self.at("late"), material="star", display="Star", tier="mythic", ingredient="$item:mid/zinc_ingot", color="#f0e0ff", node="last", kinds=["sword"])
        features = bundles.load_features(self.features)
        bible = self.base / "bible"
        bible.mkdir()
        graph.save(bible / "progression.json", world)
        try:
            progression.run(features, bible, {}, {}, bible / "none.json", {})
        except GateFailed as error:
            self.fail(error.message)

    def test_the_same_recipes_without_something_from_before_are_refused(self):
        world = {"goal": "Wake the machine", "nodes": {
            "first": {"stage": "early", "name": "First", "requires": [], "opens_with": "", "holds": ""},
            "second": {"stage": "mid", "name": "Second", "requires": ["first"], "opens_with": "something", "holds": ""},
            "last": {"stage": "end", "name": "Last", "requires": ["second"], "opens_with": "something", "holds": ""},
        }}
        new_ore(self.at("mid"), name="zinc", display="Zinc", color="#a0c0c8", tier="beyond", node="second")
        new_tool_set(self.at("mid"), material="zinc", display="Zinc", tier="beyond", ingredient="$item:zinc_ingot", color="#a0c0c8", kinds=["sword"])
        bible = self.base / "bible"
        bible.mkdir()
        graph.save(bible / "progression.json", world)
        with self.assertRaises(GateFailed) as caught:
            progression.run(bundles.load_features(self.features), bible, {}, {}, bible / "none.json", {})
        self.assertIn("nothing gates it", caught.exception.message)


class Refusals(Case):
    TEMPLATES = {
        "new_ore": lambda folder: new_ore(folder, name="tin", display="Tin", color="#d8c8a0", tier="iron", deep=True),
        "new_tool_set": lambda folder: new_tool_set(folder, material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0"),
        "new_armor_set": lambda folder: new_armor_set(folder, material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0"),
        "new_plant": lambda folder: new_plant(folder, name="moss", display="Moss", color="#d04060", food={"nutrition": 4, "saturation": 2.4}),
        "new_mob": lambda folder: new_mob(folder, name="husk", display="Husk", category="monster", behaviour="hostile", drops={"item": "husk_fang"}, spawn=True),
        "new_machine": lambda folder: new_machine(folder, name="forge", display="Forge", casing="#70707a", accent="#e88e36", recipe_ingredients=["minecraft:furnace"]),
    }

    def test_every_template_covers_this_table(self):
        self.assertEqual(set(self.TEMPLATES), set(templates.TEMPLATES))

    def test_a_second_call_with_the_same_name_is_refused_and_changes_nothing(self):
        for name, make in self.TEMPLATES.items():
            with self.subTest(name):
                folder = self.at(name)
                make(folder)
                before = folder_print(folder)
                with self.assertRaises(TemplateError):
                    make(folder)
                self.assertEqual(folder_print(folder), before)

    def test_a_partly_overlapping_call_writes_nothing(self):
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", kinds=["sword"])
        before = folder_print(self.at())
        with self.assertRaises(TemplateError):
            new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", kinds=["pickaxe", "sword"])
        self.assertEqual(folder_print(self.at()), before)
        self.assertNotIn("tin_pickaxe", self.manifest()["items"])

    def test_the_rest_of_a_set_can_still_be_added(self):
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", kinds=["sword"])
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", kinds=["axe"])
        self.assertEqual(set(self.manifest()["items"]), {"tin_sword", "tin_axe"})
        self.release()

    def test_it_wont_overwrite_art_a_builder_already_made(self):
        textures = self.at() / "assets" / "textures"
        textures.mkdir(parents=True)
        (textures / "tin_ingot.png").write_bytes(b"mine")
        with self.assertRaises(TemplateError):
            new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        self.assertEqual((textures / "tin_ingot.png").read_bytes(), b"mine")
        self.assertFalse((self.at() / "feature.json").exists())
        self.assertEqual(len(list(textures.iterdir())), 1)

    def test_a_block_item_and_mob_cant_share_a_name(self):
        # bindings.json maps feature/name to one slot, so the second would quietly take over.
        new_mob(self.at(), name="tin_ore", display="Tin Ore", category="monster", behaviour="hostile")
        with self.assertRaises(TemplateError):
            new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")

    def test_a_bad_feature_json_is_left_alone(self):
        self.at().mkdir()
        (self.at() / "feature.json").write_text("{nope", encoding="utf-8")
        with self.assertRaises(TemplateError):
            new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        self.assertEqual((self.at() / "feature.json").read_text(encoding="utf-8"), "{nope")

    def test_a_feature_json_for_another_id_is_left_alone(self):
        self.at().mkdir()
        (self.at() / "feature.json").write_text('{"id": "other"}', encoding="utf-8")
        with self.assertRaises(TemplateError):
            new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")

    def test_what_was_there_is_kept(self):
        self.at().mkdir()
        (self.at() / "feature.json").write_text(json.dumps({"id": "thing", "summary": "Mine.", "phase": 2, "changes_reached": {"a": "b"}, "items": {"a": {"display": "A", "retired": True}}}), encoding="utf-8")
        new_ore(self.at(), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        manifest = self.manifest()
        self.assertEqual((manifest["summary"], manifest["phase"], manifest["changes_reached"]), ("Mine.", 2, {"a": "b"}))
        self.assertIn("a", manifest["items"])
        self.assertIn("tin_ingot", manifest["items"])

    def test_bad_input(self):
        ore = {"name": "tin", "display": "Tin", "color": "#d8c8a0", "tier": "iron"}
        tools = {"material": "tin", "display": "Tin", "tier": "iron", "ingredient": INGOT, "color": "#d8c8a0"}
        armor = {"material": "tin", "display": "Tin", "tier": "iron", "ingredient": INGOT, "color": "#d8c8a0"}
        plant = {"name": "moss", "display": "Moss", "color": "#d04060"}
        mob = {"name": "husk", "display": "Husk", "category": "monster", "behaviour": "hostile"}
        machine = {"name": "forge", "display": "Forge", "casing": "#70707a", "accent": "#e88e36"}
        for function, base, changes in (
            (new_ore, ore, {"tier": "mithril"}),
            (new_ore, ore, {"name": "Tin Ore"}),
            (new_ore, ore, {"name": "a/b"}),
            (new_ore, ore, {"color": "orange"}),
            (new_ore, ore, {"stone_color": "grey"}),
            (new_ore, ore, {"display": ""}),
            (new_ore, ore, {"biomes": ["#minecraft:is_forest"]}),
            (new_ore, ore, {"min_y": 40, "max_y": 10}),
            (new_ore, ore, {"min_y": 100, "max_y": 200}),
            (new_ore, ore, {"min_y": 1.5}),
            (new_ore, ore, {"vein_size": 17}),
            (new_ore, ore, {"vein_size": 0}),
            (new_ore, ore, {"deep": True, "min_y": -40, "max_y": -10}),
            (new_ore, ore, {"deep": True, "min_y": 20, "max_y": 60}),
            (new_ore, ore, {"drop_count": [3, 1]}),
            (new_ore, ore, {"drop_count": 2}),
            (new_ore, ore, {"tool_level": "netherite"}),
            (new_ore, ore, {"block_style": "shiny"}),
            (new_ore, {**ore, "tier": "mythic"}, {"vein_size": 16}),
            (new_tool_set, tools, {"tier": "mithril"}),
            (new_tool_set, tools, {"kinds": ["spoon"]}),
            (new_tool_set, tools, {"kinds": []}),
            (new_tool_set, tools, {"kinds": "pickaxe"}),
            (new_tool_set, tools, {"ingredient": "tin_ingot"}),
            (new_tool_set, tools, {"ingredient": "gm:i0007"}),
            (new_tool_set, tools, {"ingredient": "#c:ingots"}),
            (new_tool_set, tools, {"ingredient": "$item:tin_ingot"}),
            (new_tool_set, tools, {"ingredient": 5}),
            (new_tool_set, tools, {"handle_ingredient": "stick"}),
            (new_tool_set, tools, {"mode": "known"}),
            (new_tool_set, tools, {"mode": "guessable"}),
            (new_armor_set, armor, {"slots": ["tail"]}),
            (new_armor_set, armor, {"slots": ["body"]}),
            (new_armor_set, armor, {"worn_look": "cardboard"}),
            (new_armor_set, armor, {"extra_ingredient": "stick"}),
            (new_armor_set, armor, {"mode": "known"}),
            (new_plant, plant, {"family": "stone"}),
            (new_plant, plant, {"kind": "tree"}),
            (new_plant, plant, {"on": ["#minecraft:dirt"]}),
            (new_plant, plant, {"on": []}),
            (new_plant, plant, {"biomes": ["#minecraft:is_forest"]}),
            (new_plant, plant, {"per_chunk": 0}),
            (new_plant, plant, {"min_y": 60.5}),
            (new_plant, plant, {"food": {"nutrition": 4}}),
            (new_plant, plant, {"food": {"nutrition": -1, "saturation": 1}}),
            (new_plant, plant, {"food": {"nutrition": 1, "saturation": 1, "kind": "soup"}}),
            (new_plant, plant, {"food": 4}),
            (new_mob, mob, {"category": "boss"}),
            (new_mob, mob, {"behaviour": "angry"}),
            (new_mob, mob, {"shape": "snake"}),
            (new_mob, mob, {"health": 0}),
            (new_mob, mob, {"damage": -1}),
            (new_mob, mob, {"speed": 0}),
            (new_mob, mob, {"primary": "nope"}),
            (new_mob, mob, {"drops": {"item": "minecraft:rotten_flesh"}}),
            (new_mob, mob, {"drops": {"count": [1, 2]}}),
            (new_mob, mob, {"drops": {"item": "fang", "count": [2, 1]}}),
            (new_mob, mob, {"spawn": {"light": "dim"}}),
            (new_mob, mob, {"spawn": {"weight": 1.5}}),
            (new_mob, mob, {"spawn": {"biomes": ["Forest"]}}),
            (new_mob, mob, {"spawn": 3}),
            (new_mob, {**mob, "shape": "slime"}, {"horns": True}),
            (new_machine, machine, {"casing": "nope"}),
            (new_machine, machine, {"recipe_ingredients": ["furnace"]}),
            (new_machine, machine, {"recipe_ingredients": ["minecraft:stone"] * 10}),
            (new_machine, machine, {"automation": {"what": "mining"}}),
            (new_machine, machine, {"automation": [{"what": "mining"}]}),
            (new_machine, machine, {"automation": [{"per_minute": 5}]}),
            (new_machine, machine, {"automation": [{"what": "mining", "per_minute": 0}]}),
            (new_machine, machine, {"tool_level": "wood"}),
        ):
            with self.subTest(f"{function.__name__} {changes}"):
                folder = self.at("bad")
                with self.assertRaises(TemplateError):
                    function(folder, **{**base, **changes})
                self.assertFalse(folder.exists(), "a refused call leaves nothing behind")

    def test_an_id_that_isnt_a_feature_id(self):
        with self.assertRaises(TemplateError):
            new_ore(self.at("Not An Id"), name="tin", display="Tin", color="#d8c8a0", tier="iron")

    def test_a_token_for_another_feature_is_checked_if_it_can_be(self):
        new_ore(self.at("metal"), name="tin", display="Tin", color="#d8c8a0", tier="iron")
        with self.assertRaises(TemplateError):
            new_tool_set(self.at("gear"), material="tin", display="Tin", tier="iron", ingredient="$item:metal/zinc_ingot", color="#d8c8a0")
        with self.assertRaises(TemplateError):
            new_tool_set(self.at("gear"), material="tin", display="Tin", tier="iron", ingredient="$block:metal/tin_ingot", color="#d8c8a0")
        result = new_tool_set(self.at("gear"), material="tin", display="Tin", tier="iron", ingredient="$item:elsewhere/zinc_ingot", color="#d8c8a0")
        self.assertIn("make sure it declares zinc_ingot", result["summary"])


class Known(Case):
    def test_a_known_recipe_needs_its_entry_and_passes_with_it(self):
        result = new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", mode="known", route="smithing")
        self.assertIn("smithing", result["summary"])
        self.assertEqual(self.manifest()["recipes"]["tin_sword"]["mode"], "known")
        self.assertEqual(self.manifest()["recipes"]["tin_sword"]["route"], "smithing")
        # bundles.render says the same thing as the gate, and stops first.
        with self.assertRaises(bundles.BundleError):
            self.release()
        manifest = self.manifest()
        manifest["knowledge"] = {"smithing": {"title": "On Smithing", "text": "Hints.", "routes": [{"type": "obtain", "id": INGOT}]}}
        (self.at() / "feature.json").write_text(json.dumps(manifest), encoding="utf-8")
        _, _, content = self.release()
        plan = read(content / "config" / "knowledge.json")
        self.assertEqual(len(plan["entries"]["thing/smithing"]["recipes"]), 5)

    def test_armor_too_and_another_features_entry(self):
        new_armor_set(self.at("gear"), material="tin", display="Tin", tier="iron", ingredient=INGOT, color="#d8c8a0", mode="known", route="lore/smithing")
        self.at("lore").mkdir()
        (self.at("lore") / "feature.json").write_text(json.dumps({"id": "lore", "knowledge": {"smithing": {"title": "T", "text": "T", "routes": [{"type": "obtain", "id": INGOT}]}}}), encoding="utf-8")
        self.release()

    def test_a_machine_too(self):
        new_machine(self.at(), name="forge", display="Forge", casing="#70707a", accent="#e88e36", recipe_ingredients=["minecraft:furnace"], mode="known", route="smithing")
        self.assertEqual(self.manifest()["recipes"]["forge"]["route"], "smithing")


class NodeAndPhase(Case):
    def test_every_template_sets_them_when_asked(self):
        for name, make in Refusals.TEMPLATES.items():
            with self.subTest(name):
                folder = self.at(name)
                make(folder)
                self.assertNotIn("node", self.manifest(name))
                self.assertNotIn("phase", self.manifest(name))
        calls = {
            "new_ore": {"name": "a", "display": "A", "color": "#d8c8a0", "tier": "iron"},
            "new_tool_set": {"material": "a", "display": "A", "tier": "iron", "ingredient": INGOT, "color": "#d8c8a0"},
            "new_armor_set": {"material": "a", "display": "A", "tier": "iron", "ingredient": INGOT, "color": "#d8c8a0"},
            "new_plant": {"name": "a", "display": "A", "color": "#d04060"},
            "new_mob": {"name": "a", "display": "A", "category": "monster", "behaviour": "hostile"},
            "new_machine": {"name": "a", "display": "A", "casing": "#70707a", "accent": "#e88e36"},
        }
        self.assertEqual(set(calls), set(templates.TEMPLATES))
        for name, arguments in calls.items():
            with self.subTest(name):
                templates.TEMPLATES[name](self.at(f"{name}_set"), **arguments, node="first_ore", phase=2)
                manifest = self.manifest(f"{name}_set")
                self.assertEqual((manifest["node"], manifest["phase"]), ("first_ore", 2))


class Calling(Case):
    """How orchestrator/workshop.py calls these: a path, and arguments that came through JSON."""

    def test_arguments_from_json(self):
        new_ore(str(self.at()), name="tin", display="Tin", color=[216, 200, 160], tier="iron", min_y=-20.0, max_y=40.0)
        self.assertIs(type(self.manifest()["ores"][0]["minY"]), int)
        new_tool_set(self.at(), material="tin", display="Tin", tier="iron", ingredient="$item:tin_ingot", color=[216, 200, 160], kinds=["sword", "axe"])
        new_armor_set(self.at(), material="tin", display="Tin", tier="iron", ingredient="$item:tin_ingot", color=[216, 200, 160], slots=["head"])
        self.release()

    def test_the_result_can_go_back_through_json(self):
        for name, make in Refusals.TEMPLATES.items():
            with self.subTest(name):
                result = make(self.at(name))
                self.assertEqual(json.loads(json.dumps(result)), result)
                self.assertEqual(set(result), {"added", "summary"})
                self.assertTrue(result["added"])
                self.assertLess(len(result["summary"]), 600, "it's meant to be a sentence or two")

    def test_each_takes_under_a_second(self):
        for name, make in Refusals.TEMPLATES.items():
            with self.subTest(name):
                began = time.perf_counter()
                make(self.at(name))
                self.assertLess(time.perf_counter() - began, 1.0)


class Seeds(Case):
    def test_the_same_seed_gives_the_same_files(self):
        for name, make in Refusals.TEMPLATES.items():
            with self.subTest(name):
                make(self.at())
                first = folder_print(self.at())
                shutil.rmtree(self.at())
                make(self.at())
                self.assertEqual(folder_print(self.at()), first)
                shutil.rmtree(self.at())

    def test_a_different_seed_gives_different_art(self):
        calls = [
            (new_ore, {"name": "tin", "display": "Tin", "color": "#d8c8a0", "tier": "iron"}),
            (new_plant, {"name": "moss", "display": "Moss", "color": "#d04060", "food": {"nutrition": 4, "saturation": 2.4}}),
            (new_mob, {"name": "husk", "display": "Husk", "category": "monster", "behaviour": "hostile"}),
            (new_machine, {"name": "forge", "display": "Forge", "casing": "#70707a", "accent": "#e88e36"}),
            (new_tool_set, {"material": "tin", "display": "Tin", "tier": "iron", "ingredient": INGOT, "color": "#d8c8a0"}),
            (new_armor_set, {"material": "tin", "display": "Tin", "tier": "iron", "ingredient": INGOT, "color": "#d8c8a0"}),
        ]
        for function, arguments in calls:
            with self.subTest(function.__name__):
                # By contents, because a model's file name comes from the feature's id.
                art = []
                for seed in (1, 2):
                    folder = self.at(f"{function.__name__}_{seed}")
                    function(folder, **arguments, seed=seed)
                    art.append({digest for path, digest in folder_print(folder).items() if "assets" in path})
                self.assertEqual(len(art[0]), len(art[1]))
                self.assertNotEqual(art[0], art[1])


class Art(Case):
    def test_textures_are_valid_and_keep_to_a_small_palette(self):
        for name, make in Refusals.TEMPLATES.items():
            make(self.at(name))
        # Worn armour has a shape of its own, which test_it_draws_what_it_looks_like_worn looks at.
        pictures = [path for path in self.features.rglob("*.png") if "raw" not in path.parts]
        self.assertGreater(len(pictures), 15)
        for path in pictures:
            with self.subTest(path.name):
                image = Image.open(path)
                self.assertEqual(image.size, (16, 16))
                self.assertEqual(image.mode, "RGBA")
                colours = {pixel[:3] for pixel in image.getdata() if pixel[3]}
                self.assertTrue(colours, "a texture with nothing in it")
                self.assertLessEqual(len(colours), 13)

    def test_every_block_and_item_has_its_texture(self):
        for name, make in Refusals.TEMPLATES.items():
            make(self.at(name))
            manifest = self.manifest(name)
            for table in ("blocks", "items"):
                for thing, entry in manifest.get(table, {}).items():
                    self.assertTrue((self.at(name) / "assets" / "textures" / f"{entry['texture']}.png").exists(), thing)
                    self.assertTrue(entry["display"], thing)


if __name__ == "__main__":
    unittest.main()
