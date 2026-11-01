"""What the release gates and the bundler make of machine inventories, crops, connected blocks, items that do more, ore options and
new looks for a mob. No servers needed.

Usage: python3 -m unittest broker.tests.test_bigger
"""
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from PIL import Image

from broker import bundles
from broker.gates import GateFailed, balance, shadow, static
from broker.tests.test_balance import feature, from_iron, shapeless
from orchestrator import tuning, world_index

POOL = {"families": {"stone": {"first": 0, "count": 4}, "machine": {"first": 10, "count": 4}, "crop": {"first": 20, "count": 2}, "connected": {"first": 30, "count": 2},
                     "soil": {"first": 40, "count": 4}, "ore": {"first": 50, "count": 2}, "glow_ore": {"first": 60, "count": 2}},
        "item_count": 8, "mobs": {"monster": 1, "creature": 2}}
TEXTURES = ("t", "t0", "t1", "t2", "t3", "other")
MACHINE_RECIPE = {"mode": "open", "machine": "kiln", "inputs": [{"item": "minecraft:iron_ingot", "count": 2}]}


def refused(check, *mentions, features=None):
    case = unittest.TestCase()
    with case.assertRaises(GateFailed) as caught:
        check(features)
    for mention in mentions:
        case.assertIn(mention, caught.exception.message)
    return caught.exception.message


def render(manifest):
    """Runs the real bundler over one feature, with plain art for anything it asks for, and hands back what it wrote."""
    folder = tempfile.TemporaryDirectory()
    root = pathlib.Path(folder.name)
    source = root / "feature"
    (source / "assets" / "textures").mkdir(parents=True)
    (source / "assets" / "models").mkdir(parents=True)
    for name in TEXTURES:
        Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(source / "assets" / "textures" / f"{name}.png")
    (source / "assets" / "models" / "new_look.bbmodel").write_text("{}", encoding="utf-8")
    (source / "assets" / "models" / "m.bbmodel").write_text("{}", encoding="utf-8")
    found = {manifest["id"]: {"manifest": manifest, "dir": source}}
    ledger = bundles.assign_slots(found, bundles.empty_ledger(), POOL)
    bundles.render(found, ledger, root / "out", 1)
    return folder, root / "out", ledger


def read(folder, *path):
    return json.loads(pathlib.Path(folder, *path).read_text(encoding="utf-8"))


class MachineRules(unittest.TestCase):
    def test_a_machine_can_have_an_inventory(self):
        static.check_machines({"f": feature(blocks={"kiln": {"family": "machine", "inventory": {"inputs": 2, "fuel": 1, "outputs": 1}}})})
        static.check_machines({"f": feature(blocks={"kiln": {"family": "model", "inventory": {"outputs": 1}}})})

    def test_nothing_else_can(self):
        refused(static.check_machines, "only a machine", features={"f": feature(blocks={"chest": {"family": "stone", "inventory": {"inputs": 1}}})})

    def test_the_wrong_shape(self):
        for inventory in ({"inputs": "two"}, {"inputs": -1}, {"sides": 1}, {"inputs": True}, 3):
            refused(static.check_machines, "whole numbers", features={"f": feature(blocks={"kiln": {"family": "machine", "inventory": inventory}})})

    def test_how_many_slots(self):
        for inventory in ({}, {"inputs": 0}, {"inputs": 28}, {"inputs": 20, "outputs": 8}):
            refused(static.check_machines, "from 1 to 27", features={"f": feature(blocks={"kiln": {"family": "machine", "inventory": inventory}})})

    def test_a_recipe_says_what_it_makes_one_way(self):
        output = {"item": "minecraft:gold_ingot", "count": 1}
        static.check_machines({"f": feature(recipes={"a": {**MACHINE_RECIPE, "output": output}})})
        static.check_machines({"f": feature(recipes={"a": {**MACHINE_RECIPE, "outputs": [output, output]}})})
        refused(static.check_machines, "not both", features={"f": feature(recipes={"a": {**MACHINE_RECIPE, "output": output, "outputs": [output]}})})
        refused(static.check_machines, "not both", features={"f": feature(recipes={"a": MACHINE_RECIPE})})
        for made in ([], [{"item": "x"}], ["minecraft:gold_ingot"], "minecraft:gold_ingot"):
            refused(static.check_machines, "outputs", features={"f": feature(recipes={"a": {**MACHINE_RECIPE, "outputs": made}})})

    def test_everything_it_makes_counts_as_had_and_as_made(self):
        recipe = {**MACHINE_RECIPE, "outputs": [{"item": "$item:a", "count": 1}, {"item": "$item:b", "count": 1}]}
        balance.run({"f": feature(items={"a": {}, "b": {}}, recipes={"r": recipe})})
        loop = {"mode": "open", "machine": "kiln", "inputs": [{"item": "$item:a", "count": 1}], "outputs": [{"item": "$item:a", "count": 1}, {"item": "$item:a", "count": 1}]}
        refused(balance.run, "from nothing", features={"f": feature(items={"a": {}}, recipes={"seed": from_iron("$item:a"), "r": loop})})

    def test_the_server_gets_every_output_and_the_layout(self):
        recipe = {**MACHINE_RECIPE, "outputs": [{"item": "$item:a", "count": 2}, {"item": "minecraft:flint", "count": 1}]}
        holder, out, ledger = render({"id": "f", "items": {"a": {"display": "A", "texture": "t"}}, "recipes": {"r": recipe},
                                      "blocks": {"kiln": {"family": "machine", "display": "K", "texture": "t", "inventory": {"inputs": 2, "outputs": 2}}}})
        with holder:
            machines = read(out, "config", "knowledge.json")["machines"]
            self.assertEqual(machines["f/kiln"][0]["outputs"], [{"item": f"gm:{ledger['items']['f/a']['slot']}", "count": 2}, {"item": "minecraft:flint", "count": 1}])
            self.assertEqual(read(out, "config", "machine_inventories.json")[ledger["blocks"]["f/kiln"]["slot"]], {"inputs": 2, "outputs": 2})

    def test_the_voices_and_the_tuner_can_read_several(self):
        recipe = {**MACHINE_RECIPE, "outputs": [{"item": "$item:a", "count": 2}, {"item": "minecraft:flint", "count": 1}]}
        self.assertIn("$item:a, minecraft:flint", world_index._describe_recipe(recipe))
        manifest = {"id": "f", "recipes": {"r": recipe}}
        with self.assertRaises(tuning.TuneError):
            tuning.apply(manifest, "recipes", "r", "output.count", 3, "players say this gives too little")


class Crops(unittest.TestCase):
    CROP = {"family": "crop", "display": "C", "texture": "t", "stages": ["t0", "t1", "t2", "t3"], "drops": [{"item": "fruit", "count": [1, 2]}, {"item": "seed"}], "young_drops": {"item": "seed"}}
    ITEMS = {"fruit": {"display": "F", "texture": "t"}, "seed": {"display": "S", "texture": "t", "places": {"block": "$block:crop"}}}

    def test_it_needs_all_its_stages(self):
        static.check_block_kinds({"f": feature(blocks={"crop": self.CROP})})
        for stages in (None, [], ["t0"], ["t0", "t1", "t2", "t3", "t3"], "t0"):
            refused(static.check_block_kinds, "4 textures", features={"f": feature(blocks={"crop": {**self.CROP, "stages": stages}})})

    def test_only_a_crop_has_those(self):
        for field, value in (("stages", ["t0"]), ("growth", 0.5), ("young_drops", {"item": "x"})):
            refused(static.check_block_kinds, "only a crop", features={"f": feature(blocks={"b": {"family": "soil", field: value}})})

    def test_growth_is_a_share(self):
        for growth in (0, 1.5, "fast"):
            refused(static.check_block_kinds, "random tick", features={"f": feature(blocks={"crop": {**self.CROP, "growth": growth}})})

    def test_a_crop_has_to_give_something(self):
        refused(static.check_block_kinds, "nobody could ever harvest", features={"f": feature(blocks={"crop": {**self.CROP, "drops": "nothing"}})})

    def test_what_it_gives_depends_on_being_ripe(self):
        table = bundles._crop_loot_table(self.CROP, "s0020", "f", {"blocks": {}, "items": {"f/fruit": {"slot": "i1"}, "f/seed": {"slot": "i2"}}})
        ripe = [pool for pool in table["pools"] if pool["condition"]["type"] == "minecraft:match_block"]
        young = [pool for pool in table["pools"] if pool["condition"]["type"] == "minecraft:inverted"]
        self.assertEqual([pool["entries"][0]["name"] for pool in ripe], ["gm:i1", "gm:i2"])
        self.assertEqual([pool["entries"][0]["name"] for pool in young], ["gm:i2"])
        self.assertEqual(ripe[0]["condition"]["state"], {"age": "3"})

    def test_each_stage_has_its_art_and_it_keeps_farmland(self):
        holder, out, ledger = render({"id": "f", "blocks": {"crop": self.CROP}, "items": self.ITEMS})
        with holder:
            slot = ledger["blocks"]["f/crop"]["slot"]
            for stage in range(4):
                self.assertEqual(read(out, "pack", "assets/gm/models/block", f"{slot}_{stage}.json")["textures"]["cross"], f"gm:block/{slot}_{stage}")
                self.assertTrue(pathlib.Path(out, "pack", "assets/gm/textures/block", f"{slot}_{stage}.png").exists())
                self.assertTrue(static.SAFE_PATH.match(f"assets/gm/models/block/{slot}_{stage}.json"), slot)
            self.assertIn(f"gm:{slot}", read(out, "datapack", "data/minecraft/tags/block/maintains_farmland.json")["values"])

    def test_a_seed_is_a_source_of_what_it_plants(self):
        balance.run({"f": feature(blocks={"crop": self.CROP}, items={"fruit": {}, "seed": {"places": {"block": "$block:crop"}}}, recipes={"s": from_iron("$item:seed")})})

    def test_a_block_only_a_seed_nobody_can_get_plants_cant_be_had(self):
        refused(balance.run, "Nobody can obtain f/crop", features={"f": feature(blocks={"crop": self.CROP}, items={"fruit": {}, "seed": {"places": {"block": "$block:crop"}}})})


class Connected(unittest.TestCase):
    def test_a_shape_has_an_arm_for_each_direction_it_reaches(self):
        self.assertEqual(len(bundles._connected_model("s0030", 0)["elements"]), 1)
        self.assertEqual(len(bundles._connected_model("s0030", 0b111111)["elements"]), 7)
        down = bundles._connected_model("s0030", 1)["elements"][1]
        self.assertEqual((down["from"], down["to"]), ([6, 0, 6], [10, 6, 10]))
        east = bundles._connected_model("s0030", 1 << 5)["elements"][1]
        self.assertEqual((east["from"], east["to"]), ([10, 6, 6], [16, 10, 10]))

    def test_every_shape_gets_a_model_and_its_list_of_neighbours_is_resolved(self):
        holder, out, ledger = render({"id": "f", "blocks": {"cable": {"family": "connected", "display": "C", "texture": "t", "connects": ["minecraft:hopper", "$block:other"]},
                                                            "other": {"family": "soil", "display": "O", "texture": "t"}}})
        with holder:
            slot = ledger["blocks"]["f/cable"]["slot"]
            for shape in (0, 63):
                self.assertTrue(pathlib.Path(out, "pack", "assets/gm/models/block", f"{slot}_c{shape}.json").exists())
                self.assertTrue(static.SAFE_PATH.match(f"assets/gm/models/block/{slot}_c{shape}.json"))
            self.assertEqual(read(out, "config", "block_settings.json")[slot]["connects"], ["minecraft:hopper", f"gm:{ledger['blocks']['f/other']['slot']}"])

    def test_only_it_connects(self):
        refused(static.check_block_kinds, "only a connected", features={"f": feature(blocks={"b": {"family": "soil", "connects": ["minecraft:hopper"]}})})


class BlockOptions(unittest.TestCase):
    def test_hardness(self):
        static.check_block_kinds({"f": feature(blocks={"b": {"family": "stone", "hardness": 0}, "c": {"family": "stone", "hardness": 5}})})
        for hardness in (-1, 5.5, "soft", True):
            refused(static.check_block_kinds, "from 0", features={"f": feature(blocks={"b": {"family": "stone", "hardness": hardness}})})

    def test_it_goes_to_the_server(self):
        holder, out, ledger = render({"id": "f", "blocks": {"b": {"family": "stone", "display": "B", "texture": "t", "hardness": 0}}})
        with holder:
            self.assertEqual(read(out, "config", "block_settings.json")[ledger["blocks"]["f/b"]["slot"]], {"hardness": 0})

    def test_a_block_can_drop_nothing(self):
        self.assertEqual(bundles._loot_table({"drops": "nothing"}, "b", "s0000", "f", {})["pools"], [])
        self.assertEqual(world_index._describe_block({"display": "B", "family": "soil", "drops": "nothing"}), '"B", soil')
        placed = {"f": feature(blocks={"b": {"drops": "nothing"}}, ruins={"r": {"parts": [{"x": 0, "y": 0, "z": 0, "block": "$block:b"}]}})}
        balance.run(placed)
        self.assertEqual(balance.drops_of({"drops": "nothing"}), [])

    def test_what_only_a_module_hands_out_says_so(self):
        balance.run({"f": feature(items={"sample": {"from_module": True}})})
        balance.run({"f": feature(items={"sample": {"from_module": True}, "x": {}}, recipes={"x": shapeless(["$item:sample"], {"id": "$item:x"})})})
        refused(balance.run, "Nobody can obtain f/sample", features={"f": feature(items={"sample": {}})})

    def test_an_emissive_cube_says_so_in_its_own_elements(self):
        holder, out, ledger = render({"id": "f", "blocks": {"b": {"family": "soil", "display": "B", "texture": "t", "emissive": True}}})
        with holder:
            model = read(out, "pack", "assets/gm/models/block", f"{ledger['blocks']['f/b']['slot']}.json")
            self.assertEqual(model["elements"][0]["light_emission"], 15)
            self.assertEqual(model["textures"]["up"], f"gm:block/{ledger['blocks']['f/b']['slot']}")
            # This one has no elements of its own to inherit, only how a block sits in an inventory.
            self.assertEqual(model["parent"], "minecraft:block/block")

    def test_only_a_cube_can_be_emissive(self):
        refused(static.check_block_kinds, "only a plain cube", features={"f": feature(blocks={"b": {"family": "plant", "emissive": True}})})

    def test_a_glowing_ore_is_an_ore(self):
        self.assertIn("glow_ore", bundles.ORE_FAMILIES)


class Ores(unittest.TestCase):
    def ore(self, **fields):
        return {"f": feature(blocks={"o": {"family": "ore"}}, ores=[{"id": "o1", "block": "o", "veinsPerChunk": 3, "veinSize": 7, "minY": -40, "maxY": 48, **fields}])}

    def test_a_range_counts_as_its_average(self):
        balance.run(self.ore(veinSize=[4, 8]))
        recipes = []
        spread = balance.check_ores(self.ore(veinsPerChunk=60, veinSize=[4, 8], minY=-64, maxY=64), recipes)
        fixed = balance.check_ores(self.ore(veinsPerChunk=60, veinSize=6, minY=-64, maxY=64), recipes)
        self.assertEqual(spread, fixed)

    def test_a_range_of_nonsense(self):
        for size in ([4], [4, 8, 9], ["a", "b"]):
            with self.assertRaises(GateFailed):
                balance.run(self.ore(veinSize=size))
        problems = balance.check_ores(self.ore(veinSize=[4.5, 8]), [])
        self.assertIn("whole numbers", problems[0])

    def test_the_server_is_told(self):
        holder, out, _ = render({"id": "f", "blocks": {"o": {"family": "ore", "display": "O", "texture": "t"}},
                                 "ores": [{"id": "o1", "block": "o", "replaces": ["minecraft:stone"], "veinsPerChunk": 3, "veinSize": [4, 8], "minY": 0, "maxY": 40, "touchingAir": True}]})
        with holder:
            patch = read(out, "config", "ore_patches.json")[0]
            self.assertEqual((patch["veinSize"], patch["touchingAir"]), ([4, 8], True))


class Items(unittest.TestCase):
    def test_a_timed_use_is_like_food_to_a_client(self):
        holder, out, ledger = render({"id": "f", "items": {"tool": {"display": "T", "texture": "t", "use": {"seconds": 2, "animation": "brush"}, "tooltip": ["A line"]}}})
        with holder:
            defaults = read(out, "config", "item_defaults.json")[f"gm:{ledger['items']['f/tool']['slot']}"]
            self.assertTrue(defaults["timed_use"])
            self.assertEqual(defaults["components"]["minecraft:consumable"]["consume_seconds"], 2)
            self.assertEqual(defaults["components"]["minecraft:consumable"]["animation"], "brush")
            self.assertEqual(defaults["components"]["minecraft:lore"][0]["fallback"], "A line")

    def test_the_rules_for_a_use(self):
        static.check_items({"f": feature(items={"t": {"use": {"seconds": 1}}})})
        for use in ({}, {"seconds": 0}, {"seconds": 61}, {"seconds": "long"}, {"seconds": True}, 3):
            refused(static.check_items, "seconds", features={"f": feature(items={"t": {"use": use}})})
        refused(static.check_items, "animation", features={"f": feature(items={"t": {"use": {"seconds": 1, "animation": "dance"}}})})
        refused(static.check_items, "or something eaten", features={"f": feature(items={"t": {"use": {"seconds": 1}, "components": {"minecraft:consumable": {}}}})})

    def test_a_tooltip_is_lines(self):
        for tooltip in ("A line", [1], {"line": "A"}):
            refused(static.check_items, "lines of text", features={"f": feature(items={"t": {"tooltip": tooltip}})})

    def test_variants_and_a_compass_get_a_definition_of_their_own(self):
        holder, out, ledger = render({"id": "f", "items": {"art": {"display": "A", "texture": "t", "variants": {"gilded": "other"}}, "needle": {"display": "N", "texture": "t", "compass": ["t0", "t1", "t2", "t3"]},
                                                           "plain": {"display": "P", "texture": "t"}}})
        with holder:
            art, needle, plain = (ledger["items"][f"f/{name}"]["slot"] for name in ("art", "needle", "plain"))
            model = read(out, "pack", "assets/gm/items", f"{art}.json")["model"]
            self.assertEqual((model["type"], model["property"], model["cases"][0]["when"]), ("minecraft:select", "minecraft:custom_model_data", "gilded"))
            self.assertEqual(model["fallback"]["model"], f"gm:item/{art}")
            self.assertTrue(pathlib.Path(out, "pack", "assets/gm/textures/item", f"{art}_v0.png").exists())
            model = read(out, "pack", "assets/gm/items", f"{needle}.json")["model"]
            self.assertEqual((model["type"], model["property"], model["target"], model["scale"], len(model["entries"])), ("minecraft:range_dispatch", "minecraft:compass", "lodestone", 4, 4))
            self.assertFalse(pathlib.Path(out, "pack", "assets/gm/items", f"{plain}.json").exists())
            for path in (f"assets/gm/items/{art}.json", f"assets/gm/models/item/{needle}_c3.json", f"assets/gm/textures/item/{art}_v0.png"):
                self.assertTrue(static.SAFE_PATH.match(path), path)

    def test_the_rules_for_pictures(self):
        for frames in (["a"], ["a"] * 65, "a", [1, 2]):
            refused(static.check_items, "clockwise", features={"f": feature(items={"t": {"compass": frames}})})
        for variants in ({}, ["a"], {"a": 1}):
            refused(static.check_items, "texture for each", features={"f": feature(items={"t": {"variants": variants}})})


class ScreenEffects(unittest.TestCase):
    GOOD = "#version 330\nvoid main() { }\n"

    def effect(self, source):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        shaders = pathlib.Path(folder.name, "assets", "shaders")
        shaders.mkdir(parents=True)
        (shaders / "warp.fsh").write_text(source, encoding="utf-8")
        return {"f": {"manifest": {"screen_effects": ["warp"]}, "dir": pathlib.Path(folder.name)}}

    def test_a_plain_one_is_fine(self):
        static.check_screen_effects(self.effect(self.GOOD))
        static.check_screen_effects(self.effect("#version 330\nvoid main() { for (int i = 0; i < 4; i++) { } }\n"))

    def test_it_has_to_exist(self):
        refused(static.check_screen_effects, "needs assets/shaders", features={"f": {"manifest": {"screen_effects": ["warp"]}, "dir": pathlib.Path("does-not-exist")}})

    def test_the_version_the_game_uses(self):
        refused(static.check_screen_effects, "#version 330", features=self.effect("void main() { }\n"))

    def test_nothing_that_could_never_finish(self):
        for loop in ("while (true) { }", "do { } while (false);"):
            refused(static.check_screen_effects, "hang", features=self.effect(f"#version 330\nvoid main() {{ {loop} }}\n"))

    def test_nothing_enormous(self):
        refused(static.check_screen_effects, "keep it simple", features=self.effect("#version 330\n" + "// " * 8000))

    def test_the_game_is_told_how_to_run_it_under_a_name_that_gives_nothing_away(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = pathlib.Path(folder.name)
        (root / "feature" / "assets" / "shaders").mkdir(parents=True)
        (root / "feature" / "assets" / "shaders" / "warp.fsh").write_text(self.GOOD, encoding="utf-8")
        bundles._copy_screen_effects({"manifest": {"screen_effects": ["warp"]}, "dir": root / "feature"}, "f", root / "pack")
        hashed = bundles._effect_id("f", "warp")
        self.assertTrue((root / "pack/assets/gm/shaders/post" / f"{hashed}.fsh").exists())
        effect = read(root, "pack/assets/gm/post_effect", f"{hashed}.json")
        self.assertEqual(effect["passes"][0]["fragment_shader"], f"gm:post/{hashed}")
        self.assertEqual(effect["passes"][1]["output"], "minecraft:main")
        self.assertTrue(static.SAFE_PATH.match(f"assets/gm/shaders/post/{hashed}.fsh"))
        self.assertTrue(static.SAFE_PATH.match(f"assets/gm/post_effect/{hashed}.json"))

    def test_the_name_is_worked_out_as_the_companion_does(self):
        # The same text and the same sum as ModuleHost.effectId, so a change on one side has to be made on the other.
        self.assertEqual(bundles._effect_id("hooks", "hook_warp"), "p" + hashlib.sha256(b"hooks/hook_warp").hexdigest()[:16])


class AReleaseThatStopsTheServerStarting(unittest.TestCase):
    def test_it_is_refused_with_what_the_server_said(self):
        said = "[10:45:02] [main/ERROR]: Errors in registry minecraft:loot_table:\n>> Errors in element gm:blocks/s2200:\n"
        with (mock.patch.object(shadow, "_running", return_value=False), mock.patch.object(shadow, "cold_boot"),
              mock.patch.object(shadow.runtime, "apply_content"), mock.patch.object(shadow.runtime, "stack") as stack,
              mock.patch.object(shadow, "start", side_effect=TimeoutError("shadow didn't answer within 240s")),
              mock.patch.object(shadow.runtime, "logs_since", return_value=said)):
            with self.assertRaises(GateFailed) as caught:
                shadow.run_gate("T3", [], pathlib.Path("."), [])
        self.assertIn("wouldn't start", caught.exception.message)
        self.assertIn("Errors in registry", caught.exception.message)
        stack.assert_called_with("stop", "shadow", check=False)


class Reskins(unittest.TestCase):
    MOB = {"category": "creature", "display": "M", "model": "m", "behaviour": "passive", "health": 8, "damage": 0, "speed": 0.2, "width": 1, "height": 1}

    def test_a_feature_can_give_a_mob_a_new_look(self):
        holder, out, ledger = render({"id": "f", "mobs": {"m": self.MOB}, "reskins": {"f/m": "new_look"}})
        with holder:
            model = read(out, "config", "mobs.json")[f"gm:{ledger['mobs']['f/m']['slot']}"]["model"]
            self.assertTrue(pathlib.Path(out, "config", "models", f"{model}.bbmodel").exists())

    def test_it_has_to_be_a_real_mob(self):
        with self.assertRaises(bundles.BundleError) as caught:
            render({"id": "f", "reskins": {"f/nobody": "new_look"}})
        self.assertIn("no feature declares", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
