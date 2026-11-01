#!/usr/bin/env python3
"""A machine recipe goes on the list its machine's module reads, whichever feature declared it.

Usage: python3 -m unittest broker.tests.test_machine_home
"""
import json
import pathlib
import tempfile
import unittest

from broker import bundles


def feature(blocks=(), **fields):
    return {"manifest": {"blocks": {name: {} for name in blocks}, **fields}}


class Home(unittest.TestCase):
    def setUp(self):
        self.features = {"engine": feature(["kiln"]), "quarry": feature(["head"]), "old_oven": feature(["oven"]), "new_oven": feature(["oven"])}

    def home(self, owner, machine):
        return bundles._machine_home(self.features, owner, machine)

    def test_a_features_own_machine_stays_with_it(self):
        self.assertEqual(self.home("engine", "kiln"), "engine/kiln")

    def test_a_recipe_for_another_features_machine_goes_to_that_machine(self):
        self.assertEqual(self.home("quarry", "kiln"), "engine/kiln")

    def test_a_machine_with_no_block_of_that_name_is_its_own_features(self):
        self.assertEqual(self.home("quarry", "crusher"), "quarry/crusher")

    def test_its_own_block_wins_over_anothers(self):
        self.assertEqual(self.home("old_oven", "oven"), "old_oven/oven")

    def test_two_other_owners_arent_guessed_between(self):
        self.assertEqual(self.home("quarry", "oven"), "quarry/oven")

    def test_a_full_name_is_taken_as_it_is(self):
        self.assertEqual(self.home("quarry", "new_oven/oven"), "new_oven/oven")


class Release(unittest.TestCase):
    def test_a_release_files_it_under_the_real_machine(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            manifests = {
                "engine": {"id": "engine", "blocks": {"kiln": {"family": "machine", "display": "Kiln"}},
                           "recipes": {"own": {"mode": "open", "machine": "kiln", "inputs": [{"item": "minecraft:coal", "count": 1}], "output": {"item": "minecraft:iron_ingot", "count": 1}}}},
                "quarry": {"id": "quarry", "items": {"alloy": {"display": "Alloy"}},
                           "knowledge": {"quarrying": {"title": "Quarrying", "text": "Words.", "routes": [{"type": "obtain", "id": "$item:alloy"}]}},
                           "recipes": {"fire": {"mode": "known", "route": "quarrying", "machine": "kiln", "inputs": [{"item": "minecraft:coal", "count": 2}], "output": {"item": "$item:alloy", "count": 2}}}},
            }
            for name, manifest in manifests.items():
                textures = root / "features" / name / "assets" / "textures"
                textures.mkdir(parents=True)
                for thing in ("kiln", "alloy"):
                    (textures / f"{thing}.png").write_bytes(b"")
                (root / "features" / name / "feature.json").write_text(json.dumps(manifest), encoding="utf-8")
            found = bundles.load_features(root / "features")
            pool = {"families": {"machine": {"first": 1, "count": 5}}, "item_count": 5, "mobs": {"monster": 1, "creature": 1}}
            ledger = bundles.assign_slots(found, bundles.empty_ledger(), pool)
            bundles.render(found, ledger, root / "out", 1)
            machines = json.loads((root / "out" / "config" / "knowledge.json").read_text(encoding="utf-8"))["machines"]
        self.assertEqual(sorted(machines), ["engine/kiln"])
        recipes = {recipe["id"]: recipe for recipe in machines["engine/kiln"]}
        self.assertEqual(sorted(recipes), ["engine/own", "quarry/fire"])
        # Everything else about it still comes from the feature that declared it.
        self.assertEqual(recipes["quarry/fire"]["needs"], ["quarry/quarrying"])
        self.assertEqual(recipes["quarry/fire"]["outputs"], [{"item": "gm:" + ledger["items"]["quarry/alloy"]["slot"], "count": 2}])


if __name__ == "__main__":
    unittest.main()
