"""The rules that shape a world's arc, and the tools that work on what's already out. No servers needed."""
import json
import pathlib
import tempfile
import unittest

from broker.gates import GateFailed, balance, world_diff
from broker.gates import progression as gate
from orchestrator import progression as graph
from orchestrator import tuning, world_index


def node(stage, *requires, opens_with="something from before"):
    return {"stage": stage, "name": stage, "requires": list(requires), "opens_with": opens_with, "holds": ""}


WORLD = {"goal": "Wake the machine", "nodes": {
    "first_ore": node("early"),
    "other_ore": node("early"),
    "press": node("mid", "first_ore"),
    "sorter": node("mid", "first_ore"),
    "quarry": node("end", "press"),
}}


def feature(feature_id, at=None, **tables):
    manifest = {"id": feature_id, **tables}
    if at:
        manifest["node"] = at
    return {"manifest": manifest, "dir": pathlib.Path("/nowhere")}


def craft(*inputs, makes, **extra):
    return {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": list(inputs), "result": {"id": makes}}, **extra}


def check(features, doc=WORLD):
    """Runs the gate with a real graph file. Returns the problem, or None if it passed."""
    with tempfile.TemporaryDirectory() as folder:
        bible = pathlib.Path(folder)
        if doc:
            graph.save(bible / "progression.json", doc)
        try:
            gate.run(features, bible, {}, {}, bible / "none.json", {})
        except GateFailed as error:
            return error.message
    return None


class TheGraph(unittest.TestCase):
    def problems(self, **changes):
        return graph.problems({"goal": "x", "nodes": {**WORLD["nodes"], **changes}})

    def test_a_good_graph_with_branches_passes(self):
        self.assertEqual(graph.problems(WORLD), [])

    def test_every_stage_is_needed(self):
        self.assertTrue(graph.problems({"goal": "x", "nodes": {"a": node("early")}}))

    def test_a_goal_is_needed(self):
        self.assertTrue(graph.problems({"goal": "", "nodes": WORLD["nodes"]}))

    def test_a_loop_is_refused(self):
        looped = {"one": node("early", "two"), "two": node("early", "one"), "mid_node": node("mid", "one"), "end_node": node("end", "mid_node")}
        self.assertIn("loop", graph.problems({"goal": "x", "nodes": looped})[0])

    def test_a_missing_node_is_refused(self):
        self.assertTrue(self.problems(extra=node("mid", "nothing")))

    def test_a_stage_cant_go_backwards(self):
        self.assertTrue(self.problems(extra=node("early", "press")))

    def test_mid_game_needs_the_early_game_before_it(self):
        self.assertTrue(self.problems(extra=node("mid")))

    def test_the_endgame_needs_the_mid_game_before_it(self):
        self.assertTrue(self.problems(extra=node("end", "first_ore")))

    def test_later_nodes_say_what_opens_them(self):
        self.assertTrue(self.problems(extra=node("mid", "first_ore", opens_with="")))

    def test_it_can_grow(self):
        merged, refused = graph.merge(WORLD, [{"id": "reactor", **node("end", "quarry")}], set())
        self.assertIn("reactor", merged["nodes"])
        self.assertEqual(refused, [])

    def test_what_players_have_reached_cant_be_reshaped(self):
        merged, refused = graph.merge(WORLD, [{"id": "press", **node("mid", "other_ore")}], {"press"})
        self.assertEqual(merged["nodes"]["press"]["requires"], ["first_ore"])
        self.assertTrue(refused)

    def test_a_change_that_breaks_the_graph_is_refused(self):
        merged, refused = graph.merge(WORLD, [{"id": "bad", **node("mid", "nothing")}], set())
        self.assertIs(merged, WORLD)
        self.assertTrue(refused)


class FeaturesInTheGraph(unittest.TestCase):
    def test_a_feature_says_where_it_belongs(self):
        self.assertIn("no \"node\"", check({"a": feature("a")}))

    def test_a_feature_cant_name_a_node_that_doesnt_exist(self):
        self.assertIn("isn't in", check({"a": feature("a", "nowhere")}))

    def test_a_world_without_a_graph_isnt_held_to_one(self):
        self.assertIsNone(check({"a": feature("a")}, doc=None))

    def test_a_recipe_cant_use_something_from_later_on(self):
        features = {"ore": feature("ore", "first_ore", items={"pick": {}}, recipes={"pick": craft("$item:press/plate", makes="$item:pick")}),
                    "press": feature("press", "press", items={"plate": {}})}
        self.assertIn("doesn't come before", check(features))

    def test_a_recipe_cant_use_something_from_another_branch(self):
        features = {"press": feature("press", "press", items={"plate": {}, "x": {}}, recipes={"x": craft("$item:sorter/gear", makes="$item:x")}),
                    "sorter": feature("sorter", "sorter", items={"gear": {}})}
        self.assertIn("doesn't come before", check(features))

    def test_a_recipe_can_use_what_came_before(self):
        features = {"ore": feature("ore", "first_ore", items={"ingot": {}}),
                    "press": feature("press", "press", items={"plate": {}}, recipes={"plate": craft("$item:ore/ingot", makes="$item:plate")})}
        self.assertIsNone(check(features))


class GatedByResources(unittest.TestCase):
    def test_late_gear_made_only_from_vanilla_things_is_refused(self):
        features = {"press": feature("press", "press", items={"pick": {"tier": "diamond"}},
                                     recipes={"pick": craft("minecraft:iron_ingot", makes="$item:pick")})}
        self.assertIn("nothing gates it", check(features))

    def test_late_gear_needing_an_earlier_material_passes(self):
        features = {"ore": feature("ore", "first_ore", items={"ingot": {}}),
                    "press": feature("press", "press", items={"pick": {"tier": "diamond"}},
                                     recipes={"pick": craft("$item:ore/ingot", makes="$item:pick")})}
        self.assertIsNone(check(features))

    def test_the_earlier_material_can_be_a_few_steps_back(self):
        features = {"ore": feature("ore", "first_ore", items={"ingot": {}}),
                    "press": feature("press", "press", items={"plate": {}, "pick": {"tier": "diamond"}},
                                     recipes={"plate": craft("$item:ore/ingot", makes="$item:plate"), "pick": craft("$item:plate", makes="$item:pick")})}
        self.assertIsNone(check(features))

    def test_the_endgames_gear_cant_be_made_of_the_first_ore(self):
        features = {"ore": feature("ore", "first_ore", items={"ingot": {}}),
                    "blade": feature("blade", "quarry", items={"sword": {"tier": "mythic"}},
                                     recipes={"sword": craft("$item:ore/ingot", makes="$item:sword")})}
        self.assertIn("nothing gates it", check(features))

    def test_the_endgames_gear_needs_what_the_mid_game_makes(self):
        features = {"ore": feature("ore", "first_ore", items={"ingot": {}}),
                    "press": feature("press", "press", items={"plate": {}}, recipes={"plate": craft("$item:ore/ingot", makes="$item:plate")}),
                    "blade": feature("blade", "quarry", items={"sword": {"tier": "mythic"}},
                                     recipes={"sword": craft("$item:press/plate", "$item:ore/ingot", makes="$item:sword")})}
        self.assertIsNone(check(features))

    def test_an_early_ore_going_into_later_recipes_stays_common(self):
        features = {"ore": feature("ore", "first_ore", blocks={"ore": {}}, items={"ingot": {}},
                                   ores=[{"id": "ore_v1", "block": "ore", "veinsPerChunk": 16, "veinSize": 8, "minY": -32, "maxY": 48}]),
                    "blade": feature("blade", "quarry", items={"sword": {"tier": "mythic"}},
                                     recipes={"sword": craft("$block:ore/ore", makes="$item:sword")})}
        self.assertEqual(balance.check_ores(features, balance._read_recipes(features)), [])

    def test_within_one_step_an_ore_still_answers_for_what_it_makes(self):
        features = {"ore": feature("ore", "first_ore", blocks={"ore": {}}, items={"sword": {"tier": "diamond"}},
                                   ores=[{"id": "ore_v1", "block": "ore", "veinsPerChunk": 16, "veinSize": 8, "minY": -32, "maxY": 48}],
                                   recipes={"sword": craft("$block:ore", makes="$item:sword")})}
        self.assertIn("feeds tier diamond", balance.check_ores(features, balance._read_recipes(features))[0])

    def test_a_cheap_second_recipe_is_a_way_around_the_gate(self):
        features = {"ore": feature("ore", "first_ore", items={"ingot": {}}),
                    "press": feature("press", "press", items={"pick": {"tier": "diamond"}},
                                     recipes={"good": craft("$item:ore/ingot", makes="$item:pick"), "cheap": craft("minecraft:stick", makes="$item:pick")})}
        self.assertIn("press/cheap", check(features))

    def test_a_machine_is_gated_too(self):
        features = {"press": feature("press", "press", blocks={"press": {"family": "machine"}},
                                     recipes={"press": craft("minecraft:iron_block", makes="$block:press")})}
        self.assertIn("nothing gates it", check(features))

    def test_material_found_in_the_world_is_how_a_node_opens(self):
        features = {"press": feature("press", "press", items={"raw": {}, "ingot": {}}, recipes={"ingot": craft("$item:raw", makes="$item:ingot")})}
        self.assertIsNone(check(features))


class WhatEachStageAllows(unittest.TestCase):
    def tier(self, tier, at):
        return check({"a": feature("a", at, items={"thing": {"tier": tier}})})

    def test_early_gear_stops_around_iron(self):
        self.assertIsNone(self.tier("iron", "first_ore"))
        self.assertIn("strongest allowed", self.tier("diamond", "first_ore"))

    def test_the_mid_game_is_stronger_but_not_unlimited(self):
        self.assertIsNone(self.tier("beyond", "press"))
        self.assertIn("strongest allowed", self.tier("mythic", "press"))

    def test_the_endgame_has_no_limit(self):
        self.assertIsNone(self.tier("mythic", "quarry"))

    def test_mythic_cant_exist_without_a_progression(self):
        self.assertIn("endgame node", check({"a": feature("a", items={"thing": {"tier": "mythic"}})}, doc=None))

    def test_mythic_gear_can_carry_anything(self):
        components = {"minecraft:enchantments": {"minecraft:sharpness": 50}, "minecraft:unbreakable": {},
                      "minecraft:attribute_modifiers": [{"type": "minecraft:max_health", "amount": 100, "operation": "add_value", "slot": "any"}]}
        for tier, passes in (("mythic", True), ("netherite", False)):
            features = {"a": feature("a", items={"thing": {"tier": tier, "components": components}})}
            problems = balance.check_power(features, balance._read_recipes(features))
            self.assertEqual(not problems, passes, problems)

    def mob(self, at, health, damage=2):
        return check({"a": feature("a", at, mobs={"mob": {"health": health, "damage": damage}})})

    def test_mobs_grow_with_the_stages(self):
        self.assertIsNone(self.mob("first_ore", 20))
        self.assertIn("Weaken", self.mob("first_ore", 100))
        self.assertIsNone(self.mob("press", 100))
        self.assertIn("Weaken", self.mob("press", 2000))
        self.assertIsNone(self.mob("quarry", 100000, 500))


class Automation(unittest.TestCase):
    def automates(self, at, what, rate):
        return check({"a": feature("a", at, automation=[{"what": what, "per_minute": rate}])})

    def test_nothing_runs_by_itself_in_the_early_game(self):
        self.assertIn("themselves", self.automates("first_ore", "crafting", 1))

    def test_mid_game_mining_and_killing_are_very_slow(self):
        self.assertIsNone(self.automates("press", "mining", 6))
        self.assertIn("Slow it down", self.automates("press", "mining", 60))
        self.assertIsNone(self.automates("press", "mob_killing", 1))
        self.assertIn("Slow it down", self.automates("press", "mob_killing", 5))

    def test_mid_game_crafting_is_allowed(self):
        self.assertIsNone(self.automates("press", "crafting", 20))
        self.assertIsNone(self.automates("press", "sorting", 150))

    def test_the_endgame_can_have_a_quarry(self):
        self.assertIsNone(self.automates("quarry", "mining", 100000))

    def test_what_it_does_and_how_fast_have_to_be_said(self):
        self.assertIn("Say which", self.automates("press", "everything", 1))
        self.assertIn("per_minute", self.automates("press", "mining", None))


class WhatPlayersAlreadyHave(unittest.TestCase):
    LEDGER = {"items": {"a/pick": {"slot": "i0001"}, "a/other": {"slot": "i0002"}}}

    def run_gate(self, manifest_extra=None, old="old", new="new", reached=("gm:i0001",)):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / "knowledge.json").write_text(json.dumps({"found": {"someone": list(reached)}}), encoding="utf-8")
            features = {"a": feature("a", items={"pick": {}, "other": {}}, **(manifest_extra or {}))}
            try:
                gate.run(features, root, self.LEDGER, {"a/pick": old}, root / "knowledge.json", {"a/pick": new})
            except GateFailed as error:
                return error.message
        return None

    def test_changing_something_players_have_is_refused(self):
        self.assertIn("Players already have a/pick", self.run_gate())

    def test_a_clear_reason_lets_it_through(self):
        self.assertIsNone(self.run_gate({"changes_reached": {"pick": "Players said it breaks far too quickly"}}))

    def test_a_word_isnt_a_reason(self):
        self.assertIn("Players already have", self.run_gate({"changes_reached": {"pick": "nerf"}}))

    def test_leaving_it_alone_passes(self):
        self.assertIsNone(self.run_gate(new="old"))

    def test_changing_what_nobody_has_reached_is_fine(self):
        self.assertIsNone(self.run_gate(reached=("gm:i0002",)))

    def test_a_fingerprint_notices_a_new_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            plain = {"a": {"manifest": {"id": "a", "items": {"x": {}}}, "dir": pathlib.Path(folder)}}
            with_recipe = {"a": {"manifest": {"id": "a", "items": {"x": {}}, "recipes": {"x": craft("minecraft:stick", makes="$item:x")}},
                                 "dir": pathlib.Path(folder)}}
            self.assertNotEqual(gate.snapshot(plain)["a/x"], gate.snapshot(with_recipe)["a/x"])


class Tuning(unittest.TestCase):
    REASON = "Two players said it was too rare"

    def manifest(self):
        return {"id": "a", "ores": [{"id": "ore_v1", "block": "ore", "veinsPerChunk": 3, "veinSize": 7}],
                "plants": [{"id": "moss_v1", "block": "moss", "perChunk": 1.0}],
                "blocks": {"ore": {"drops": {"item": "raw", "count": [1, 2]}}},
                "mobs": {"crab": {"health": 8, "spawn": {"weight": 10}}},
                "items": {"pick": {"stats": {"durability": 100}, "components": {
                    "minecraft:max_damage": 100,
                    "minecraft:food": {"nutrition": 2, "saturation": 1.0},
                    "minecraft:tool": {"rules": [{"blocks": "#minecraft:mineable/pickaxe", "speed": 4, "correct_for_drops": True}]},
                    "minecraft:attribute_modifiers": [{"type": "minecraft:attack_damage", "amount": 3, "operation": "add_value", "slot": "mainhand"}]}}},
                "recipes": {"cook": {"json": {"type": "minecraft:smelting", "cookingtime": 200, "result": {"id": "$item:pick"}}}}}

    def apply(self, manifest, *args):
        tuning.apply(manifest, *args, self.REASON)
        return manifest

    def test_more_ore_is_a_new_entry_for_the_difference(self):
        ores = self.apply(self.manifest(), "ores", "ore_v1", "veinsPerChunk", 5)["ores"]
        self.assertEqual(len(ores), 2)
        self.assertEqual(ores[1]["veinsPerChunk"], 2)
        self.assertNotEqual(ores[1]["id"], "ore_v1")

    def test_a_second_raise_counts_the_first(self):
        manifest = self.apply(self.manifest(), "ores", "ore_v1", "veinsPerChunk", 5)
        ores = self.apply(manifest, "ores", "ore_v1", "veinsPerChunk", 6)["ores"]
        self.assertEqual(ores[2]["veinsPerChunk"], 1)
        self.assertEqual(len({ore["id"] for ore in ores}), 3)

    def test_veins_stay_whole_numbers(self):
        ores = self.apply(self.manifest(), "ores", "ore_v1", "veinsPerChunk", 4.5)["ores"]
        self.assertEqual(ores[1]["veinsPerChunk"], 2)

    def test_ore_in_the_world_cant_be_taken_back_out(self):
        with self.assertRaisesRegex(tuning.TuneError, "can't be taken out"):
            self.apply(self.manifest(), "ores", "ore_v1", "veinsPerChunk", 1)

    def test_more_plants_work_the_same_way(self):
        self.assertEqual(self.apply(self.manifest(), "plants", "moss_v1", "perChunk", 2.5)["plants"][1]["perChunk"], 1.5)

    def test_an_items_real_numbers_change_along_with_what_it_states(self):
        item = self.apply(self.manifest(), "items", "pick", "durability", 200)["items"]["pick"]
        self.assertEqual(item["stats"]["durability"], 200)
        self.assertEqual(item["components"]["minecraft:max_damage"], 200)

    def test_attack_damage_is_what_the_tooltip_says(self):
        item = self.apply(self.manifest(), "items", "pick", "attack_damage", 6)["items"]["pick"]
        self.assertEqual(item["components"]["minecraft:attribute_modifiers"][0]["amount"], 5)

    def test_food_and_mining_speed(self):
        item = self.apply(self.manifest(), "items", "pick", "nutrition", 5)["items"]["pick"]
        self.assertEqual(item["components"]["minecraft:food"]["nutrition"], 5)
        item = self.apply(self.manifest(), "items", "pick", "mining_speed", 7)["items"]["pick"]
        self.assertEqual(item["components"]["minecraft:tool"]["rules"][0]["speed"], 7)

    def test_mobs_blocks_and_recipes(self):
        self.assertEqual(self.apply(self.manifest(), "mobs", "crab", "spawn.weight", 5)["mobs"]["crab"]["spawn"]["weight"], 5)
        self.assertEqual(self.apply(self.manifest(), "blocks", "ore", "drops.count", [2, 3])["blocks"]["ore"]["drops"]["count"], [2, 3])
        self.assertEqual(self.apply(self.manifest(), "recipes", "cook", "json.cookingtime", 100)["recipes"]["cook"]["json"]["cookingtime"], 100)

    def test_the_reason_is_recorded_for_the_gate(self):
        self.assertEqual(self.apply(self.manifest(), "items", "pick", "durability", 200)["changes_reached"]["pick"], self.REASON)
        self.assertEqual(self.apply(self.manifest(), "ores", "ore_v1", "veinsPerChunk", 5)["changes_reached"]["ore"], self.REASON)
        self.assertEqual(self.apply(self.manifest(), "recipes", "cook", "json.cookingtime", 100)["changes_reached"]["pick"], self.REASON)

    def test_only_listed_numbers_can_change(self):
        for table, name, field, value in (("items", "pick", "display", "Better"), ("mobs", "crab", "model", "other"), ("blocks", "ore", "family", "stone"),
                                          ("items", "pick", "armor", 5), ("items", "nothing", "durability", 5), ("feature", "a", "node", "x")):
            with self.assertRaises(tuning.TuneError, msg=field):
                self.apply(self.manifest(), table, name, field, value)

    def test_bad_values_are_refused(self):
        for table, name, field, value in (("items", "pick", "durability", -1), ("items", "pick", "durability", float("inf")), ("items", "pick", "durability", True),
                                          ("blocks", "ore", "drops.count", 3), ("blocks", "ore", "drops.count", [3, 1])):
            with self.assertRaises(tuning.TuneError, msg=str(value)):
                self.apply(self.manifest(), table, name, field, value)

    def test_a_reason_is_needed(self):
        with self.assertRaises(tuning.TuneError):
            tuning.apply(self.manifest(), "items", "pick", "durability", 200, "because")


class WorldDiff(unittest.TestCase):
    CHEST = {"id": "minecraft:chest", "x": 1, "y": 2, "z": 3, "Items": []}
    MACHINE = {"id": "gm:machine", "x": 4, "y": 2, "z": 3, "machine": {}}
    GRAVEL = {"id": "minecraft:brushable_block", "x": 1, "y": 9, "z": 3}
    SULFUR = {"id": "minecraft:potent_sulfur", "x": 7, "y": 9, "z": 3, "countdown": 5}

    def test_a_falling_block_taking_its_record_with_it_is_natural(self):
        self.assertTrue(world_diff.entities_kept([self.CHEST, self.GRAVEL], [self.CHEST], False))
        self.assertTrue(world_diff.entities_kept([self.CHEST, self.GRAVEL], [self.CHEST, {**self.GRAVEL, "y": 5}], False))

    def test_timers_the_game_runs_by_itself_are_natural(self):
        self.assertTrue(world_diff.entities_kept([self.CHEST, self.SULFUR], [self.CHEST, {**self.SULFUR, "countdown": 4}], False))

    def test_a_busy_furnace_is_natural(self):
        furnace = {"id": "minecraft:furnace", "x": 2, "y": 2, "z": 3, "Items": [1, 2]}
        self.assertTrue(world_diff.entities_kept([furnace], [{**furnace, "Items": [1]}], False))

    def test_losing_something_that_holds_items_is_not(self):
        self.assertFalse(world_diff.entities_kept([self.CHEST, self.GRAVEL], [self.GRAVEL], False))
        self.assertFalse(world_diff.entities_kept([self.CHEST], [self.CHEST | {"id": "minecraft:barrel"}], False))

    def test_losing_a_machine_is_not(self):
        self.assertFalse(world_diff.entities_kept([self.MACHINE], [], False))

    def test_a_new_chest_needs_a_ruin_to_explain_it(self):
        self.assertFalse(world_diff.entities_kept([], [self.CHEST], False))
        self.assertTrue(world_diff.entities_kept([], [self.CHEST], True))


class WorldIndex(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = pathlib.Path(self.folder.name)
        self.features = root / "mods/genesis/features"
        (root / "bible").mkdir()
        graph.save(root / "bible/progression.json", WORLD)
        manifest = {"id": "ore", "node": "first_ore", "summary": "The first metal.",
                    "blocks": {"ore": {"display": "Tin Ore", "family": "ore", "tool_level": "stone", "drops": {"item": "raw", "count": [1, 2]}}},
                    "items": {"raw": {"display": "Raw Tin"}, "pick": {"display": "Tin Pick", "tier": "stone", "components": {"minecraft:tool": {}, "minecraft:max_damage": 131}}},
                    "ores": [{"id": "ore_v1", "block": "ore", "veinsPerChunk": 3, "veinSize": 7, "minY": 0, "maxY": 40}],
                    "recipes": {"pick": craft("$item:raw", makes="$item:pick")}}
        (self.features / "ore").mkdir(parents=True)
        (self.features / "ore/feature.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_it_lists_everything_by_where_it_sits(self):
        text = world_index.build(self.features)
        self.assertIn("Goal: Wake the machine", text)
        self.assertLess(text.index("early: first_ore"), text.index("mid: press"))
        self.assertLess(text.index("mid: press"), text.index("end: quarry"))
        for wanted in ("$block:ore/ore", "$item:ore/pick", "tier stone", "durability 131", "3 veins of 7", "Comes after: first_ore", "Nothing built here yet"):
            self.assertIn(wanted, text)

    def test_it_marks_what_players_have(self):
        text = world_index.build(self.features, ["Raw Tin"])
        marked = [line for line in text.splitlines() if "players have this" in line]
        self.assertEqual(len(marked), 1)
        self.assertIn("Raw Tin", marked[0])

    def test_it_knows_which_nodes_players_have_reached(self):
        self.assertEqual(world_index.reached_nodes(self.features, ["Raw Tin"]), {"first_ore"})
        self.assertEqual(world_index.reached_nodes(self.features, []), set())


if __name__ == "__main__":
    unittest.main()
