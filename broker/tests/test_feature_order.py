#!/usr/bin/env python3
"""Biomes agreeing on the order of their features. A disagreement stops the server starting, so it's found here first. No servers needed.

Usage: python3 -m unittest broker.tests.test_feature_order
"""
import json
import pathlib
import tempfile
import unittest

from broker import bundles, feature_order
from broker.gates import GateFailed, static

STEPS = len(feature_order.STEPS)
VEGETAL = feature_order.STEPS.index("vegetal_decoration")


def features(*vegetal):
    """A biome with these features in the vegetal step and nothing in the others."""
    return [[] for _ in range(VEGETAL)] + [list(vegetal)] + [[] for _ in range(STEPS - VEGETAL - 1)]


def vegetal_of(found):
    return found[VEGETAL]


class Order(unittest.TestCase):
    def test_a_new_feature_goes_on_the_end_if_nothing_says_otherwise(self):
        order = feature_order.FeatureOrder([features("a", "b")], {"new"})
        self.assertEqual(vegetal_of(order.place("x", features("a", "b"), "vegetal_decoration", "new")), ["a", "b", "new"])

    def test_it_goes_before_what_another_biome_runs_it_before(self):
        # Another biome already runs it before b, so on the end of this list it would have to come both before and after b.
        order = feature_order.FeatureOrder([features("a", "b"), features("new", "b")], {"new"})
        self.assertEqual(vegetal_of(order.place("x", features("a", "b"), "vegetal_decoration", "new")), ["a", "new", "b"])

    def test_it_goes_after_what_another_biome_runs_it_after_as_well(self):
        order = feature_order.FeatureOrder([features("a", "b", "c"), features("a", "new", "c")], {"new"})
        self.assertEqual(vegetal_of(order.place("x", features("a", "b", "c"), "vegetal_decoration", "new")), ["a", "b", "new", "c"])

    def test_it_follows_a_chain_through_other_biomes(self):
        order = feature_order.FeatureOrder([features("a", "b"), features("new", "p"), features("p", "q"), features("q", "b")], {"new"})
        self.assertEqual(vegetal_of(order.place("x", features("a", "b"), "vegetal_decoration", "new")), ["a", "new", "b"])

    def test_with_nowhere_for_it_to_go_it_says_so(self):
        # b has to come before new, and new before a, but this biome runs a before b.
        order = feature_order.FeatureOrder([features("a", "b"), features("b", "new"), features("new", "a")], {"new"})
        with self.assertRaises(feature_order.OrderError) as caught:
            order.place("x", features("a", "b"), "vegetal_decoration", "new")
        self.assertIn("nowhere", str(caught.exception))

    def test_one_it_already_has_is_refused(self):
        with self.assertRaises(feature_order.OrderError):
            feature_order.FeatureOrder().place("x", features("a"), "vegetal_decoration", "a")

    def test_a_list_of_its_own_is_checked_as_the_game_would(self):
        order = feature_order.FeatureOrder([features("a", "b")])
        order.add_biome("fine", features("a", "c", "b"))
        with self.assertRaises(feature_order.OrderError) as caught:
            order.add_biome("backwards", features("b", "a"))
        self.assertIn("other way round", str(caught.exception))

    def test_one_biome_listing_a_feature_twice_is_refused(self):
        with self.assertRaises(feature_order.OrderError) as caught:
            feature_order.FeatureOrder().add_biome("twice", features("a", "b", "a"))
        self.assertIn("twice", str(caught.exception))

    def test_steps_run_in_order_too(self):
        early = [["a"]] + [[] for _ in range(STEPS - 1)]
        order = feature_order.FeatureOrder([[*early[:-1], ["b"]]])
        self.assertIsNotNone(order.place("x", early, "vegetal_decoration", "c"))

    def test_the_same_feature_in_two_steps_is_two_things(self):
        order = feature_order.FeatureOrder([[["a"], ["b"]]])
        order.add_biome("fine", [["b"], ["a"]])


class Rendering(unittest.TestCase):
    def render(self, biome, order):
        with tempfile.TemporaryDirectory() as folder:
            datapack = pathlib.Path(folder)
            base = {"features": features("a", "b"), "effects": {}}
            patch = bundles._render_biome("f", "b1", biome, lambda name: base, datapack, order)
            return patch, json.loads(next(datapack.rglob("*.json")).read_text(encoding="utf-8"))

    def test_adding_features_keeps_the_rest_of_the_base(self):
        order = feature_order.FeatureOrder([features("a", "b")], {"new"})
        patch, written = self.render({"base": "minecraft:plains", "add_features": {"vegetal_decoration": ["new"]}}, order)
        self.assertEqual(vegetal_of(written["features"]), ["a", "b", "new"])
        # Land people have already seen can't be given new features, so it can't count as only looking different.
        self.assertFalse(patch["sibling"])

    def test_a_feature_the_game_doesnt_have_is_said_plainly(self):
        order = feature_order.FeatureOrder([features("a", "b")], {"new"})
        with self.assertRaises(bundles.BundleError) as caught:
            self.render({"base": "minecraft:plains", "add_features": {"vegetal_decoration": ["minecraft:nothing"]}}, order)
        self.assertIn("no feature called minecraft:nothing", str(caught.exception))

    def test_a_list_of_its_own_that_clashes_is_refused_here_and_not_at_boot(self):
        order = feature_order.FeatureOrder([features("a", "b")], {"new"})
        with self.assertRaises(bundles.BundleError) as caught:
            self.render({"base": "minecraft:plains", "features": features("b", "a")}, order)
        self.assertIn("other way round", str(caught.exception))

    def test_a_biome_that_only_looks_different_is_still_a_sibling(self):
        patch, _ = self.render({"base": "minecraft:plains", "effects": {"grass_color": "#2e8b57"}}, None)
        self.assertTrue(patch["sibling"])

    def test_each_biome_goes_by_the_ones_before_it(self):
        order = feature_order.FeatureOrder([features("a", "b")], {"p", "q"})
        self.render({"base": "minecraft:plains", "add_features": {"vegetal_decoration": ["p", "q"]}}, order)
        with self.assertRaises(bundles.BundleError):
            self.render({"base": "minecraft:plains", "features": features("q", "p")}, order)


class TheInstantCheck(unittest.TestCase):
    def check(self, added):
        static.check_biome_features({"f": {"manifest": {"biomes": {"b": {"add_features": added}}}}})

    def test_a_step_that_doesnt_exist(self):
        with self.assertRaises(GateFailed) as caught:
            self.check({"vegetal": ["minecraft:patch_pumpkin"]})
        self.assertIn("The steps are", caught.exception.message)

    def test_a_good_one(self):
        self.check({"vegetal_decoration": ["minecraft:patch_pumpkin"]})

    def test_not_a_list(self):
        with self.assertRaises(GateFailed):
            self.check({"vegetal_decoration": "minecraft:patch_pumpkin"})
        with self.assertRaises(GateFailed):
            self.check(["minecraft:patch_pumpkin"])


if __name__ == "__main__":
    unittest.main()
