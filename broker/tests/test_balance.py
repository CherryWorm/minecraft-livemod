"""The balance gate. Needs no server: a feature here is only its manifest.

Usage: python3 -m unittest broker.tests.test_balance
"""
import json
import pathlib
import tempfile
import unittest

from broker.gates import GateFailed, balance, static

EMBER = pathlib.Path(__file__).parent / "fixtures" / "ember"
LORE = pathlib.Path(__file__).parent / "fixtures" / "lore"


def feature(**manifest):
    return {"manifest": manifest, "dir": pathlib.Path(".")}


def shaped(pattern, key, result, mode="open", **extra):
    return {"mode": mode, "json": {"type": "minecraft:crafting_shaped", "pattern": pattern, "key": key, "result": result}, **extra}


def shapeless(ingredients, result, mode="open", **extra):
    return {"mode": mode, "json": {"type": "minecraft:crafting_shapeless", "ingredients": ingredients, "result": result}, **extra}


def from_iron(result_id, components=None, **extra):
    """A recipe with an obtainable input, so tests of what it makes aren't tripped up by where it comes from."""
    result = {"id": result_id, "count": 1}
    if components is not None:
        result["components"] = components
    return shapeless(["minecraft:iron_ingot"], result, **extra)


def tool(rules_speed=None, damage_per_block=1, default=1.0):
    rules = [{"blocks": "#minecraft:mineable/pickaxe", "speed": rules_speed, "correct_for_drops": True}] if rules_speed else []
    return {"rules": rules, "default_mining_speed": default, "damage_per_block": damage_per_block}


def modifiers(damage=None, speed=None, armor=None, slot="mainhand", **others):
    found = []
    for kind, amount in (("attack_damage", damage), ("attack_speed", speed), ("armor", armor), *others.items()):
        if amount is not None:
            found.append({"type": f"minecraft:{kind}", "id": f"gm:{kind}", "amount": amount, "operation": "add_value", "slot": slot})
    return found


def with_item(components=None, tier="iron", **thing):
    """A feature with one item a recipe makes, carrying these components."""
    item = {"display": "X", **thing}
    if tier is not None:
        item["tier"] = tier
    return {"f": feature(items={"x": item}, recipes={"x": from_iron("$item:x", components)})}


class Case(unittest.TestCase):
    def assert_passes(self, features):
        balance.run(features)

    def assert_fails(self, features, *mentions):
        with self.assertRaises(GateFailed) as caught:
            balance.run(features)
        self.assertEqual(caught.exception.gate, "balance")
        for mention in mentions:
            self.assertIn(mention, caught.exception.message)
        return caught.exception.message


class Fixture(Case):
    def test_ember_passes(self):
        data = json.loads((EMBER / "feature.json").read_text(encoding="utf-8"))
        self.assert_passes({"ember": {"manifest": data, "dir": EMBER}})

    def test_lore_passes(self):
        data = json.loads((LORE / "feature.json").read_text(encoding="utf-8"))
        self.assert_passes({"lore": {"manifest": data, "dir": LORE}})

    def test_static_gate_runs_this(self):
        with tempfile.TemporaryDirectory() as folder:
            content = pathlib.Path(folder)
            for part in ("pack", "datapack"):
                (content / part).mkdir()
            (content / "recipes.json").write_text("{}", encoding="utf-8")
            ledger = {"blocks": {}, "items": {}, "patches": []}
            pool = {"families": {}, "item_count": 10}
            static.run({}, ledger, ledger, pool, content)
            features = {"f": feature(items={"x": {"display": "X"}})}
            with self.assertRaises(GateFailed) as caught:
                static.run(features, ledger, ledger, pool, content)
            self.assertEqual(caught.exception.gate, "balance")


class Declared(Case):
    def declare(self, stats, tier="iron", table="items"):
        thing = {"display": "X", "stats": stats}
        if tier is not None:
            thing["tier"] = tier
        recipe_result = "$block:x" if table == "blocks" else "$item:x"
        return {"f": feature(**{table: {"x": thing}}, recipes={"x": from_iron(recipe_result)})}

    def test_within_budget(self):
        self.assert_passes(self.declare({"durability": 250, "mining_speed": 6.0, "attack_damage": 4, "attack_speed": 1.2}))

    def test_exactly_at_110_percent(self):
        self.assert_passes(self.declare({"durability": 275, "mining_speed": 6.6}))
        self.assert_passes(self.declare({"durability": 64.9}, tier="wood"))

    def test_just_over_110_percent(self):
        self.assert_fails(self.declare({"durability": 276}), "durability 276", "over its limit of 275")
        self.assert_fails(self.declare({"mining_speed": 6.7}), "mining_speed")

    def test_each_tier_has_its_own_curve(self):
        for tier, durability, speed, armor in (("wood", 59, 2, 3), ("stone", 131, 4, 5), ("iron", 250, 6, 6),
                                               ("diamond", 1561, 8, 8), ("netherite", 2031, 9, 8)):
            with self.subTest(tier):
                self.assert_passes(self.declare({"durability": durability, "mining_speed": speed}, tier=tier))
                self.assert_passes(self.declare({"armor": armor, "slot": "chest"}, tier=tier))
                self.assert_fails(self.declare({"durability": durability * 1.2}, tier=tier), "durability")
                self.assert_fails(self.declare({"mining_speed": speed * 1.2}, tier=tier), "mining_speed")
                self.assert_fails(self.declare({"armor": armor * 1.2, "slot": "chest"}, tier=tier), "armor")

    def test_stats_with_no_tier(self):
        self.assert_fails(self.declare({"durability": 10}, tier=None), "no tier")

    def test_no_stats_needs_no_tier(self):
        self.assert_passes({"f": feature(items={"x": {"display": "X"}}, recipes={"x": from_iron("$item:x")})})

    def test_unknown_tier(self):
        self.assert_fails(self.declare({"durability": 10}, tier="mithril"), "mithril", "must be one of")
        self.assert_fails({"f": feature(items={"x": {"tier": "mithril"}}, recipes={"x": from_iron("$item:x")})}, "mithril")

    def test_stat_with_no_curve(self):
        self.assert_fails(self.declare({"luck": 5}), "luck", "no vanilla curve")

    def test_numbers_that_arent(self):
        for value in ("many", True, None, [1]):
            with self.subTest(value):
                self.assert_fails(self.declare({"durability": value}), "must be a number")

    def test_nan_and_infinity_cant_slip_through(self):
        # json.loads accepts both, and NaN compares false with everything.
        for text in ("NaN", "Infinity", "1e999"):
            with self.subTest(text):
                self.assert_fails(self.declare(json.loads(f'{{"durability": {text}}}')), "durability")

    def test_damage_and_speed_are_judged_together(self):
        self.assert_passes(self.declare({"attack_damage": 6, "attack_speed": 1.6}))
        self.assert_fails(self.declare({"attack_damage": 9, "attack_speed": 1.6}), "damage_per_second")
        self.assert_passes(self.declare({"attack_damage": 9, "attack_speed": 0.9}))

    def test_leaving_out_attack_speed_means_the_base_rate(self):
        self.assert_fails(self.declare({"attack_damage": 6}), "damage_per_second", "attack_speed")

    def test_armor_uses_the_armor_durability_curve(self):
        self.assert_passes(self.declare({"durability": 528, "armor": 8, "slot": "chest"}, tier="diamond"))
        self.assert_fails(self.declare({"durability": 1561, "armor": 8, "slot": "chest"}, tier="diamond"), "durability")

    def test_armor_depends_on_the_slot(self):
        self.assert_passes(self.declare({"armor": 3.3, "slot": "feet"}, tier="diamond"))
        self.assert_fails(self.declare({"armor": 8, "slot": "feet"}, tier="diamond"), "armor")

    def test_bad_slot(self):
        self.assert_fails(self.declare({"armor": 1, "slot": "tail"}), "tail")

    def test_toughness_and_knockback(self):
        self.assert_fails(self.declare({"armor_toughness": 1, "slot": "chest"}, tier="iron"), "armor_toughness")
        self.assert_passes(self.declare({"armor_toughness": 2, "slot": "chest"}, tier="diamond"))
        self.assert_passes(self.declare({"knockback_resistance": 0.1, "slot": "chest"}, tier="netherite"))
        self.assert_fails(self.declare({"knockback_resistance": 0.1, "slot": "chest"}, tier="diamond"), "knockback")

    def test_blocks_can_declare_too(self):
        self.assert_passes(self.declare({"hardness": 5, "blast_resistance": 6}, table="blocks"))
        self.assert_fails(self.declare({"hardness": 50}, table="blocks"), "hardness")
        self.assert_fails(self.declare({"hardness": 5}, tier=None, table="blocks"), "no tier")

    def test_beyond_has_its_own_ceiling(self):
        self.assert_passes(self.declare({"durability": 3046, "mining_speed": 13.5}, tier="beyond"))
        self.assert_fails(self.declare({"durability": 3047}, tier="beyond"), "durability")

    def test_full_beyond_armor_lands_on_the_games_cap(self):
        full_set = sum(balance._limits("beyond", slot, True)["armor"] for slot in ("head", "chest", "legs", "feet"))
        self.assertEqual(round(full_set), 30)


class Components(Case):
    def test_vanilla_iron_sword_passes(self):
        self.assert_passes(with_item({"minecraft:max_damage": 250, "minecraft:attribute_modifiers": modifiers(damage=5, speed=-2.4),
                                      "minecraft:tool": {"rules": [{"blocks": "minecraft:cobweb", "speed": 15.0, "correct_for_drops": True},
                                                                   {"blocks": "#minecraft:sword_instantly_mines", "speed": 3.4e38},
                                                                   {"blocks": "#minecraft:sword_efficient", "speed": 1.5}],
                                                         "damage_per_block": 2}}))

    def test_every_vanilla_weapon_and_tool_fits_its_own_tier(self):
        # Damage and speed as in Items.class, as the amounts a modifier adds to the base 1 and 4.
        materials = {"wood": (0, 59, 2), "stone": (1, 131, 4), "iron": (2, 250, 6), "diamond": (3, 1561, 8), "netherite": (4, 2031, 9)}
        axes = {"wood": (6, -3.2), "stone": (7, -3.2), "iron": (6, -3.1), "diamond": (5, -3.0), "netherite": (5, -3.0)}
        hoe_speed = {"wood": -3.0, "stone": -2.0, "iron": -1.0, "diamond": 0.0, "netherite": 0.0}
        for tier, (bonus, durability, speed) in materials.items():
            shapes = {"sword": (3 + bonus, -2.4), "shovel": (1.5 + bonus, -3.0), "pickaxe": (1 + bonus, -2.8),
                      "axe": (axes[tier][0] + bonus, axes[tier][1]), "hoe": (-bonus, hoe_speed[tier])}
            for shape, (damage, attack_speed) in shapes.items():
                with self.subTest(f"{tier} {shape}"):
                    self.assert_passes(with_item({"max_damage": durability, "tool": tool(speed),
                                                  "attribute_modifiers": modifiers(damage=damage, speed=attack_speed)}, tier=tier))

    def test_every_vanilla_armor_piece_fits_its_own_tier(self):
        for tier, (factor, points, toughness, knockback) in balance.ARMOR.items():
            for slot, armor, multiplier in zip(balance.SLOTS, points, balance.ARMOR_DURABILITY):
                with self.subTest(f"{tier} {slot}"):
                    extras = modifiers(armor=armor, slot=slot, armor_toughness=toughness, knockback_resistance=knockback)
                    self.assert_passes(with_item({"max_damage": factor * multiplier, "equippable": {"slot": slot},
                                                  "attribute_modifiers": extras}, tier=tier))

    def test_stat_components_need_a_tier(self):
        self.assert_fails(with_item({"minecraft:max_damage": 10}, tier=None), "durability", "no tier")

    def test_durability_over(self):
        self.assert_fails(with_item({"minecraft:max_damage": 300}), "durability 300")

    def test_names_without_a_namespace_are_the_same_component(self):
        # The game reads "max_damage" as minecraft:max_damage, so a check for the long name alone would miss it.
        self.assert_fails(with_item({"max_damage": 9999}), "durability")
        self.assert_fails(with_item({"attribute_modifiers": [{"type": "attack_damage", "amount": 50, "operation": "add_value", "slot": "mainhand"}]}),
                          "attack_damage")

    def test_mining_speed_over(self):
        self.assert_fails(with_item({"minecraft:tool": tool(20.0)}), "mining_speed 20")
        self.assert_fails(with_item({"minecraft:tool": tool(default=20.0)}), "mining_speed 20")

    def test_special_rule_doesnt_excuse_real_blocks(self):
        rule = {"blocks": ["minecraft:cobweb", "minecraft:stone"], "speed": 15.0}
        self.assert_fails(with_item({"minecraft:tool": {"rules": [rule]}}), "mining_speed 15")

    def test_never_wearing_out_is_infinite_durability(self):
        for components in ({"minecraft:unbreakable": {}}, {"minecraft:max_damage": 10, "minecraft:tool": tool(damage_per_block=0)},
                           {"minecraft:max_damage": 10, "minecraft:weapon": {"item_damage_per_attack": 0}}):
            with self.subTest(components):
                self.assert_fails(with_item(components, tier="beyond"), "durability inf")

    def test_damage_counts_the_base_of_one(self):
        # An iron sword's modifier is +5, and it hits for 6.
        self.assert_passes(with_item({"attribute_modifiers": modifiers(damage=8, speed=-3.1)}))
        self.assert_fails(with_item({"attribute_modifiers": modifiers(damage=9.0, speed=-3.1)}), "attack_damage 10")

    def test_several_modifiers_add_up(self):
        split = modifiers(damage=5, speed=-2.4) + modifiers(damage=5)
        self.assert_fails(with_item({"attribute_modifiers": split}), "attack_damage 11")

    def test_no_speed_modifier_is_the_base_speed(self):
        self.assert_fails(with_item({"attribute_modifiers": modifiers(damage=5)}), "damage_per_second 24")

    def test_old_modifier_shape(self):
        self.assert_fails(with_item({"attribute_modifiers": {"modifiers": modifiers(damage=50, speed=-2.4)}}), "attack_damage")

    def test_multipliers_cant_be_budgeted(self):
        boost = [{"type": "minecraft:attack_damage", "amount": 2.0, "operation": "add_multiplied_total", "slot": "mainhand"}]
        self.assert_fails(with_item({"attribute_modifiers": boost}), "add_multiplied_total", "add_value")

    def test_attributes_with_no_curve(self):
        self.assert_fails(with_item({"attribute_modifiers": modifiers(max_health=20)}), "max_health", "no vanilla curve")

    def test_drawbacks_are_free(self):
        self.assert_passes(with_item({"attribute_modifiers": modifiers(movement_speed=-0.1)}))

    def test_weapon_stats_must_be_in_the_main_hand(self):
        self.assert_fails(with_item({"attribute_modifiers": modifiers(damage=1, speed=-3, slot="chest")}), "stacks with a real weapon")
        self.assert_fails(with_item({"attribute_modifiers": modifiers(speed=3, slot="offhand")}), "stacks with a real weapon")

    def test_armor_stats_must_be_worn(self):
        self.assert_fails(with_item({"attribute_modifiers": modifiers(armor=2, slot="mainhand")}), "stacks with worn armor")

    def test_armor_piece_is_judged_by_its_slot(self):
        piece = {"max_damage": 240, "equippable": {"slot": "feet"}}
        self.assert_fails(with_item(piece), "durability 240")
        self.assert_passes(with_item({"max_damage": 195, "equippable": {"slot": "feet"}}))

    def test_components_with_no_curve_are_refused_at_every_tier(self):
        for name in ("minecraft:enchantments", "enchantments", "minecraft:death_protection", "minecraft:glider", "minecraft:damage_type"):
            with self.subTest(name):
                self.assert_fails(with_item({name: {}}, tier="beyond"), name.removeprefix("minecraft:"), "no vanilla curve")

    def test_harmless_components_need_no_tier(self):
        self.assert_passes(with_item({"minecraft:custom_name": "x", "minecraft:rarity": "rare", "minecraft:max_stack_size": 16}, tier=None))

    def test_vanilla_item_with_stats_needs_a_tier_on_the_recipe(self):
        recipe = from_iron("minecraft:iron_sword", {"minecraft:max_damage": 99999})
        self.assert_fails({"f": feature(recipes={"x": recipe})}, "no tier", "recipe")
        self.assert_fails({"f": feature(recipes={"x": {**recipe, "tier": "iron"}})}, "durability 99999")
        self.assert_passes({"f": feature(recipes={"x": {**from_iron("minecraft:iron_sword", {"minecraft:max_damage": 260}), "tier": "iron"}})})

    def test_other_features_items_keep_their_tier(self):
        features = {"a": feature(items={"x": {"display": "X", "tier": "wood"}}),
                    "b": feature(recipes={"x": from_iron("$item:a/x", {"minecraft:max_damage": 100})})}
        self.assert_fails(features, "durability 100", "limit of 64.9")

    def test_every_recipe_that_makes_an_item_counts(self):
        features = {"f": feature(items={"x": {"display": "X", "tier": "iron"}},
                                 recipes={"fair": from_iron("$item:x", {"minecraft:max_damage": 250}),
                                          "cheat": from_iron("$item:x", {"minecraft:max_damage": 9000})})}
        self.assert_fails(features, "f/cheat", "durability 9000")


class Cycles(Case):
    def nuggets(self, ingot_makes, nuggets_make_ingot):
        return {"f": feature(
            items={"ingot": {"display": "I"}, "nugget": {"display": "N"}},
            recipes={"split": shapeless(["$item:ingot"], {"id": "$item:nugget", "count": ingot_makes}),
                     "join": shaped(["X" * min(3, nuggets_make_ingot), "X" * max(0, nuggets_make_ingot - 3)],
                                    {"X": "$item:nugget"}, {"id": "$item:ingot", "count": 1}),
                     "seed": from_iron("$item:ingot")})}

    def test_nine_nuggets_eight_back_makes_material(self):
        # An ingot makes 9, and 8 of those make the ingot back, so each loop is one nugget up with nothing spent.
        self.assert_fails(self.nuggets(9, 8), "from nothing", "f/split x1", "f/join x1", "+1 item:f/nugget")

    def test_breaking_even_is_fine(self):
        self.assert_passes(self.nuggets(9, 9))

    def test_losing_material_is_fine(self):
        self.assert_passes(self.nuggets(8, 9))

    def test_a_longer_loop(self):
        recipes = {"ab": shapeless(["$item:a"], {"id": "$item:b", "count": 2}),
                   "bc": shapeless(["$item:b"], {"id": "$item:c", "count": 2}),
                   "ca": shaped(["XXX"], {"X": "$item:c"}, {"id": "$item:a", "count": 1}),
                   "start": from_iron("$item:a")}
        self.assert_fails({"f": feature(items={"a": {}, "b": {}, "c": {}}, recipes=recipes)}, "from nothing", "f/ab", "f/bc", "f/ca")

    def test_loop_across_features(self):
        features = {"one": feature(items={"a": {}}, recipes={"up": shapeless(["$item:two/b"], {"id": "$item:a", "count": 2}),
                                                             "start": from_iron("$item:a")}),
                    "two": feature(items={"b": {}}, recipes={"down": shapeless(["$item:one/a"], {"id": "$item:b", "count": 1})})}
        self.assert_fails(features, "one/up", "two/down")

    def test_a_recipe_that_makes_its_own_input(self):
        recipes = {"grow": shapeless(["$item:a"], {"id": "$item:a", "count": 2}), "start": from_iron("$item:a")}
        self.assert_fails({"f": feature(items={"a": {}}, recipes=recipes)}, "from nothing", "f/grow")

    def test_many_slots_and_counts(self):
        # 3 of a and 1 of b make 5 of a and 1 of b, which is a gain even though both inputs are returned.
        recipes = {"mix": {"mode": "open", "json": {"type": "gm:machine", "ingredients": [{"item": "$item:a", "count": 3}, "$item:b"],
                                                    "results": [{"id": "$item:a", "count": 5}, {"id": "$item:b", "count": 1}]},
                           "machine": True, "feedback": "x"},
                   "a": from_iron("$item:a"), "b": from_iron("$item:b")}
        self.assert_fails({"f": feature(items={"a": {}, "b": {}}, recipes=recipes)}, "f/mix")

    def test_alternatives_each_count(self):
        recipes = {"up": shapeless([["minecraft:stick", "$item:a"]], {"id": "$item:a", "count": 2})}
        self.assert_fails({"f": feature(items={"a": {}}, recipes=recipes)}, "from nothing", "f/up")

    def test_loop_through_vanilla_storage_recipes(self):
        # Fine alone, but vanilla turns 9 ingots into a block, so this makes one ingot per block forever.
        recipe = shapeless(["minecraft:iron_block"], {"id": "minecraft:iron_ingot", "count": 10})
        self.assert_fails({"f": feature(recipes={"x": recipe})}, "from nothing", "f/x", "vanilla")

    def test_vanilla_storage_alone_is_neutral(self):
        recipe = shapeless(["minecraft:iron_block"], {"id": "minecraft:iron_ingot", "count": 9})
        self.assert_passes({"f": feature(recipes={"x": recipe})})

    def test_paying_with_something_from_outside_is_a_conversion(self):
        # Like vanilla's template duplication: more comes out, but it costs diamonds each time.
        recipes = {"copy": shapeless(["$item:template", "minecraft:diamond"], {"id": "$item:template", "count": 2}),
                   "first": from_iron("$item:template")}
        self.assert_passes({"f": feature(items={"template": {}}, recipes=recipes)})

    def test_ordinary_crafting_chain_isnt_a_loop(self):
        recipes = {"plank": shapeless(["#minecraft:logs"], {"id": "minecraft:oak_planks", "count": 4}),
                   "stick": shaped(["X", "X"], {"X": "minecraft:oak_planks"}, {"id": "minecraft:stick", "count": 4})}
        self.assert_passes({"f": feature(recipes=recipes)})

    def test_too_many_combinations_to_check(self):
        options = [f"minecraft:item{index}" for index in range(10)]
        recipe = shapeless([options, options, options], {"id": "minecraft:stick", "count": 1})
        self.assert_fails({"f": feature(recipes={"x": recipe})}, "combinations")


class Obtainable(Case):
    def test_item_nothing_makes(self):
        self.assert_fails({"f": feature(items={"x": {"display": "X"}})}, "Nobody can obtain f/x", "retired")

    def test_block_nothing_makes(self):
        self.assert_fails({"f": feature(blocks={"x": {"display": "X", "family": "stone"}})}, "Nobody can obtain f/x")

    def test_retired_things_are_meant_to_be_unobtainable(self):
        self.assert_passes({"f": feature(items={"x": {"display": "X", "retired": True}},
                                         blocks={"y": {"display": "Y", "retired": True}})})

    def test_retired_input_doesnt_make_anything_obtainable(self):
        features = {"f": feature(items={"old": {"retired": True}, "new": {}},
                                 recipes={"x": shapeless(["$item:old"], {"id": "$item:new"})})}
        self.assert_fails(features, "Nobody can obtain f/new", "item:f/old")

    def test_recipe_from_vanilla(self):
        self.assert_passes({"f": feature(items={"x": {}}, recipes={"x": from_iron("$item:x")})})

    def test_tag_counts_as_vanilla(self):
        self.assert_passes({"f": feature(items={"x": {}}, recipes={"x": shapeless(["#minecraft:logs"], {"id": "$item:x"})})})

    def test_ore_drop(self):
        features = {"f": feature(blocks={"ore": {"family": "ore", "drops": {"item": "gem"}}}, items={"gem": {}},
                                 ores=[{"id": "o", "block": "ore", "veinsPerChunk": 3, "veinSize": 7, "minY": -40, "maxY": 48}])}
        self.assert_passes(features)

    def test_ore_that_drops_itself(self):
        features = {"f": feature(blocks={"ore": {"family": "ore"}, "brick": {}},
                                 recipes={"b": shapeless(["$block:ore"], {"id": "$block:brick"})},
                                 ores=[{"id": "o", "block": "ore", "veinsPerChunk": 3, "veinSize": 7, "minY": -40, "maxY": 48}])}
        self.assert_passes(features)

    def test_ore_with_other_drops_cant_be_held_as_an_ingredient(self):
        # It's in the world, so it's fine itself, but no loot table ever hands it to a player.
        features = {"f": feature(blocks={"ore": {"family": "ore", "drops": {"item": "gem"}}, "brick": {}}, items={"gem": {}},
                                 recipes={"b": shapeless(["$block:ore"], {"id": "$block:brick"})},
                                 ores=[{"id": "o", "block": "ore", "veinsPerChunk": 3, "veinSize": 7, "minY": -40, "maxY": 48}])}
        self.assert_fails(features, "Nobody can obtain f/brick")

    def test_drop_of_a_crafted_block(self):
        features = {"f": feature(blocks={"crate": {"drops": {"item": "plank"}}}, items={"plank": {}},
                                 recipes={"c": from_iron("$block:crate")})}
        self.assert_passes(features)

    def test_drop_of_a_block_nobody_can_get(self):
        features = {"f": feature(blocks={"crate": {"drops": {"item": "plank"}}}, items={"plank": {}})}
        message = self.assert_fails(features, "Nobody can obtain f/crate")
        self.assertIn("Nobody can obtain f/plank", message)

    def test_chain_of_recipes(self):
        recipes = {"a": from_iron("$item:a"), "b": shapeless(["$item:a"], {"id": "$item:b"}), "c": shapeless(["$item:b"], {"id": "$item:c"})}
        self.assert_passes({"f": feature(items={"a": {}, "b": {}, "c": {}}, recipes=recipes)})

    def test_recipe_needing_something_unobtainable(self):
        recipes = {"b": shapeless(["$item:a"], {"id": "$item:b"})}
        message = self.assert_fails({"f": feature(items={"a": {}, "b": {}}, recipes=recipes)}, "Nobody can obtain f/a", "Nobody can obtain f/b")
        self.assertIn("f/b needs item:f/a", message)

    def test_only_loop_with_no_way_in(self):
        recipes = {"ab": shapeless(["$item:a"], {"id": "$item:b"}), "ba": shapeless(["$item:b"], {"id": "$item:a"})}
        self.assert_fails({"f": feature(items={"a": {}, "b": {}}, recipes=recipes)}, "Nobody can obtain f/a")

    def test_known_recipes_count(self):
        recipe = from_iron("$item:x", mode="known", route="found in a chest")
        self.assert_passes({"f": feature(items={"x": {}}, recipes={"x": recipe})})

    def test_guessable_recipes_count(self):
        recipe = {"mode": "guessable", "machine": True, "feedback": "hums",
                  "json": {"type": "gm:machine", "ingredients": ["minecraft:iron_ingot"], "result": {"id": "$item:x"}}}
        self.assert_passes({"f": feature(items={"x": {}}, recipes={"x": recipe})})

    def test_either_alternative_is_enough(self):
        recipe = shapeless([["$item:never", "minecraft:stick"]], {"id": "$item:x"})
        features = {"f": feature(items={"x": {}, "never": {"retired": True}}, recipes={"x": recipe})}
        self.assert_passes(features)

    def test_vanilla_results_need_no_source(self):
        self.assert_passes({"f": feature(recipes={"x": shapeless(["minecraft:stick"], {"id": "minecraft:torch"})})})

    def test_shaped_inputs_are_read(self):
        recipes = {"a": shaped(["XX", "XX"], {"X": "$item:never"}, {"id": "$item:a"})}
        self.assert_fails({"f": feature(items={"a": {}, "never": {}}, recipes=recipes)}, "Nobody can obtain f/a")

    def test_smelting_and_smithing_inputs_are_read(self):
        recipes = {"s": {"mode": "open", "json": {"type": "minecraft:smelting", "ingredient": "$item:never", "cookingtime": 200, "result": {"id": "$item:a"}}},
                   "t": {"mode": "open", "json": {"type": "minecraft:smithing_transform", "template": "$item:never", "base": "minecraft:stick",
                                                  "addition": "minecraft:stick", "result": {"id": "$item:b"}}}}
        self.assert_fails({"f": feature(items={"a": {}, "b": {}, "never": {}}, recipes=recipes)}, "Nobody can obtain f/a", "Nobody can obtain f/b")

    def test_named_machine_recipes_count(self):
        recipe = {"mode": "guessable", "machine": "crucible", "feedback": "hums",
                  "inputs": [{"item": "$item:a", "count": 1}], "output": {"item": "$item:b", "count": 1}}
        self.assert_passes({"f": feature(items={"a": {}, "b": {}}, recipes={"a": from_iron("$item:a"), "b": recipe})})
        self.assert_fails({"f": feature(items={"a": {}, "b": {}}, recipes={"b": recipe})}, "Nobody can obtain f/b")

    def test_named_machine_recipes_cant_make_material_either(self):
        recipes = {"grow": {"mode": "open", "machine": "m", "inputs": [{"item": "$item:a", "count": 1}], "output": {"item": "$item:a", "count": 2}},
                   "a": from_iron("$item:a")}
        self.assert_fails({"f": feature(items={"a": {}}, recipes=recipes)}, "from nothing", "f/grow")

    def test_mob_drop(self):
        self.assert_passes({"f": feature(items={"gem": {}}, mobs={"crab": {"drops": {"item": "gem", "count": [1, 2]}}})})

    def test_plant_is_in_the_world_and_drops_itself(self):
        features = {"f": feature(blocks={"moss": {"family": "plant"}, "tea": {}},
                                 plants=[{"id": "p", "block": "moss", "perChunk": 1}],
                                 recipes={"t": shapeless(["$block:moss"], {"id": "$block:tea"})})}
        self.assert_passes(features)

    def test_ruin_chest(self):
        loot = {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item", "name": "$item:tablet"}]}]}
        self.assert_passes({"f": feature(items={"tablet": {}}, ruins={"shrine": {"id": "s", "parts": [], "loot": loot}})})

    def test_ruin_walls_can_be_broken_for_their_drop(self):
        parts = [{"x": 0, "y": 0, "z": 0, "block": "$block:wall"}, {"x": 1, "y": 0, "z": 0, "block": "minecraft:chest"}]
        features = {"f": feature(blocks={"wall": {"drops": {"item": "rubble"}}}, items={"rubble": {}}, ruins={"shrine": {"id": "s", "parts": parts}})}
        self.assert_passes(features)

    def test_hand_written_slot_id(self):
        self.assert_fails({"f": feature(recipes={"x": shapeless(["gm:i0007"], {"id": "minecraft:stick"})})}, "gm:i0007", "no feature declares")


class Ores(Case):
    def ore(self, veins=10, size=9, low=-24, high=56, tier="iron", drops=None, ore_tier=None, extra=None):
        block = {"family": "ore", "display": "O"}
        if tier:
            block["tier"] = tier
        items = {}
        if drops:
            block["drops"] = drops
            items[drops["item"]] = {"display": "G"}
        entry = {"id": "o1", "block": "o", "veinsPerChunk": veins, "veinSize": size, "minY": low, "maxY": high}
        if ore_tier:
            entry["tier"] = ore_tier
        return feature(blocks={"o": block}, items=items, ores=[entry] + (extra or []))

    def test_vanilla_table_is_what_the_game_really_does(self):
        self.assertAlmostEqual(balance.ORE_CURVE["iron"], 10 * 9 + 10 * 4 * 129 / 137)
        self.assertAlmostEqual(balance.ORE_CURVE["stone"], 16 * 10 * 81 / 129)
        self.assertAlmostEqual(balance.ORE_CURVE["wood"], 20 * 17 * 65 / 193)
        self.assertGreater(balance.ORE_CURVE["iron"], balance.ORE_CURVE["diamond"])
        self.assertGreater(balance.ORE_CURVE["diamond"], balance.ORE_CURVE["netherite"])
        self.assertGreater(balance.ORE_CURVE["netherite"], balance.ORE_CURVE["beyond"])

    def test_ember_has_no_tier_and_is_only_capped(self):
        self.assert_passes({"f": self.ore(veins=3, size=7, low=-40, high=48, tier=None)})

    def test_vanilla_iron_numbers_pass_as_iron(self):
        self.assert_passes({"f": self.ore()})

    def test_tiers_compare_with_their_own_ore(self):
        self.assert_passes({"f": self.ore(veins=4, size=8, low=-64, high=16, tier="diamond")})
        self.assert_passes({"f": self.ore(veins=1, size=3, low=-64, high=0, tier="netherite")})
        self.assert_passes({"f": self.ore(veins=1, size=2, low=-64, high=0, tier="beyond")})

    def test_too_common(self):
        self.assert_fails({"f": self.ore(veins=20, size=16, tier="diamond")}, "feeds tier diamond", "Lower")
        self.assert_fails({"f": self.ore(veins=10, size=9, tier="netherite")}, "feeds tier netherite")

    def test_too_rare(self):
        self.assert_fails({"f": self.ore(veins=1, size=2, tier="iron")}, "run dry")

    def test_edges_of_the_tolerance(self):
        limit = balance.ORE_CURVE["diamond"] * balance.ORE_TOLERANCE
        self.assert_passes({"f": self.ore(veins=limit / 10, size=10, low=-64, high=0, tier="diamond")})
        self.assert_fails({"f": self.ore(veins=(limit + 1) / 10, size=10, low=-64, high=0, tier="diamond")}, "feeds tier diamond")

    def test_y_range_above_the_rock_counts_for_little(self):
        # Half this range is in the air, so veins there are wasted.
        self.assert_passes({"f": self.ore(veins=30, size=9, low=-64, high=192, tier="iron")})
        self.assert_fails({"f": self.ore(veins=30, size=9, low=-64, high=64, tier="iron")}, "feeds tier iron")

    def test_y_range_below_the_world_counts_for_little(self):
        self.assert_fails({"f": self.ore(veins=4, size=8, low=-300, high=-65, tier="diamond")}, "never generates")

    def test_an_ore_that_can_never_generate(self):
        self.assert_fails({"f": self.ore(tier=None, low=100, high=200)}, "never generates")
        self.assert_fails({"f": self.ore(tier=None, low=20, high=10)}, "never generates")

    def test_no_tier_still_has_a_ceiling(self):
        self.assert_fails({"f": self.ore(veins=100, size=16, tier=None)}, "twice vanilla")

    def test_splitting_an_ore_into_entries_is_still_one_ore(self):
        extra = [{"id": f"o{index}", "block": "o", "veinsPerChunk": 10, "veinSize": 9, "minY": -24, "maxY": 56} for index in range(2, 5)]
        self.assert_fails({"f": self.ore(tier="iron", extra=extra)}, "feeds tier iron")

    def test_lots_of_drops_is_lots_of_ore(self):
        self.assert_fails({"f": self.ore(veins=4, size=8, low=-64, high=16, tier="diamond", drops={"item": "gem", "count": [8, 16]})},
                          "feeds tier diamond")

    def test_tier_read_from_the_ore_entry(self):
        self.assert_fails({"f": self.ore(tier=None, veins=20, size=16, ore_tier="diamond")}, "feeds tier diamond")

    def test_tier_read_from_what_it_drops(self):
        made = self.ore(tier=None, veins=20, size=16, drops={"item": "gem"})
        made["manifest"]["items"]["gem"]["tier"] = "diamond"
        self.assert_fails({"f": made}, "feeds tier diamond")

    def test_tier_read_from_what_it_feeds(self):
        made = self.ore(tier=None, veins=20, size=16, drops={"item": "gem"})
        made["manifest"]["items"]["sword"] = {"tier": "diamond"}
        made["manifest"]["recipes"] = {"s": shapeless(["$item:gem"], {"id": "$item:sword"})}
        self.assert_fails({"f": made}, "feeds tier diamond")

    def test_a_low_label_cant_undercut_what_it_makes(self):
        made = self.ore(tier="iron", drops={"item": "gem"})
        made["manifest"]["items"]["sword"] = {"tier": "netherite"}
        made["manifest"]["recipes"] = {"s": shapeless(["$item:gem"], {"id": "$item:sword"})}
        self.assert_fails({"f": made}, "feeds tier netherite")

    def test_unknown_tier_on_an_entry(self):
        self.assert_fails({"f": self.ore(tier=None, ore_tier="mithril")}, "mithril")

    def test_numbers_that_arent(self):
        made = self.ore()
        made["manifest"]["ores"][0]["veinSize"] = "lots"
        self.assert_fails({"f": made}, "needs numbers")
        made["manifest"]["ores"][0]["veinSize"] = float("nan")
        self.assert_fails({"f": made}, "needs numbers")


class ReportsEverything(Case):
    def test_all_problems_at_once(self):
        features = {"f": feature(items={"lonely": {}, "strong": {"tier": "wood", "stats": {"durability": 999}}},
                                 recipes={"s": from_iron("$item:strong")})}
        self.assert_fails(features, "lonely", "durability 999")

    def test_a_manifest_in_the_wrong_shape_fails_the_gate_instead_of_crashing(self):
        # A crash would leave promote with no report, and the daemon would read the last one instead.
        for manifest in ({"recipes": ["x"]}, {"items": ["x"]}, {"ores": ["x"]}, {"recipes": {"x": {"json": {"result": {"id": 5}}}}, "items": 3},
                         {"blocks": {"o": {"drops": "x"}}, "ores": [{"block": "o"}]}, {"mobs": {"m": {"drops": "x"}}}, {"ruins": {"r": {"parts": ["x"]}}},
                         {"recipes": {"x": from_iron("minecraft:stick", {"tool": {"rules": ["x"]}})}}):
            with self.subTest(manifest):
                self.assert_fails({"f": feature(**manifest)}, "wrong shape")


if __name__ == "__main__":
    unittest.main()
