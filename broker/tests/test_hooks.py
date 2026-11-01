"""What the release gates and the bundler make of the engine's newer hooks: sounds by name, a mob's own sounds, what a block drops,
and ruins that vary. No servers needed.

Usage: python3 -m unittest broker.tests.test_hooks
"""
import hashlib
import json
import pathlib
import tempfile
import unittest

from broker import bundles, promote
from broker.gates import GateFailed, advice, balance, static
from broker.tests.test_balance import feature, from_iron, shapeless
from orchestrator import tuning, world_index

GROUND = ["minecraft:grass_block"]
OPEN = ["minecraft:air"]
STONE = {"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"}
LOOT = {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "$item:tablet"}]}]}
POOL = {"families": {"stone": {"first": 0, "count": 4}}, "item_count": 4, "mobs": {"monster": 1, "creature": 1}}


def ruin(**fields):
    return {"id": "r_v1", "parts": [{"x": 1, "y": 0, "z": 1, "block": "minecraft:stone"}], "on": GROUND, "replaces": OPEN,
            "chance": 0.1, "minY": 0, "maxY": 200, **fields}


def without(entry, *names):
    return {key: value for key, value in entry.items() if key not in names}


def features(*ruins):
    return {"f": {"manifest": {"ruins": {f"r{index}": entry for index, entry in enumerate(ruins)}}}}


class BlockSettings(unittest.TestCase):
    def manifest(self, name="thing", **fields):
        return {"blocks": {name: {"family": "stone", "display": "Thing", "texture": "thing", **fields}}}

    def assert_fine(self, **fields):
        static.check_block_kinds({"f": {"manifest": self.manifest(**fields), "dir": pathlib.Path("nowhere")}})

    def assert_refused(self, mention, **fields):
        with self.assertRaises(GateFailed) as caught:
            static.check_block_kinds({"f": {"manifest": self.manifest(**fields), "dir": pathlib.Path("nowhere")}})
        self.assertIn(mention, caught.exception.message)

    def test_facing_takes_a_family_that_can_turn(self):
        self.assert_fine(family="facing", facing="all")
        self.assert_fine(family="facing_machine", facing="horizontal")
        self.assert_fine(family="model", model="nothing", facing="horizontal")
        self.assert_refused("only a facing", facing="horizontal")
        self.assert_refused("Use ['all', 'horizontal']", family="facing", facing="sideways")

    def test_light_is_a_level(self):
        self.assert_fine(light=0)
        self.assert_fine(light=15)
        for wrong in (16, -1, 2.5, True, "bright"):
            self.assert_refused("from 0 to 15", light=wrong)

    def test_flags_are_flags(self):
        self.assert_fine(redstone=True, comparator=False, unbreakable=True)
        self.assert_refused("true or false", redstone="yes")

    def test_unbreakable_with_a_hardness_says_two_things(self):
        self.assert_refused("only one of them", unbreakable=True, hardness=1)

    def test_only_a_model_has_glowing_parts(self):
        self.assert_refused("only a model block", glowing=["eyes"])
        self.assert_refused("a list of the names", family="model", model="nothing", glowing="eyes")

    def test_glowing_parts_have_to_be_in_the_model(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "assets" / "models"
            path.mkdir(parents=True)
            (path / "lamp.bbmodel").write_text(json.dumps({"outliner": [{"name": "root", "children": [{"name": "eyes", "children": []}]}]}), encoding="utf-8")
            block = {"family": "model", "display": "Lamp", "texture": "lamp", "model": "lamp"}
            static.check_block_kinds({"f": {"manifest": {"blocks": {"lamp": {**block, "glowing": ["eyes", "root"]}}}, "dir": pathlib.Path(folder)}})
            with self.assertRaises(GateFailed) as caught:
                static.check_block_kinds({"f": {"manifest": {"blocks": {"lamp": {**block, "glowing": ["tail"]}}}, "dir": pathlib.Path(folder)}})
            self.assertIn("['tail']", caught.exception.message)

    def test_a_player_can_never_be_handed_an_unbreakable_block(self):
        def with_it(**tables):
            return {"f": {"manifest": {**self.manifest(unbreakable=True), **tables}, "dir": pathlib.Path("nowhere")}}

        crafted = {"r": {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["minecraft:stone"], "result": {"id": "$block:thing"}}}}
        for tables in ({"recipes": crafted}, {"items": {"seed": {"display": "Seed", "places": {"block": "$block:thing"}}}},
                       {"recipes": {"r": {"mode": "open", "machine": "press", "inputs": [], "output": {"item": "$block:thing", "count": 1}}}}):
            with self.assertRaises(GateFailed) as caught:
                static.check_block_kinds(with_it(**tables))
            self.assertIn("never remove", caught.exception.message)
        static.check_block_kinds(with_it(recipes={"r": {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["$block:thing"], "result": {"id": "minecraft:stone"}}}}))


class MachineLimits(unittest.TestCase):
    def check(self, inventory):
        static.check_machines({"f": {"manifest": {"blocks": {"press": {"family": "facing_machine", "inventory": inventory}}}}})

    def test_limits_by_slot(self):
        self.check({"inputs": 2, "outputs": 1, "limits": {"0": 1, "2": 16}})

    def test_limits_dont_count_as_slots(self):
        with self.assertRaises(GateFailed) as caught:
            self.check({"limits": {"0": 1}})
        self.assertIn("0 slots", caught.exception.message)

    def test_wrong_limits(self):
        for limits in ({"3": 1}, {"0": 0}, {"0": 100}, {"east": 1}, {"0": True}, [1]):
            with self.assertRaises(GateFailed) as caught:
                self.check({"inputs": 2, "outputs": 1, "limits": limits})
            self.assertIn("how many fit in a slot", caught.exception.message)


class RenderedBlockSettings(unittest.TestCase):
    def render(self, **fields):
        block = {"family": "facing", "display": "Thing", "texture": "thing", **fields}
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            textures = root / "f" / "assets" / "textures"
            textures.mkdir(parents=True)
            from PIL import Image
            Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(textures / "thing.png")
            features = {"f": {"manifest": {"id": "f", "blocks": {"thing": block}}, "dir": root / "f"}}
            pool = {"families": {"facing": {"first": 2700, "count": 4}}, "item_count": 4, "mobs": {"monster": 1, "creature": 1}}
            ledger = bundles.assign_slots(features, bundles.empty_ledger(), pool)
            bundles.render(features, ledger, root / "out", 1)
            slot = ledger["blocks"]["f/thing"]["slot"]
            settings = json.loads((root / "out" / "config" / "block_settings.json").read_text(encoding="utf-8")).get(slot, {})
            tags = {path.stem for path in (root / "out" / "datapack" / "data" / "minecraft" / "tags" / "block").glob("*.json")}
            return settings, tags

    def test_a_facing_block_turns_unless_it_says_how(self):
        self.assertEqual(self.render()[0]["facing"], "horizontal")
        self.assertEqual(self.render(facing="all")[0]["facing"], "all")

    def test_settings_reach_the_server(self):
        settings, _ = self.render(light=9, redstone=True, comparator=True, unbreakable=True)
        self.assertEqual((settings["light"], settings["redstone"], settings["comparator"], settings["unbreakable"]), (9, True, True, True))

    def test_nothing_that_breaks_blocks_can_break_an_unbreakable_one(self):
        self.assertEqual(self.render(unbreakable=True)[1] & {"wither_immune", "dragon_immune"}, {"wither_immune", "dragon_immune"})
        self.assertFalse(self.render()[1] & {"wither_immune", "dragon_immune"})


class MobFields(unittest.TestCase):
    def assert_refused(self, mention, **fields):
        with self.assertRaises(GateFailed) as caught:
            static.check_mobs({"f": {"manifest": {"mobs": {"bat": fields}}, "dir": pathlib.Path("nowhere")}})
        self.assertIn(mention, caught.exception.message)

    def test_fine(self):
        static.check_mobs({"f": {"manifest": {"mobs": {"bat": {"flying": True, "knockback_resistance": 0.5, "glowing": ["eyes"],
                                                               "drops": [{"item": "fang", "chance": 0.5}, {"item": "wing"}]}}}, "dir": pathlib.Path("nowhere")}})

    def test_wrong(self):
        self.assert_refused("true or false", flying="yes")
        for resistance in (-0.1, 1.5, "lots", True):
            self.assert_refused("from 0 to 1", knockback_resistance=resistance)
        self.assert_refused("above 0", drops=[{"item": "fang", "chance": 0}])
        self.assert_refused("a list of the names", glowing="eyes")

    def test_a_glowing_part_has_to_be_in_its_model(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "assets" / "models"
            path.mkdir(parents=True)
            (path / "bat.bbmodel").write_text(json.dumps({"outliner": [{"name": "eyes", "children": []}]}), encoding="utf-8")
            static.check_mobs({"f": {"manifest": {"mobs": {"bat": {"glowing": ["eyes"]}}}, "dir": pathlib.Path(folder)}})
            with self.assertRaises(GateFailed) as caught:
                static.check_mobs({"f": {"manifest": {"mobs": {"bat": {"glowing": ["wings"]}}}, "dir": pathlib.Path(folder)}})
            self.assertIn("['wings']", caught.exception.message)


class MobDrops(unittest.TestCase):
    def render(self, drops):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            models = root / "f" / "assets" / "models"
            models.mkdir(parents=True)
            (models / "bat.bbmodel").write_text("{}", encoding="utf-8")
            features = {"f": {"manifest": {"id": "f", "items": {"fang": {"display": "Fang"}, "wing": {"display": "Wing"}}, "mobs": {"bat": {"category": "creature", "display": "Bat", "model": "bat", "drops": drops}}}, "dir": root / "f"}}
            ledger = {**bundles.empty_ledger(), "items": {"f/fang": {"slot": "i0001", "index": 0}, "f/wing": {"slot": "i0002", "index": 1}},
                      "mobs": {"f/bat": {"slot": "e0001", "category": "creature", "index": 0}}}
            bundles._render_mob(features["f"], "f", "bat", features["f"]["manifest"]["mobs"]["bat"], ledger, bundles.LanguageFiles({}), root / "datapack", root / "config")
            return json.loads((root / "datapack" / "data" / "gm" / "loot_table" / "entities" / "e0001.json").read_text(encoding="utf-8"))

    def test_one_still_works(self):
        pools = self.render({"item": "fang", "count": [1, 2]})["pools"]
        self.assertEqual(len(pools), 1)
        self.assertEqual(pools[0]["entries"][0]["name"], "gm:i0001")

    def test_each_of_several_has_its_own_pool(self):
        pools = self.render([{"item": "fang"}, {"item": "wing", "chance": 0.25}])["pools"]
        self.assertEqual([pool["entries"][0]["name"] for pool in pools], ["gm:i0001", "gm:i0002"])
        self.assertNotIn("condition", pools[0])
        self.assertEqual(pools[1]["condition"], {"type": "minecraft:random_chance", "chance": 0.25})

    def test_vanillas_items_are_still_refused(self):
        with self.assertRaises(bundles.BundleError):
            self.render([{"item": "fang"}, {"item": "minecraft:diamond"}])

    def test_each_counts_as_a_source(self):
        mob = {"drops": [{"item": "fang"}, {"item": "wing"}]}
        self.assertEqual({drop["item"] for drop in balance.drops_of(mob)}, {"fang", "wing"})


class RuinRules(unittest.TestCase):
    def assert_fine(self, entry):
        static.check_ruins(features(entry))

    def assert_refused(self, entry, *mentions):
        with self.assertRaises(GateFailed) as caught:
            static.check_ruins(features(entry))
        self.assertEqual(caught.exception.gate, "static")
        for mention in mentions:
            self.assertIn(mention, caught.exception.message)

    def test_a_plain_ruin_is_still_fine(self):
        self.assert_fine(ruin())

    def test_every_new_field_together(self):
        self.assert_fine(ruin(followTerrain=True, maxSlope=4, spacing=20, chance=0.5,
                              parts=[{"x": 15, "y": -1, "z": 0, "block": "minecraft:stone", "chance": 0.25}]))

    def test_layouts_instead_of_parts(self):
        layouts = [[{"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"}], [{"x": 1, "y": 0, "z": 1, "block": "minecraft:dirt"}]]
        self.assert_fine(without(ruin(layouts=layouts), "parts"))

    def test_neither_parts_nor_layouts(self):
        self.assert_refused(without(ruin(), "parts"), "either parts")

    def test_both_parts_and_layouts(self):
        self.assert_refused(ruin(layouts=[[{"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"}]]), "and not both")

    def test_an_empty_layout(self):
        self.assert_refused(without(ruin(layouts=[[{"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"}], []]), "parts"), "nothing in it")

    def test_outside_the_chunk(self):
        self.assert_refused(ruin(parts=[{"x": 16, "y": 0, "z": 0, "block": "minecraft:stone"}]), "fit in one chunk")
        self.assert_refused(ruin(parts=[{"x": 0, "y": 0, "z": -1, "block": "minecraft:stone"}]), "fit in one chunk")
        self.assert_refused(ruin(parts=[{"x": "east", "y": 0, "z": 0, "block": "minecraft:stone"}]), "fit in one chunk")
        self.assert_refused(ruin(parts=[{"y": 0, "block": "minecraft:stone"}]), "fit in one chunk")

    def test_a_part_chance_has_to_be_a_share(self):
        for chance in (0, 1.5, "half", True):
            self.assert_refused(ruin(parts=[{"x": 0, "y": 0, "z": 0, "block": "minecraft:stone", "chance": chance}]), "above 0")

    def test_spacing_has_to_be_whole_chunks(self):
        for spacing in (0, -3, 2.5, True):
            self.assert_refused(ruin(spacing=spacing), "whole number of chunks")

    def test_with_no_chance_or_spacing_it_would_never_appear(self):
        self.assert_refused(without(ruin(), "chance"), "never appear")

    def test_spacing_is_enough_by_itself(self):
        self.assert_fine(without(ruin(spacing=8), "chance"))

    def test_nothing_underground_has_terrain_to_follow(self):
        self.assert_refused(ruin(followTerrain=True, underground=True), "terrain to follow")

    def test_max_slope_needs_terrain_to_follow(self):
        self.assert_refused(ruin(maxSlope=4), "only means something")
        self.assert_refused(ruin(followTerrain=True, maxSlope=-1), "whole number of blocks")

    def test_a_part_can_set_a_block_state(self):
        for block in ("minecraft:ladder[facing=north]", "minecraft:lantern[hanging=true,waterlogged=false]", "$block:wall[facing=north]"):
            self.assert_fine(ruin(parts=[{**STONE, "block": block}]))

    def test_a_block_state_has_to_be_readable(self):
        for block in ("minecraft:ladder[facing]", "minecraft:ladder[facing=north", "minecraft:ladder[]", "minecraft:ladder[facing=north] x"):
            self.assert_refused(ruin(parts=[{**STONE, "block": block}]), "like minecraft:ladder[facing=north]")
        self.assert_refused(ruin(parts=[{"x": 0, "y": 0, "z": 0}]), "like minecraft:ladder[facing=north]")

    def test_a_container_can_have_its_own_loot(self):
        for block in ("minecraft:chest", "minecraft:barrel[facing=up]", "minecraft:blue_shulker_box", "minecraft:shulker_box", "minecraft:waxed_exposed_copper_chest"):
            self.assert_fine(ruin(parts=[{**STONE, "block": block, "loot": LOOT}]))

    def test_only_a_container_can_have_loot(self):
        for block in ("minecraft:stone", "minecraft:ender_chest", "$block:chest"):
            self.assert_refused(ruin(parts=[{**STONE, "block": block, "loot": LOOT}]), "can't hold any")

    def test_a_parts_loot_has_to_be_a_table(self):
        self.assert_refused(ruin(parts=[{**STONE, "block": "minecraft:chest", "loot": "minecraft:chests/igloo_chest"}]), "isn't a loot table")

    def test_a_parts_loot_is_held_to_the_same_format(self):
        old = {"type": "minecraft:chest", "pools": [{"rolls": 1, "conditions": [], "entries": []}]}
        with self.assertRaises(GateFailed) as caught:
            static.check_loot_format(features(ruin(parts=[{**STONE, "block": "minecraft:chest", "loot": old}])))
        self.assertIn("conditions", caught.exception.message)

    def test_high_ground(self):
        self.assert_fine(ruin(highGround=3))
        self.assert_fine(ruin(highGround=3, followTerrain=True))
        for rise in (0, -1, 2.5, True, "yes"):
            self.assert_refused(ruin(highGround=rise), "whole number of blocks")
        self.assert_refused(ruin(highGround=3, underground=True), "on the surface")


class RuinsElsewhere(unittest.TestCase):
    """Everywhere else that reads a ruin has to see a block that's only in one of its layouts."""

    LAYOUTS = [[{"x": 0, "y": 0, "z": 0, "block": "$block:first"}], [{"x": 1, "y": 0, "z": 1, "block": "$block:second"}]]

    def test_a_block_in_any_layout_can_be_had(self):
        placed, _ = balance._natural_sources({"f": {"manifest": {"ruins": {"r": {"layouts": self.LAYOUTS}}}}})
        self.assertEqual(placed, {"block:f/first", "block:f/second"})

    def test_the_world_diff_is_told_about_every_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            new, old = pathlib.Path(folder, "new"), pathlib.Path(folder, "old")
            (new / "config").mkdir(parents=True)
            (old / "config").mkdir(parents=True)
            (new / "config" / "ruin_patches.json").write_text(json.dumps([{"id": "r_v1", "replaces": OPEN, "layouts": [
                [{"block": "gm:s0001"}], [{"block": "gm:s0002"}, {"block": "gm:s0001"}]]}]), encoding="utf-8")
            found = promote.patches_changed(new, old)
        self.assertEqual({patch["block"] for patch in found}, {"gm:s0001", "gm:s0002"})

    def test_a_block_with_a_state_is_still_that_block(self):
        placed, _ = balance._natural_sources({"f": {"manifest": {"ruins": {"r": {"parts": [{**STONE, "block": "$block:wall[facing=north]"}]}}}}})
        self.assertEqual(placed, {"block:f/wall"})

    def test_the_loot_in_one_container_can_be_had(self):
        _, handed_out = balance._natural_sources({"f": {"manifest": {"ruins": {"r": {"parts": [{**STONE, "block": "minecraft:chest", "loot": LOOT}]}}}}})
        self.assertEqual(handed_out, {"item:f/tablet"})

    def test_the_world_diff_goes_by_the_block_and_not_its_state(self):
        with tempfile.TemporaryDirectory() as folder:
            new, old = pathlib.Path(folder, "new"), pathlib.Path(folder, "old")
            (new / "config").mkdir(parents=True)
            (old / "config").mkdir(parents=True)
            (new / "config" / "ruin_patches.json").write_text(json.dumps([{"id": "r_v1", "replaces": OPEN, "parts": [
                {"block": "minecraft:ladder[facing=north]"}, {"block": "minecraft:ladder[facing=south]"}]}]), encoding="utf-8")
            found = promote.patches_changed(new, old)
        self.assertEqual([patch["block"] for patch in found], ["minecraft:ladder"])

    def test_the_voices_know_what_one_container_holds(self):
        with tempfile.TemporaryDirectory() as folder:
            feature_dir = pathlib.Path(folder, "camps")
            feature_dir.mkdir()
            own = {"pools": [{"entries": [{"name": "minecraft:flint"}]}]}
            (feature_dir / "feature.json").write_text(json.dumps({"id": "camps", "summary": "Camps.", "ruins": {
                "old_camp": {"chance": 0.5, "minY": 50, "maxY": 140, "parts": [{"x": 1, "block": "minecraft:chest", "loot": own}]}}}), encoding="utf-8")
            guide = world_index.player_entry(pathlib.Path(folder), "camps")
        self.assertIn("flint", guide)

    def test_the_voices_say_how_far_apart_they_are(self):
        with tempfile.TemporaryDirectory() as folder:
            feature = pathlib.Path(folder, "camps")
            feature.mkdir()
            (feature / "feature.json").write_text(json.dumps({"id": "camps", "summary": "Camps.", "ruins": {
                "old_camp": {"spacing": 20, "chance": 0.5, "minY": 50, "maxY": 140, "parts": [{"x": 1}]}}}), encoding="utf-8")
            guide = world_index.player_entry(pathlib.Path(folder), "camps")
        self.assertIn("at least 20 chunks apart", guide)
        self.assertNotIn("one chunk in", guide)


class RuinLootTables(unittest.TestCase):
    def render(self, entry):
        ledger = {"blocks": {}, "items": {"f/tablet": {"slot": "i0000"}}, "mobs": {}}
        with tempfile.TemporaryDirectory() as folder:
            datapack = pathlib.Path(folder)
            patch = bundles._render_ruin("f", "r", entry, ledger, datapack)
            tables = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in (datapack / "data/gm/loot_table/chests").glob("*.json")}
        return patch, tables

    def test_a_ruins_own_table_keeps_the_name_it_always_had(self):
        # Chests nobody has opened yet are out there in the world, looking for it by this name.
        patch, _ = self.render(ruin(loot=LOOT))
        self.assertEqual(patch["loot"], "gm:chests/l" + hashlib.sha256(b"f/r").hexdigest()[:10])

    def test_each_container_gets_a_table_of_its_own(self):
        other = {"type": "minecraft:chest", "pools": []}
        parts = [{**STONE, "block": "minecraft:chest", "loot": LOOT}, {**STONE, "x": 1, "block": "minecraft:barrel", "loot": other}, {**STONE, "x": 2, "block": "minecraft:chest"}]
        patch, tables = self.render(ruin(parts=parts, loot=other))
        first, second, third = patch["parts"]
        self.assertNotEqual(first["loot"], second["loot"])
        self.assertNotIn("loot", third)
        self.assertEqual(len(tables), 3)
        self.assertEqual(tables[first["loot"].rsplit("/", 1)[1]]["pools"][0]["entries"][0]["name"], "gm:i0000")

    def test_the_same_spot_in_two_layouts_doesnt_clash(self):
        layouts = [[{**STONE, "block": "minecraft:chest", "loot": LOOT}], [{**STONE, "block": "minecraft:chest", "loot": {"type": "minecraft:chest", "pools": []}}]]
        patch, tables = self.render(without(ruin(layouts=layouts), "parts"))
        self.assertNotEqual(patch["layouts"][0][0]["loot"], patch["layouts"][1][0]["loot"])
        self.assertEqual(len(tables), 2)

    def test_a_table_keeps_its_name_when_whats_in_it_changes(self):
        first, _ = self.render(ruin(parts=[{**STONE, "block": "minecraft:chest", "loot": LOOT}]))
        second, _ = self.render(ruin(parts=[{**STONE, "block": "minecraft:chest", "loot": {"type": "minecraft:chest", "pools": []}}]))
        self.assertEqual(first["parts"][0]["loot"], second["parts"][0]["loot"])

    def test_a_block_state_survives_rendering(self):
        ledger = {"blocks": {"f/wall": {"slot": "s0001"}}, "items": {}, "mobs": {}}
        with tempfile.TemporaryDirectory() as folder:
            patch = bundles._render_ruin("f", "r", ruin(parts=[{**STONE, "block": "$block:wall[facing=north]"}]), ledger, pathlib.Path(folder))
        self.assertEqual(patch["parts"][0]["block"], "gm:s0001[facing=north]")


class BlockDrops(unittest.TestCase):
    LEDGER = {"blocks": {}, "items": {"f/gem": {"slot": "i0001"}, "f/dust": {"slot": "i0002"}}, "mobs": {}}

    def table(self, **block):
        return bundles._loot_table(block, "b", "s0000", "f", self.LEDGER)

    def outcome(self, **block):
        """What's dropped when silk touch doesn't apply."""
        return self.table(**block)["pools"][0]["entries"][0]["children"][1]

    def test_one_of_this_worlds_is_as_it_was(self):
        self.assertEqual(self.outcome(drops={"item": "gem"})["name"], "gm:i0001")
        self.assertEqual(len(self.table(drops={"item": "gem"})["pools"]), 1)

    def test_vanillas_goes_by_its_own_name(self):
        entry = self.outcome(drops={"item": "minecraft:copper_ingot", "count": [1, 3]})
        self.assertEqual(entry["name"], "minecraft:copper_ingot")
        self.assertEqual(entry["modifier"][0]["type"], "minecraft:set_count")

    def test_several_all_come_together_unless_its_silk_touch(self):
        first, second = self.table(drops=[{"item": "gem"}, {"item": "minecraft:glass_pane", "count": [2, 2]}])["pools"]
        silk, gem = first["entries"][0]["children"]
        self.assertEqual((silk["name"], gem["name"]), ("gm:s0000", "gm:i0001"))
        # In one pool, the game would pick one of them.
        self.assertEqual(second["entries"][0]["name"], "minecraft:glass_pane")
        self.assertEqual(second["condition"]["type"], "minecraft:inverted")
        self.assertIn("minecraft:tool/can_silk_touch", json.dumps(second["condition"]))

    def test_fortune_works_on_each_of_an_ores(self):
        first, second = self.table(family="ore", drops=[{"item": "gem"}, {"item": "dust"}])["pools"]
        for entry in (first["entries"][0]["children"][1], second["entries"][0]):
            self.assertEqual(entry["modifier"][0]["type"], "minecraft:apply_bonus")

    def test_a_wrong_shape_is_refused(self):
        for drops in ("gem", ["gem"], [{"count": [1, 2]}], {"count": [1, 2]}):
            with self.assertRaises(bundles.BundleError):
                self.table(drops=drops)

    def test_a_mob_still_only_drops_this_worlds_own(self):
        for drops in ({"item": "minecraft:rotten_flesh"}, [{"item": "gem"}]):
            with tempfile.TemporaryDirectory() as folder:
                root = pathlib.Path(folder)
                (root / "feature" / "assets" / "models").mkdir(parents=True)
                (root / "feature" / "assets" / "models" / "m.bbmodel").write_text("{}", encoding="utf-8")
                ledger = {**self.LEDGER, "mobs": {"f/m": {"slot": "e0001"}}}
                with self.assertRaises(bundles.BundleError) as caught:
                    bundles._render_mob({"dir": root / "feature"}, "f", "m", {"display": "M", "drops": drops}, ledger, bundles.LanguageFiles({}), root, root)
                self.assertIn("this world's items", str(caught.exception))

    def test_an_empty_list_is_refused(self):
        with self.assertRaises(GateFailed) as caught:
            static.check_block_drops({"f": feature(blocks={"b": {"drops": []}})})
        self.assertIn("Leave it out", caught.exception.message)

    def assert_passes(self, features):
        balance.run(features)

    def assert_fails(self, features, *mentions):
        with self.assertRaises(GateFailed) as caught:
            balance.run(features)
        for mention in mentions:
            self.assertIn(mention, caught.exception.message)
        return caught.exception.message

    def test_a_vanilla_drop_needs_no_source(self):
        self.assert_passes({"f": feature(blocks={"crate": {"drops": {"item": "minecraft:glass_pane"}}}, recipes={"c": from_iron("$block:crate")})})

    def test_every_one_of_several_can_be_had(self):
        drops = [{"item": "gem"}, {"item": "dust"}, {"item": "minecraft:glass_pane"}]
        self.assert_passes({"f": feature(blocks={"crate": {"drops": drops}}, items={"gem": {}, "dust": {}}, recipes={"c": from_iron("$block:crate")})})

    def test_several_dont_make_a_block_itself_obtainable(self):
        drops = [{"item": "gem"}, {"item": "dust"}]
        ores = [{"id": "o", "block": "ore", "veinsPerChunk": 3, "veinSize": 7, "minY": -40, "maxY": 48}]
        self.assert_fails({"f": feature(blocks={"ore": {"family": "ore", "drops": drops}, "brick": {}}, items={"gem": {}, "dust": {}}, ores=ores,
                                        recipes={"b": shapeless(["$block:ore"], {"id": "$block:brick"})})}, "Nobody can obtain f/brick")

    def test_what_a_ruin_block_drops_can_be_had(self):
        parts = [{**STONE, "block": "$block:wall[facing=north]"}]
        self.assert_passes({"f": feature(blocks={"wall": {"drops": [{"item": "rubble"}, {"item": "minecraft:copper_ingot"}]}}, items={"rubble": {}}, ruins={"r": {"id": "s", "parts": parts}})})

    def test_vanillas_best_cant_be_mined_out_of_a_block(self):
        for drops in ({"item": "minecraft:diamond"}, [{"item": "minecraft:glass_pane"}, {"item": "minecraft:netherite_scrap"}]):
            self.assert_fails({"f": feature(blocks={"crate": {"drops": drops}}, recipes={"c": from_iron("$block:crate")})}, "ruin's loot")

    def test_a_block_cant_make_vanilla_material_from_nothing(self):
        crate = {"drops": {"item": "minecraft:iron_ingot", "count": [2, 2]}}
        self.assert_fails({"f": feature(blocks={"crate": crate}, recipes={"c": from_iron("$block:crate")})}, "from nothing", "breaking f/crate")

    def test_an_average_above_what_went_in_is_too_many(self):
        crate = {"drops": {"item": "minecraft:iron_ingot", "count": [1, 2]}}
        self.assert_fails({"f": feature(blocks={"crate": crate}, recipes={"c": from_iron("$block:crate")})}, "from nothing")

    def test_getting_back_what_went_in_is_fine(self):
        crate = {"drops": {"item": "minecraft:iron_ingot", "count": [1, 1]}}
        self.assert_passes({"f": feature(blocks={"crate": crate}, recipes={"c": from_iron("$block:crate")})})

    def test_a_seed_cant_be_the_way_round_it(self):
        features = {"f": feature(blocks={"bush": {"family": "plant", "drops": {"item": "minecraft:iron_ingot", "count": [2, 2]}}},
                                 items={"seed": {"places": {"block": "$block:bush"}}}, recipes={"s": from_iron("$item:seed")})}
        self.assert_fails(features, "from nothing", "planting f/seed")

    def test_each_of_several_ore_drops_is_measured_for_itself(self):
        def ore(raw_count):
            drops = [{"item": "raw", "count": raw_count}, {"item": "minecraft:flint"}]
            return {"f": feature(blocks={"ore": {"family": "ore", "tier": "iron", "drops": drops}}, items={"raw": {}},
                                 ores=[{"id": "o", "block": "ore", "veinsPerChunk": 10, "veinSize": 9, "minY": -24, "maxY": 56}])}
        self.assert_passes(ore([1, 1]))
        self.assert_fails(ore([3, 3]), "feeds tier iron", "Lower")

    def test_an_ore_doesnt_feed_everything_made_of_the_vanilla_item_it_drops(self):
        gear = shapeless(["minecraft:iron_ingot"], {"id": "$item:blade"})
        self.assert_passes({"f": feature(blocks={"ore": {"family": "ore", "drops": {"item": "minecraft:iron_ingot"}}}, items={"blade": {"tier": "diamond"}}, recipes={"b": gear},
                                         ores=[{"id": "o", "block": "ore", "veinsPerChunk": 10, "veinSize": 9, "minY": -24, "maxY": 56}])})

    def test_the_rest_of_the_tools_can_read_several(self):
        drops = [{"item": "gem", "count": [1, 2]}, {"item": "minecraft:glass_pane"}]
        described = world_index._describe_block({"display": "Crate", "family": "soil", "drops": drops})
        self.assertIn("gem x[1, 2], minecraft:glass_pane x1", described)
        manifest = {"id": "f", "items": {"gem": {}}, "blocks": {"crate": {"family": "soil", "drops": drops}}}
        with tempfile.TemporaryDirectory() as folder:
            advice.run({"f": {"manifest": manifest, "dir": pathlib.Path(folder)}})
            feature_dir = pathlib.Path(folder, "f")
            feature_dir.mkdir()
            (feature_dir / "feature.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertIn("drops", world_index.player_entry(pathlib.Path(folder), "f"))
        with self.assertRaises(tuning.TuneError) as caught:
            tuning.apply(manifest, "blocks", "crate", "drops.count", [2, 3], "players say this block gives too little")
        self.assertIn("builder", str(caught.exception))


class MobSounds(unittest.TestCase):
    def assert_refused(self, sounds, *mentions):
        with self.assertRaises(GateFailed) as caught:
            static.check_mob_sounds({"f": feature(sounds=["yelp"], mobs={"m": {"sounds": sounds}})})
        for mention in mentions:
            self.assertIn(mention, caught.exception.message)

    def test_its_own_vanillas_and_another_features(self):
        features = {"f": feature(sounds=["yelp"], mobs={"m": {"sounds": {"idle": "$sound:yelp", "hurt": "minecraft:entity.pig.hurt", "death": "$sound:other/moan"}}}),
                    "other": feature(sounds=["moan"])}
        static.check_mob_sounds(features)

    def test_it_can_have_any_of_them_or_none(self):
        static.check_mob_sounds({"f": feature(sounds=["yelp"], mobs={"m": {"sounds": {"hurt": "$sound:yelp"}}, "n": {}})})

    def test_a_sound_nobody_lists(self):
        self.assert_refused({"hurt": "$sound:howl"}, "no feature lists")

    def test_a_name_with_no_way_to_tell_whose(self):
        self.assert_refused({"hurt": "yelp"}, "$sound:name")
        self.assert_refused({"hurt": "$item:yelp"}, "$sound:name")

    def test_a_kind_of_sound_nothing_plays(self):
        self.assert_refused({"attack": "$sound:yelp"}, "idle")
        self.assert_refused(["$sound:yelp"], "idle")

    def test_the_server_is_told_which_sound_it_really_is(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / "feature" / "assets" / "models").mkdir(parents=True)
            (root / "feature" / "assets" / "models" / "m.bbmodel").write_text("{}", encoding="utf-8")
            _, definition = bundles._render_mob({"dir": root / "feature"}, "f", "m", {"display": "M", "sounds": {"hurt": "$sound:yelp", "death": "minecraft:entity.pig.death"}},
                                                {"mobs": {"f/m": {"slot": "e0001"}}}, bundles.LanguageFiles({}), root, root)
        self.assertEqual(definition["sounds"], {"hurt": "gm:" + bundles._sound_id("f", "yelp"), "death": "minecraft:entity.pig.death"})


class SoundsByName(unittest.TestCase):
    def render(self, manifest, sounds=("chime",)):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            feature = root / "feature"
            (feature / "assets" / "sounds").mkdir(parents=True)
            for name in sounds:
                (feature / "assets" / "sounds" / f"{name}.ogg").write_bytes(b"OggS")
            (feature / "assets" / "textures").mkdir()
            (feature / "assets" / "textures" / "chime.png").write_bytes(b"png")
            found = {"f": {"manifest": manifest, "dir": feature}}
            ledger = bundles.assign_slots(found, bundles.empty_ledger(), POOL)
            bundles.render(found, ledger, root / "out", 1)
            return json.loads((root / "out" / "config" / "bindings.json").read_text(encoding="utf-8"))

    def test_a_module_can_find_it_by_name(self):
        bindings = self.render({"id": "f", "sounds": ["chime"]})
        # The same name the pack's own sounds.json uses, so what a module plays is what the pack has.
        self.assertEqual(bindings["sound:f/chime"], bundles._sound_id("f", "chime"))

    def test_it_can_share_a_name_with_a_block(self):
        bindings = self.render({"id": "f", "sounds": ["chime"], "blocks": {"chime": {"family": "stone", "display": "Chime"}}})
        self.assertEqual(bindings["f/chime"], "s0000")
        self.assertEqual(bindings["sound:f/chime"], bundles._sound_id("f", "chime"))


if __name__ == "__main__":
    unittest.main()
