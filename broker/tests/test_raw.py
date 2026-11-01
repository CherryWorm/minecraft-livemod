"""What the bundler and the instant checks make of the vanilla files a feature ships in raw/: names that give nothing away, what can't
be shipped at all, what needs a restart, and no way round the balance rules. No servers needed.

Usage: python3 -m unittest broker.tests.test_raw
"""
import copy
import json
import pathlib
import tempfile
import unittest
import unittest.mock

from PIL import Image

from broker import bundles, rawpack
from broker.gates import GateFailed, balance, progression, raw, static

POOL = {"families": {"stone": {"first": 0, "count": 4}, "plant": {"first": 10, "count": 2}, "ladder": {"first": 20, "count": 2}}, "item_count": 8, "mobs": {"monster": 1, "creature": 2}}
ENCHANTMENT = {"description": {"text": "Ember Edge"}, "supported_items": "#minecraft:enchantable/sharp_weapon", "weight": 5, "max_level": 3, "min_cost": {"base": 1, "per_level_above_first": 11},
               "max_cost": {"base": 21, "per_level_above_first": 11}, "anvil_cost": 2, "slots": ["mainhand"]}
SONG = {"sound_event": {"sound_id": "$sound:hum"}, "description": {"text": "Hum"}, "length_in_seconds": 30, "comparator_output": 7}
ADVANCEMENT = {"criteria": {"got": {"trigger": "minecraft:inventory_changed", "conditions": {"items": [{"items": "$item:token"}]}}},
               "display": {"icon": {"id": "$item:token"}, "title": {"text": "Got one"}, "description": {"text": "Well done"}}}
ADD_DAMAGE = {"minecraft:damage": [{"effect": {"type": "minecraft:add", "value": {"type": "minecraft:linear", "base": 1.0, "per_level_above_first": 0.5}}}]}


def base_manifest(**extra):
    return {"id": "f", "node": "start", "items": {"token": {"display": "Token", "texture": "t"}}, "recipes": {
        "token": {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["minecraft:paper"], "result": {"id": "$item:token"}}}}, **extra}


class World:
    """Features on disk with their raw files, and what the real bundler makes of them."""

    def __init__(self, test, files=None, **manifest):
        self.folder = tempfile.TemporaryDirectory()
        test.addCleanup(self.folder.cleanup)
        self.root = pathlib.Path(self.folder.name)
        self.features = {}
        self.add("f", files or {}, base_manifest(**manifest))

    def add(self, feature_id, files, manifest):
        source = self.root / feature_id
        (source / "assets" / "textures").mkdir(parents=True)
        (source / "assets" / "sounds").mkdir(parents=True)
        Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(source / "assets" / "textures" / "t.png")
        (source / "assets" / "sounds" / "hum.ogg").write_bytes(b"not really")
        for relative, contents in files.items():
            path = source / "raw" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(contents, tuple):
                Image.new("RGBA", contents, (9, 9, 9, 255)).save(path)
            elif isinstance(contents, str):
                path.write_text(contents, encoding="utf-8")
            else:
                path.write_text(json.dumps(contents), encoding="utf-8")
        self.features[feature_id] = {"manifest": {**base_manifest(), "id": feature_id, **manifest}, "dir": source}

    def render(self, ledger=None):
        ledger = bundles.assign_slots(self.features, ledger or bundles.empty_ledger(), POOL)
        out = self.root / "out"
        bundles.render(self.features, ledger, out, 1, vanilla_biome=lambda name: {"effects": {}}, vanilla_file=self.vanilla)
        self.ledger = ledger
        self.out = out
        return out

    @staticmethod
    def vanilla(path):
        if path != "data/minecraft/loot_table/chests/simple_dungeon.json":
            raise KeyError(path)
        return {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "minecraft:apple"}]}], "random_sequence": "minecraft:chests/simple_dungeon"}

    def check(self, old_ledger=None):
        raw.run(self.features, old_ledger)

    def read(self, *path):
        return json.loads(self.out.joinpath(*path).read_text(encoding="utf-8"))


def hashed(name, feature_id="f"):
    return rawpack.raw_id(feature_id, name)


class Names(unittest.TestCase):
    def test_a_file_goes_out_under_a_name_that_gives_nothing_away(self):
        world = World(self, {"data/gm/enchantment/ember_edge.json": ENCHANTMENT, "assets/gm/equipment/ember_plate.json": {"layers": {"humanoid": [{"texture": "$texture:ember_plate"}]}},
                             "assets/gm/textures/entity/equipment/humanoid/ember_plate.png": (64, 32)})
        out = world.render()
        everything = [path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()]
        self.assertFalse([path for path in everything if "ember" in path], everything)
        self.assertIn(f"datapack/data/gm/enchantment/{hashed('ember_edge')}.json", everything)
        self.assertIn(f"pack/assets/gm/equipment/{hashed('ember_plate')}.json", everything)
        self.assertIn(f"pack/assets/gm/textures/entity/equipment/humanoid/{hashed('ember_plate')}.png", everything)
        static.check_spoilers(out / "pack")
        static.check_textures(out / "pack")

    def test_tokens_resolve_inside_raw_files_including_keys(self):
        world = World(self, {"data/gm/advancement/got.json": {**ADVANCEMENT, "parent": "$advancement:root"}, "data/gm/advancement/root.json": ADVANCEMENT,
                             "data/gm/enchantment/edge.json": ENCHANTMENT, "data/gm/loot_table/chest.json": {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [
                                 {"type": "minecraft:item", "name": "$item:token", "modifier": [{"type": "minecraft:set_enchantments", "enchantments": {"$enchantment:edge": 1}}]}]}]}})
        out = world.render()
        slot = world.ledger["items"]["f/token"]["slot"]
        advancement = world.read("datapack", f"data/gm/advancement/{hashed('got')}.json")
        self.assertEqual(advancement["display"]["icon"]["id"], f"gm:{slot}")
        self.assertEqual(advancement["parent"], f"gm:{hashed('root')}")
        table = world.read("datapack", f"data/gm/loot_table/{hashed('chest')}.json")
        self.assertEqual(list(table["pools"][0]["entries"][0]["modifier"][0]["enchantments"]), [f"gm:{hashed('edge')}"])
        self.assertTrue(out.exists())
        world.check()

    def test_a_token_in_feature_json_resolves_too(self):
        world = World(self, {"data/gm/jukebox_song/hum.json": SONG}, sounds=["hum"],
                      items={"token": {"display": "Token", "texture": "t"}, "disc": {"display": "Disc", "texture": "t", "components": {"minecraft:jukebox_playable": "$jukebox_song:hum", "minecraft:max_stack_size": 1}}})
        world.render()
        slot = world.ledger["items"]["f/disc"]["slot"]
        self.assertEqual(world.read("config", "item_defaults.json")[f"gm:{slot}"]["components"]["minecraft:jukebox_playable"], f"gm:{hashed('hum')}")
        world.check()

    def test_another_features_file(self):
        world = World(self, {"data/gm/enchantment/edge.json": ENCHANTMENT})
        world.add("g", {"data/minecraft/tags/enchantment/in_enchanting_table.json": {"values": ["$enchantment:f/edge"]}}, {})
        world.render()
        self.assertEqual(world.read("datapack", "data/minecraft/tags/enchantment/in_enchanting_table.json")["values"], [f"gm:{hashed('edge')}"])
        world.check()

    def test_something_that_isnt_there(self):
        world = World(self, {"data/minecraft/tags/enchantment/in_enchanting_table.json": {"values": ["$enchantment:nothing"]}})
        with self.assertRaisesRegex(GateFailed, r"\$enchantment:nothing.*no feature has that"):
            world.check()

    def test_the_wrong_kind_of_token(self):
        world = World(self, {"assets/gm/equipment/plate.json": {"layers": {"humanoid": [{"texture": "$texture:plate"}]}}, "assets/gm/textures/entity/equipment/humanoid/plate.png": (64, 32)},
                      items={"token": {"display": "Token", "texture": "t", "components": {"minecraft:equippable": {"slot": "chest", "asset_id": "$enchantment:plate"}}}})
        with self.assertRaisesRegex(GateFailed, r"\$enchantment:plate"):
            world.check()

    def test_writing_an_id_yourself(self):
        world = World(self, {"data/gm/advancement/got.json": {**ADVANCEMENT, "parent": "gm:q123"}})
        with self.assertRaisesRegex(GateFailed, "Don't write a gm: id yourself"):
            world.check()


class WhatCantShip(unittest.TestCase):
    def refused(self, relative, mention, contents="{}"):
        world = World(self, {relative: contents})
        with self.assertRaisesRegex(bundles.BundleError, mention):
            world.render()

    def test_refused_paths(self):
        for relative, mention in (("data/gm/function/x.mcfunction", "any command"), ("data/gm/recipe/x.json", "feature.json"), ("data/minecraft/recipe/x.json", "feature.json"),
                                  ("data/minecraft/loot_table/chests/simple_dungeon.json", "loot_additions"), ("data/minecraft/advancement/story/root.json", "vanilla stays vanilla"),
                                  ("data/gm/dialog/x.json", "web page"), ("data/gm/villager_trade/x.json", "trade"), ("data/gm/dimension/x.json", "Dimensions"),
                                  ("data/gm/worldgen/feature/x.json", "any ore"), ("data/gm/worldgen/biome/x.json", "any ore"),
                                  ("data/other/enchantment/x.json", "namespace"), ("data/gm/enchantment/deep/x.json", "folder of its own"),
                                  ("assets/minecraft/textures/block/stone.png", "vanilla's own look"), ("assets/gm/shaders/post/x.fsh", "Shaders"), ("assets/gm/lang/en_us.json", "language"),
                                  ("assets/gm/font/x.json", "fonts"), ("data/gm/enchantment/x.txt", ".json"), ("readme.txt", "goes under")):
            self.refused(relative, mention)

    def test_a_link_isnt_followed(self):
        world = World(self)
        path = world.features["f"]["dir"] / "raw" / "assets" / "gm" / "textures" / "painting"
        path.mkdir(parents=True)
        try:
            (path / "x.png").symlink_to(pathlib.Path(__file__))
        except OSError:
            self.skipTest("this system can't make links")
        with self.assertRaisesRegex(bundles.BundleError, "is a link"):
            world.render()

    def test_bad_json(self):
        with self.assertRaisesRegex(bundles.BundleError, "isn't valid JSON"):
            World(self, {"data/gm/advancement/x.json": "{oops"}).render()

    def test_what_gets_around_everything_however_its_arranged(self):
        for name, contents, mention in (
                ("enchantment/x", {**ENCHANTMENT, "effects": {"minecraft:post_attack": [{"effect": {"type": "minecraft:run_command", "command": "op me"}, "enchanted": "attacker", "affected": "attacker"}]}}, "run_command"),
                ("advancement/x", {**ADVANCEMENT, "rewards": {"function": "minecraft:give_everything"}}, "function"),
                ("advancement/y", {**ADVANCEMENT, "display": {**ADVANCEMENT["display"], "title": {"text": "Go", "click_event": {"action": "open_url", "url": "http://x"}}}}, "click_event")):
            world = World(self, {f"data/gm/{name}.json": contents})
            with self.assertRaisesRegex(GateFailed, mention):
                world.check()

    def test_a_field_the_game_would_ignore(self):
        world = World(self, {"data/gm/jukebox_song/hum.json": {**SONG, "lenght_in_seconds": 3}}, sounds=["hum"])
        with self.assertRaisesRegex(GateFailed, "lenght_in_seconds, which none of vanilla's has"):
            world.check()

    def test_a_missing_field_would_stop_the_server_starting(self):
        world = World(self, {"data/gm/enchantment/x.json": {key: value for key, value in ENCHANTMENT.items() if key != "weight"}})
        with self.assertRaisesRegex(GateFailed, "missing weight"):
            world.check()


    def test_the_wrong_kind_of_value_would_too(self):
        world = World(self, {"data/gm/enchantment/x.json": {**ENCHANTMENT, "anvil_cost": "a lot"}})
        with self.assertRaisesRegex(GateFailed, "anvil_cost .*a number"):
            world.check()

    def test_text_can_be_plain(self):
        World(self, {"data/gm/enchantment/x.json": {**ENCHANTMENT, "description": "Plain words", "weight": 5.0}}).check()


class Tiers(unittest.TestCase):
    def test_what_needs_a_restart(self):
        for relative in ("data/gm/enchantment/q.json", "data/gm/jukebox_song/q.json", "data/gm/painting_variant/q.json", "data/gm/worldgen/biome/b.json", "data/gm/damage_type/q.json",
                         "data/minecraft/tags/worldgen/biome/is_forest.json", "data/gm/something_new/q.json"):
            self.assertTrue(rawpack.needs_restart(relative), relative)
        for relative in ("data/gm/advancement/q.json", "data/gm/loot_table/blocks/s1000.json", "data/gm/recipe/r.json", "data/minecraft/loot_table/chests/x.json", "data/gm/predicate/q.json", "data/gm/item_modifier/q.json",
                         "data/minecraft/tags/block/climbable.json", "data/minecraft/tags/enchantment/in_enchanting_table.json", "pack.mcmeta"):
            self.assertFalse(rawpack.needs_restart(relative), relative)

    def test_a_change_to_a_tag_doesnt_look_like_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            data = pathlib.Path(folder)
            (data / "data/gm/enchantment").mkdir(parents=True)
            (data / "data/minecraft/tags/block").mkdir(parents=True)
            (data / "data/gm/enchantment/q.json").write_text("{}", encoding="utf-8")
            (data / "data/minecraft/tags/block/x.json").write_text("{}", encoding="utf-8")
            before = rawpack.startup_files(data)
            (data / "data/minecraft/tags/block/x.json").write_text('{"values": []}', encoding="utf-8")
            self.assertEqual(rawpack.startup_files(data), before)
            (data / "data/gm/enchantment/q.json").write_text('{"weight": 1}', encoding="utf-8")
            self.assertNotEqual(rawpack.startup_files(data), before)

    def test_every_raw_folder_is_on_the_right_side(self):
        for registry in rawpack.RELOADED_RAW:
            self.assertFalse(rawpack.needs_restart(f"data/gm/{registry}/q.json"), registry)
        for registry in rawpack.STARTUP_RAW:
            self.assertTrue(rawpack.needs_restart(f"data/gm/{registry}/q.json"), registry)

    def test_whats_read_at_startup_stays_for_good(self):
        world = World(self, {"data/gm/enchantment/edge.json": ENCHANTMENT})
        world.render()
        self.assertEqual(world.ledger["raw"], ["enchantment/f/edge"])
        (world.features["f"]["dir"] / "raw/data/gm/enchantment/edge.json").unlink()
        with self.assertRaisesRegex(GateFailed, "enchantment/f/edge has been released"):
            world.check(world.ledger)

    def test_a_tag_or_advancement_can_go(self):
        world = World(self, {"data/gm/advancement/got.json": ADVANCEMENT})
        world.render()
        self.assertEqual(world.ledger["raw"], [])


class Enchantments(unittest.TestCase):
    def power(self, tier=None, **fields):
        problems = []
        raw._check_enchantment_power({**ENCHANTMENT, **fields}, tier, "It", problems)
        return problems

    def test_as_strong_as_vanillas_best(self):
        self.assertEqual(self.power(max_level=5, effects=ADD_DAMAGE), [])

    def test_stronger_than_vanillas_best(self):
        problems = self.power(max_level=5, effects={"minecraft:damage": [{"effect": {"type": "minecraft:add", "value": 100}}]})
        self.assertIn("over vanilla's best", problems[0])

    def test_a_condition_allows_what_smite_does(self):
        conditional = {"minecraft:damage": [{"effect": {"type": "minecraft:add", "value": 12}, "requirements": {"type": "minecraft:entity_properties"}}]}
        self.assertEqual(self.power(effects=conditional), [])

    def test_a_multiplier_cant_hide_as_a_small_number(self):
        self.assertTrue(self.power(effects={"minecraft:damage": [{"effect": {"type": "minecraft:multiply", "factor": 3}}]}))

    def test_too_many_levels(self):
        self.assertIn("max_level", self.power(max_level=255)[0])

    def test_never_wearing_out(self):
        self.assertEqual(self.power(effects={"minecraft:item_damage": [{"effect": {"type": "minecraft:remove_binomial", "chance": 0.5}}]}), [])
        self.assertTrue(self.power(effects={"minecraft:item_damage": [{"effect": {"type": "minecraft:remove_binomial", "chance": 1.0}}]}))
        self.assertTrue(self.power(effects={"minecraft:item_damage": [{"effect": {"type": "minecraft:set", "value": 0}}]}))

    def test_attributes(self):
        self.assertEqual(self.power(effects={"minecraft:attributes": [{"attribute": "minecraft:mining_efficiency", "amount": 5, "operation": "add_value", "id": "gm:x"}]}), [])
        self.assertIn("max_health", self.power(effects={"minecraft:attributes": [{"attribute": "minecraft:max_health", "amount": 5, "operation": "add_value", "id": "gm:x"}]})[0])

    def test_what_cant_be_measured(self):
        for effects in ({"minecraft:tick": [{"effect": {"type": "minecraft:apply_mob_effect"}}]}, {"minecraft:post_attack": [{"effect": {"type": "minecraft:summon_entity", "entity": "minecraft:wither"}, "enchanted": "attacker", "affected": "victim"}]},
                        {"minecraft:post_attack": [{"effect": {"type": "minecraft:explode", "radius": 50}, "enchanted": "attacker", "affected": "victim"}]}):
            self.assertIn("nothing to measure", self.power(effects=effects)[0])

    def test_beyond_allows_half_as_much_again(self):
        strong = {"minecraft:damage": [{"effect": {"type": "minecraft:add", "value": 4.5}}]}
        self.assertTrue(self.power(effects=strong))
        self.assertEqual(self.power("beyond", effects=strong), [])

    def test_mythic_has_no_limits(self):
        self.assertEqual(self.power("mythic", max_level=255, effects={"minecraft:tick": [{"effect": {"type": "minecraft:summon_entity"}}]}), [])

    def test_the_tier_comes_from_feature_json_and_has_to_fit_the_stage(self):
        strong = {**ENCHANTMENT, "effects": {"minecraft:damage": [{"effect": {"type": "minecraft:add", "value": 4.5}}]}}
        world = World(self, {"data/gm/enchantment/edge.json": strong}, enchantments={"edge": {"tier": "beyond"}})
        world.check()
        doc = {"nodes": {"start": {"stage": "early", "requires": []}}}
        problems = progression._check_tiers(world.features, doc, [])
        self.assertIn("Enchantment f/edge is tier beyond", problems[0])

    def test_a_tier_for_something_that_isnt_there(self):
        world = World(self, enchantments={"nothing": {"tier": "beyond"}})
        with self.assertRaisesRegex(GateFailed, "no raw/data/gm/enchantment/nothing.json"):
            world.check()

    def test_on_a_recipes_result_it_still_isnt_allowed(self):
        problems = balance.check_power({}, [{"source": "f/x", "tier": "iron", "inputs": [], "outputs": [("minecraft:iron_sword", 1, {"minecraft:enchantments": {"gm:q": 1}})]}])
        self.assertIn("sets enchantments", problems[0])


class LootAdditions(unittest.TestCase):
    PILE = [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "$item:token"}]}]

    def test_added_to_vanilla_not_instead_of_it(self):
        world = World(self, loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": self.PILE}])
        world.add("g", {}, {"loot_additions": [{"table": "minecraft:chests/simple_dungeon", "pools": [{"rolls": 2, "entries": [{"type": "minecraft:item", "name": "minecraft:stick"}]}]}]})
        world.render()
        table = world.read("datapack", "data/minecraft/loot_table/chests/simple_dungeon.json")
        names = [pool["entries"][0]["name"] for pool in table["pools"]]
        self.assertEqual(names[0], "minecraft:apple")
        self.assertIn(f"gm:{world.ledger['items']['f/token']['slot']}", names)
        self.assertIn("minecraft:stick", names)
        self.assertEqual(table["random_sequence"], "minecraft:chests/simple_dungeon")
        world.check()

    def test_a_table_that_isnt_there(self):
        world = World(self, loot_additions=[{"table": "minecraft:chests/nowhere", "pools": self.PILE}])
        with self.assertRaisesRegex(bundles.BundleError, "no loot table called"):
            world.render()
        with self.assertRaisesRegex(GateFailed, "no loot table called"):
            world.check()

    def test_its_own_table_isnt_an_addition(self):
        with self.assertRaisesRegex(bundles.BundleError, "vanilla's tables"):
            World(self, loot_additions=[{"table": "chests/x", "pools": self.PILE}]).render()

    def addition(self, *entries):
        return World(self, loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": [{"rolls": 1, "entries": list(entries)}]}])

    def test_gear_past_the_early_game_cant_go_in_vanillas_loot(self):
        world = World(self, items={"token": {"display": "Token", "texture": "t", "tier": "diamond"}}, loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": self.PILE}])
        with self.assertRaisesRegex(GateFailed, "tier diamond.*from the start"):
            world.check()

    def test_it_cant_set_more_power_than_its_tier(self):
        sword = {"type": "minecraft:item", "name": "minecraft:iron_sword", "tier": "iron", "modifier": [{"type": "minecraft:set_components", "components": {"minecraft:max_damage": 99999}}]}
        with self.assertRaisesRegex(GateFailed, "durability"):
            self.addition(sword).check()

    def test_it_has_to_say_what_tier_vanilla_gear_is(self):
        sword = {"type": "minecraft:item", "name": "minecraft:iron_sword", "modifier": [{"type": "minecraft:set_components", "components": {"minecraft:max_damage": 100}}]}
        with self.assertRaisesRegex(GateFailed, "what tier"):
            self.addition(sword).check()

    def test_unmeasured_components_stay_out(self):
        sword = {"type": "minecraft:item", "name": "minecraft:iron_sword", "tier": "iron", "modifier": [{"type": "minecraft:set_components", "components": {"minecraft:enchantments": {"minecraft:sharpness": 100}}}]}
        with self.assertRaisesRegex(GateFailed, "sets enchantments"):
            self.addition(sword).check()

    def test_enchantments_up_to_their_highest_level(self):
        good = {"type": "minecraft:item", "name": "minecraft:book", "modifier": [{"type": "minecraft:set_enchantments", "enchantments": {"minecraft:sharpness": 5}}]}
        self.addition(good).check()
        bad = {"type": "minecraft:item", "name": "minecraft:book", "modifier": [{"type": "minecraft:set_enchantments", "enchantments": {"minecraft:sharpness": 6}}]}
        with self.assertRaisesRegex(GateFailed, "over its highest"):
            self.addition(bad).check()

    def test_a_custom_enchantment_has_its_own_highest_level(self):
        entry = {"type": "minecraft:item", "name": "minecraft:book", "modifier": [{"type": "minecraft:set_enchantments", "enchantments": {"$enchantment:edge": 4}}]}
        world = World(self, {"data/gm/enchantment/edge.json": ENCHANTMENT}, loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": [{"rolls": 1, "entries": [entry]}]}])
        with self.assertRaisesRegex(GateFailed, "over its highest of 3"):
            world.check()

    def test_something_carrying_anything_at_all_stays_out(self):
        for component in ("minecraft:container", "minecraft:bundle_contents", "minecraft:block_entity_data"):
            box = {"type": "minecraft:item", "name": "minecraft:shulker_box", "modifier": [{"type": "minecraft:set_components", "components": {component: []}}]}
            with self.assertRaisesRegex(GateFailed, "could be anything"):
                self.addition(box).check()

    def test_what_set_contents_puts_inside_is_checked(self):
        box = {"type": "minecraft:item", "name": "minecraft:shulker_box", "modifier": [{"type": "minecraft:set_contents", "component": "minecraft:container", "entries": [{"type": "minecraft:item", "name": "minecraft:emberstone"}]}]}
        with self.assertRaisesRegex(GateFailed, "minecraft:emberstone"):
            self.addition(box).check()

    def test_what_never_runs_out_cant_hand_out_what_should_be_rare(self):
        pools = [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "minecraft:diamond"}]}]
        world = World(self, loot_additions=[{"table": "minecraft:entities/zombie", "pools": pools}])
        with self.assertRaisesRegex(GateFailed, "soon be common"):
            world.check()
        World(self, loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": pools}]).check()

    def test_old_fields_quietly_do_nothing(self):
        entry = {"type": "minecraft:item", "name": "minecraft:book", "functions": [{"function": "minecraft:set_count", "count": 3}]}
        with self.assertRaisesRegex(GateFailed, "functions"):
            self.addition(entry).check()

    def test_something_vanilla_doesnt_have(self):
        with self.assertRaisesRegex(GateFailed, "hands out"):
            self.addition({"type": "minecraft:item", "name": "minecraft:emberstone"}).check()
        with self.assertRaisesRegex(GateFailed, "the game doesn't have"):
            self.addition({"type": "minecraft:everything", "name": "minecraft:book"}).check()
        with self.assertRaisesRegex(GateFailed, "set_item"):
            self.addition({"type": "minecraft:item", "name": "minecraft:stick", "modifier": [{"type": "minecraft:set_item", "item": "minecraft:netherite_sword"}]}).check()

    def test_it_counts_as_a_source(self):
        world = World(self, items={"gem": {"display": "Gem", "texture": "t"}}, recipes={}, loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "$item:gem"}]}]}])
        self.assertEqual(balance._check_obtainable(world.features, []), [])

    def test_a_table_only_counts_if_something_uses_it(self):
        table = {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "$item:gem"}]}]}
        unused = World(self, {"data/gm/loot_table/x.json": table}, items={"gem": {"display": "Gem", "texture": "t"}}, recipes={})
        self.assertTrue(balance._check_obtainable(unused.features, []))
        used = World(self, {"data/gm/loot_table/x.json": table, "data/gm/advancement/y.json": {**ADVANCEMENT, "rewards": {"loot": ["$loot_table:x"]}}}, items={"gem": {"display": "Gem", "texture": "t"}}, recipes={})
        self.assertEqual(balance._check_obtainable(used.features, []), [])

    def test_it_follows_the_progression(self):
        world = World(self, loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "$item:g/later"}]}]}])
        world.add("g", {}, {"node": "later", "items": {"later": {"display": "Later", "texture": "t"}}, "recipes": {}})
        doc = {"nodes": {"start": {"stage": "early", "requires": []}, "later": {"stage": "mid", "requires": ["start"]}}}
        self.assertIn("doesn't come before", progression._check_loot_additions(world.features, doc)[0])


class Tags(unittest.TestCase):
    def test_several_features_add_to_one_tag_and_nothing_is_replaced(self):
        world = World(self, {"data/minecraft/tags/item/piglin_loved.json": {"values": ["$item:token"]}}, blocks={"ore": {"family": "stone", "display": "Ore", "texture": "t", "tool": "pickaxe"}})
        world.add("g", {"data/minecraft/tags/item/piglin_loved.json": {"values": ["$item:token", "minecraft:stick"]},
                        "data/minecraft/tags/block/mineable/pickaxe.json": {"values": ["$block:f/ore"]}}, {})
        world.render()
        tag = world.read("datapack", "data/minecraft/tags/item/piglin_loved.json")
        self.assertFalse(tag["replace"])
        self.assertEqual(len(tag["values"]), 3)
        block = f"gm:{world.ledger['blocks']['f/ore']['slot']}"
        self.assertEqual(world.read("datapack", "data/minecraft/tags/block/mineable/pickaxe.json")["values"], [block])
        world.check()

    def test_a_nested_tag_keeps_its_path(self):
        world = World(self, {"data/minecraft/tags/item/enchantable/sharp_weapon.json": {"values": ["$item:token"]}})
        world.render()
        self.assertTrue((world.out / "datapack/data/minecraft/tags/item/enchantable/sharp_weapon.json").exists())
        world.check()

    def refused(self, mention, relative="data/minecraft/tags/item/piglin_loved.json", **contents):
        world = World(self, {relative: {"values": ["$item:token"], **contents}}, blocks={"post": {"family": "stone", "display": "Post", "texture": "t"}, "rung": {"family": "ladder", "display": "Rung", "texture": "t"}})
        with self.assertRaisesRegex(GateFailed, mention):
            world.check()

    def test_it_cant_take_away_whats_there(self):
        self.refused("replace true", replace=True)

    def test_what_vanilla_gear_costs_cant_be_widened(self):
        self.refused("what something in vanilla costs", "data/minecraft/tags/item/diamond_tool_materials.json")
        self.refused("what something in vanilla costs", "data/minecraft/tags/item/repairs_netherite_armor.json")
        self.refused("what something in vanilla costs", "data/minecraft/tags/block/beacon_base_blocks.json", values=["$block:post"])

    def test_a_tag_vanilla_hasnt_got(self):
        self.refused("no item tag called", "data/minecraft/tags/item/in_enchantment_table.json")

    def test_a_name_vanilla_hasnt_got(self):
        self.refused("minecraft:emberstone", values=["minecraft:emberstone"])
        self.refused("#minecraft:nothing", values=["#minecraft:nothing"])

    def test_the_wrong_kind_of_thing(self):
        self.refused("right kind", "data/minecraft/tags/block/mineable/pickaxe.json", values=["$item:token"])

    def test_a_registry_that_cant_be_added_to(self):
        self.refused("can't be added to", "data/minecraft/tags/villager_trade/armorer/level_1.json")

    def test_climbing_only_works_on_a_ladder_block(self):
        self.refused("isn't in the ladder family", "data/minecraft/tags/block/climbable.json", values=["$block:post"])
        world = World(self, {"data/minecraft/tags/block/climbable.json": {"values": ["minecraft:ladder"]}})
        world.check()

    def test_a_ladder_climbs_with_no_tag_at_all(self):
        world = World(self, blocks={"rung": {"family": "ladder", "display": "Rung", "texture": "t"}})
        world.render()
        slot = world.ledger["blocks"]["f/rung"]["slot"]
        self.assertEqual(world.read("datapack", "data/minecraft/tags/block/climbable.json")["values"], [f"gm:{slot}"])
        self.assertEqual(world.read("pack", f"assets/gm/models/block/{slot}.json")["parent"], "minecraft:block/ladder")
        self.assertTrue((world.out / f"pack/assets/gm/items/{slot}.json").exists())

    def test_what_a_tag_adds_to_a_recipe_counts_as_an_input(self):
        """A loop through a tag is still a loop. A gem that's in a vanilla tag can be made from what it's made into."""
        world = World(self, {"data/minecraft/tags/item/piglin_loved.json": {"values": ["$item:token"]}})
        recipes = {"token": {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["minecraft:paper"], "result": {"id": "$item:token"}}},
                   "two": {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["#minecraft:piglin_loved"], "result": {"id": "$item:token", "count": 2}}}}
        world.features["f"]["manifest"]["recipes"] = recipes
        self.assertIn("from nothing", " ".join(balance._check_cycles(world.features, balance._read_recipes(world.features))))

    def test_a_recipe_can_take_a_tag_of_this_worlds(self):
        world = World(self, {"data/gm/tags/item/gems.json": {"values": ["$item:token"]}})
        world.features["f"]["manifest"]["items"]["cut"] = {"display": "Cut", "texture": "t"}
        world.features["f"]["manifest"]["recipes"]["cut"] = {"mode": "open", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["#$tag:gems"], "result": {"id": "$item:cut"}}}
        recipes = balance._read_recipes(world.features)
        self.assertEqual(next(recipe for recipe in recipes if recipe["source"] == "f/cut")["inputs"][0][0], ["item:f/token"])
        self.assertEqual(balance._check_obtainable(world.features, recipes), [])
        world.render()
        self.assertEqual(world.read("datapack", f"data/gm/tags/item/{hashed('gems')}.json")["values"], [f"gm:{world.ledger['items']['f/token']['slot']}"])
        world.check()


class Ladders(unittest.TestCase):
    def test_a_ladder_is_one_picture_on_a_wall(self):
        with self.assertRaisesRegex(GateFailed, "can't have faces"):
            static.check_block_kinds(World(self, blocks={"rung": {"family": "ladder", "display": "Rung", "texture": "t", "faces": {"top": "t"}}}).features)

    def test_it_cant_glow(self):
        with self.assertRaisesRegex(GateFailed, "emissive"):
            static.check_block_kinds(World(self, blocks={"rung": {"family": "ladder", "display": "Rung", "texture": "t", "emissive": True}}).features)


class WornArmour(unittest.TestCase):
    PLATE = {"assets/gm/equipment/plate.json": {"layers": {"humanoid": [{"texture": "$texture:plate"}], "humanoid_leggings": [{"texture": "$texture:plate"}]}},
             "assets/gm/textures/entity/equipment/humanoid/plate.png": (64, 32), "assets/gm/textures/entity/equipment/humanoid_leggings/plate.png": (64, 32)}

    def wearable(self):
        return {"token": {"display": "Plate", "texture": "t", "tier": "iron", "components": {"minecraft:equippable": {"slot": "chest", "asset_id": "$equipment:plate"}, "minecraft:max_stack_size": 1}}}

    def test_an_item_wears_its_own_art(self):
        world = World(self, self.PLATE, items=self.wearable())
        out = world.render()
        slot = world.ledger["items"]["f/token"]["slot"]
        self.assertEqual(world.read("config", "item_defaults.json")[f"gm:{slot}"]["components"]["minecraft:equippable"]["asset_id"], f"gm:{hashed('plate')}")
        self.assertEqual(world.read("pack", f"assets/gm/equipment/{hashed('plate')}.json")["layers"]["humanoid"][0]["texture"], f"gm:{hashed('plate')}")
        world.check()
        static.check_spoilers(out / "pack")
        static.check_textures(out / "pack")
        static.check_items(world.features)

    def test_a_layer_with_no_picture_shows_nothing(self):
        files = {key: value for key, value in self.PLATE.items() if "leggings/" not in key}
        with self.assertRaisesRegex(GateFailed, "needs raw/assets/gm/textures/entity/equipment/humanoid_leggings/plate.png"):
            World(self, files, items=self.wearable()).check()

    def test_an_unknown_layer(self):
        with self.assertRaisesRegex(GateFailed, "the layer hat"):
            World(self, {"assets/gm/equipment/plate.json": {"layers": {"hat": [{"texture": "minecraft:iron"}]}}}).check()

    def test_the_wrong_shape_of_picture(self):
        world = World(self, {**self.PLATE, "assets/gm/textures/entity/equipment/humanoid/plate.png": (32, 32)}, items=self.wearable())
        out = world.render()
        with self.assertRaisesRegex(GateFailed, "64 by 32"):
            static.check_textures(out / "pack")

    def test_a_bad_picture(self):
        world = World(self, {**self.PLATE, "assets/gm/textures/entity/equipment/humanoid/plate.png": "not a picture"}, items=self.wearable())
        out = world.render()
        with self.assertRaisesRegex(GateFailed, "isn't a valid PNG"):
            static.check_textures(out / "pack")

    def test_it_needs_a_slot(self):
        world = World(self, self.PLATE, items={"token": {"display": "Plate", "texture": "t", "components": {"minecraft:equippable": {"asset_id": "$equipment:plate"}}}})
        with self.assertRaisesRegex(GateFailed, "needs a slot"):
            static.check_items(world.features)

    def test_worn_numbers_answer_to_the_same_curve(self):
        items = self.wearable()
        items["token"]["components"]["minecraft:attribute_modifiers"] = [{"type": "minecraft:armor", "amount": 99, "operation": "add_value", "slot": "chest", "id": "gm:x"}]
        self.assertIn("armor 99", " ".join(balance.check_power(World(self, self.PLATE, items=items).features, [])))

    def test_changing_the_art_counts_as_changing_the_item(self):
        world = World(self, self.PLATE, items=self.wearable())
        before = progression.snapshot(world.features)
        path = world.features["f"]["dir"] / "raw/assets/gm/equipment/plate.json"
        path.write_text(json.dumps({"layers": {"humanoid": [{"texture": "minecraft:iron"}]}}), encoding="utf-8")
        self.assertNotEqual(before["f/token"], progression.snapshot(world.features)["f/token"])


class OtherRegistries(unittest.TestCase):
    def test_a_music_disc(self):
        World(self, {"data/gm/jukebox_song/hum.json": SONG}, sounds=["hum"]).check()

    def test_a_sound_has_to_be_named_the_long_way(self):
        with self.assertRaisesRegex(GateFailed, "sound_id"):
            World(self, {"data/gm/jukebox_song/hum.json": {**SONG, "sound_event": "$sound:hum"}}, sounds=["hum"]).check()

    def test_a_sound_nobody_listed(self):
        with self.assertRaisesRegex(GateFailed, r"\$sound:hum"):
            World(self, {"data/gm/jukebox_song/hum.json": SONG}).check()

    def test_a_song_with_no_length(self):
        with self.assertRaisesRegex(GateFailed, "length_in_seconds"):
            World(self, {"data/gm/jukebox_song/hum.json": {**SONG, "length_in_seconds": 0}}, sounds=["hum"]).check()

    PAINTING = {"asset_id": "$texture:view", "width": 2, "height": 1}

    def test_a_painting(self):
        world = World(self, {"data/gm/painting_variant/view.json": self.PAINTING, "assets/gm/textures/painting/view.png": (32, 16),
                             "data/minecraft/tags/painting_variant/placeable.json": {"values": ["$painting_variant:view"]}})
        out = world.render()
        world.check()
        self.assertEqual(world.read("datapack", f"data/gm/painting_variant/{hashed('view')}.json")["asset_id"], f"gm:{hashed('view')}")
        static.check_spoilers(out / "pack")
        static.check_textures(out / "pack")

    def test_a_painting_with_nothing_to_show(self):
        with self.assertRaisesRegex(GateFailed, "needs raw/assets/gm/textures/painting/view.png"):
            World(self, {"data/gm/painting_variant/view.json": self.PAINTING}).check()

    def test_a_banner_pattern(self):
        files = {"data/gm/banner_pattern/mark.json": {"asset_id": "$texture:mark", "translation_key": "block.gm.banner.mark"}, "assets/gm/textures/entity/banner/mark.png": (64, 64), "assets/gm/textures/entity/shield/mark.png": (64, 64)}
        World(self, files).check()

    def test_a_mob_variant_says_its_pictures_whole_path(self):
        files = {"data/gm/cow_variant/spotted.json": {"asset_id": "gm:entity/cow/$name:spotted", "baby_asset_id": "gm:entity/cow/$name:spotted", "spawn_conditions": []},
                 "assets/gm/textures/entity/cow/spotted.png": (64, 64)}
        world = World(self, files)
        out = world.render()
        world.check()
        self.assertEqual(world.read("datapack", f"data/gm/cow_variant/{hashed('spotted')}.json")["asset_id"], f"gm:entity/cow/{hashed('spotted')}")
        self.assertTrue((out / f"pack/assets/gm/textures/entity/cow/{hashed('spotted')}.png").exists())
        static.check_spoilers(out / "pack")
        static.check_textures(out / "pack")

    def test_a_name_on_the_end_of_a_path_still_has_to_be_there(self):
        with self.assertRaisesRegex(GateFailed, r"\$name:nothing"):
            World(self, {"data/gm/cow_variant/spotted.json": {"asset_id": "gm:entity/cow/$name:nothing", "baby_asset_id": "gm:entity/cow/$name:nothing", "spawn_conditions": []}}).check()

    def test_a_damage_type(self):
        World(self, {"data/gm/damage_type/scald.json": {"message_id": "scald", "scaling": "never", "exhaustion": 0.1}}).check()
        with self.assertRaisesRegex(GateFailed, "scaling"):
            World(self, {"data/gm/damage_type/scald.json": {"message_id": "scald", "scaling": "sometimes", "exhaustion": 0.1}}).check()

    def test_too_much_art(self):
        world = World(self)
        with unittest.mock.patch.object(raw, "MOST_RAW_BYTES", 10):
            world = World(self, {"assets/gm/textures/painting/view.png": (32, 16)})
            with self.assertRaisesRegex(GateFailed, "every player downloads"):
                world.check()


class Advancements(unittest.TestCase):
    def refused(self, mention, **fields):
        with self.assertRaisesRegex(GateFailed, mention):
            World(self, {"data/gm/advancement/x.json": {**ADVANCEMENT, **fields}}).check()

    def test_a_good_one(self):
        World(self, {"data/gm/advancement/x.json": {**ADVANCEMENT, "rewards": {"experience": 50}, "parent": "minecraft:story/root"}}).check()

    def test_recipes_are_learned_through_knowledge(self):
        self.refused("rewards recipes", rewards={"recipes": ["minecraft:diamond_sword"]})

    def test_too_much_experience(self):
        self.refused("experience", rewards={"experience": 100000})

    def test_loot_has_to_be_its_own(self):
        self.refused("loot table", rewards={"loot": ["minecraft:chests/end_city_treasure"]})

    def test_it_has_to_be_able_to_happen(self):
        self.refused("needs criteria", criteria={})
        self.refused("trigger", criteria={"x": {"trigger": "minecraft:nonsense"}})
        self.refused("could never be earned", requirements=[["other"]])

    def test_what_it_shows(self):
        self.refused("needs an icon", display={"title": {"text": "x"}})
        self.refused("the icon", display={"icon": {"id": "emberstone"}, "title": {"text": "x"}, "description": {"text": "x"}})
        self.refused("the frame", display={**ADVANCEMENT["display"], "frame": "gold"})

    def test_a_parent_that_isnt_real(self):
        self.refused("the parent", parent="minecraft:story/nothing")


class Biomes(unittest.TestCase):
    def test_a_name_that_isnt_a_biome(self):
        for value in ("minecraft:not_a_biome", "plains", "Minecraft:Plains", "$biome:nothing", "gm:b123"):
            plant = {"id": "a", "block": "b", "biomes": [value]}
            with self.assertRaises(GateFailed, msg=value):
                raw.run(World(self, plants=[plant], blocks={"b": {"family": "plant", "display": "B", "texture": "t"}}).features)
            self.assertTrue(raw.check_biomes(World(self, ores=[{"id": "a", "block": "b", "biomes": [value]}]).features))
            self.assertTrue(raw.check_biomes(World(self, ruins={"r": {"id": "a", "biomes": [value]}}).features))
            self.assertTrue(raw.check_biomes(World(self, mobs={"m": {"spawn": {"biomes": [value]}}}).features))

    def test_whats_already_out_is_left_alone(self):
        """An old mistake does nothing but keep a plant from growing, so it mustn't hold up every release after it."""
        features = World(self, plants=[{"id": "old", "block": "b", "biomes": ["minecraft:not_a_biome"]}, {"id": "new", "block": "b", "biomes": ["minecraft:not_a_biome"]}],
                         mobs={"m": {"spawn": {"biomes": ["minecraft:not_a_biome"]}}}).features
        problems = raw.check_biomes(features, old_ledger={"patches": ["old"], "mobs": {"f/m": {}}})
        self.assertEqual(len(problems), 1)
        self.assertIn("new", problems[0])

    def test_real_ones(self):
        self.assertEqual(raw.check_biomes(World(self, plants=[{"id": "a", "block": "b", "biomes": ["minecraft:plains", "minecraft:the_void"]}]).features), [])

    def test_only_a_mob_can_use_tags(self):
        self.assertTrue(raw.check_biomes(World(self, plants=[{"id": "a", "biomes": ["#minecraft:is_forest"]}]).features))
        self.assertEqual(raw.check_biomes(World(self, mobs={"m": {"spawn": {"biomes": ["#minecraft:is_forest"]}}}).features), [])
        self.assertTrue(raw.check_biomes(World(self, mobs={"m": {"spawn": {"biomes": ["#minecraft:nothing"]}}}).features))

    def test_a_biome_of_this_worlds_by_its_token(self):
        biome = {"meadow": {"base": "minecraft:plains", "effects": {"grass_color": "#2e8b57"}}}
        world = World(self, biomes=biome, blocks={"b": {"family": "plant", "display": "B", "texture": "t"}}, plants=[{"id": "a", "block": "b", "biomes": ["$biome:meadow", "minecraft:plains"]}],
                      ores=[{"id": "o", "block": "b", "replaces": ["minecraft:stone"], "veinsPerChunk": 1, "veinSize": 1, "minY": 0, "maxY": 1, "biomes": ["$biome:meadow"]}])
        self.assertEqual(raw.check_biomes(world.features), [])
        world.render()
        expected = world.read("config", "biome_patches.json")[0]["to"]
        self.assertEqual(world.read("config", "surface_patches.json")[0]["biomes"], [expected, "minecraft:plains"])
        self.assertEqual(world.read("config", "ore_patches.json")[0]["biomes"], [expected])

    def test_in_a_ruin_and_a_mobs_spawn_too(self):
        ruin = {"r": {"id": "r1", "parts": [{"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"}], "on": ["minecraft:stone"], "replaces": ["minecraft:air"], "chance": 0.1, "minY": 0, "maxY": 1, "biomes": ["$biome:meadow"]}}
        world = World(self, biomes={"meadow": {"base": "minecraft:plains"}}, ruins=ruin)
        world.render()
        self.assertEqual(world.read("config", "ruin_patches.json")[0]["biomes"], [world.read("config", "biome_patches.json")[0]["to"]])

    def test_another_features_biome(self):
        world = World(self, biomes={"meadow": {"base": "minecraft:plains"}})
        world.add("g", {}, {"plants": [{"id": "a", "block": "f/b", "biomes": ["$biome:f/meadow"]}]})
        self.assertEqual(raw.check_biomes(world.features), [])

    def test_a_biome_starting_from_nothing_real(self):
        self.assertTrue(raw.check_biomes(World(self, biomes={"meadow": {"base": "minecraft:not_a_biome"}}).features))

    def test_what_the_bundler_does_with_one_that_isnt_there(self):
        world = World(self, biomes={"meadow": {"base": "minecraft:not_a_biome"}})
        def missing(name):
            raise ValueError(f"There's no vanilla biome called {name}")
        ledger = bundles.assign_slots(world.features, bundles.empty_ledger(), POOL)
        with self.assertRaisesRegex(bundles.BundleError, "no vanilla biome"):
            bundles.render(world.features, ledger, world.root / "out", 1, vanilla_biome=missing)


class TheFilesInTheRepository(unittest.TestCase):
    def test_every_token_kind_is_a_folder_that_can_ship(self):
        for kind, registry in rawpack.TOKEN_FOLDERS.items():
            self.assertIn(registry, rawpack.RELOADED_RAW | rawpack.STARTUP_RAW, kind)

    def test_vanillas_names_are_there(self):
        for table in ("block", "item", "entity_type", "biome", "enchantment", "trigger", "loot_function", "loot_entry", "sound_event", "loot_table", "advancement"):
            self.assertTrue(raw.VANILLA[table], table)
        self.assertEqual(raw.VANILLA["enchantment"]["sharpness"], 5)
        self.assertIn("climbable", raw.VANILLA["tags"]["block"])
        self.assertIn("is_forest", raw.VANILLA["tags"]["worldgen/biome"])

    def test_the_unfair_tags_are_real_ones(self):
        for registry, pattern in raw.UNFAIR_TAGS.items():
            self.assertTrue([tag for tag in raw.VANILLA["tags"][registry.removeprefix("tags/")] if pattern.fullmatch(tag)], registry)

    def test_nothing_changes_the_manifest(self):
        manifest = base_manifest(loot_additions=[{"table": "minecraft:chests/simple_dungeon", "pools": LootAdditions.PILE}])
        before = copy.deepcopy(manifest)
        world = World(self, **manifest)
        world.render()
        self.assertEqual(manifest["loot_additions"], before["loot_additions"])


if __name__ == "__main__":
    unittest.main()
