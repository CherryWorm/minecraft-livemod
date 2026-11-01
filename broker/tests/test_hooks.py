"""What the release gates and the bundler make of the engine's newer hooks: sounds by name, and ruins that vary. No servers needed.

Usage: python3 -m unittest broker.tests.test_hooks
"""
import json
import pathlib
import tempfile
import unittest

from broker import bundles, promote
from broker.gates import GateFailed, balance, static
from orchestrator import world_index

GROUND = ["minecraft:grass_block"]
OPEN = ["minecraft:air"]


def ruin(**fields):
    return {"id": "r_v1", "parts": [{"x": 1, "y": 0, "z": 1, "block": "minecraft:stone"}], "on": GROUND, "replaces": OPEN,
            "chance": 0.1, "minY": 0, "maxY": 200, **fields}


def without(entry, *names):
    return {key: value for key, value in entry.items() if key not in names}


def features(*ruins):
    return {"f": {"manifest": {"ruins": {f"r{index}": entry for index, entry in enumerate(ruins)}}}}


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

    def test_the_voices_say_how_far_apart_they_are(self):
        with tempfile.TemporaryDirectory() as folder:
            feature = pathlib.Path(folder, "camps")
            feature.mkdir()
            (feature / "feature.json").write_text(json.dumps({"id": "camps", "summary": "Camps.", "ruins": {
                "old_camp": {"spacing": 20, "chance": 0.5, "minY": 50, "maxY": 140, "parts": [{"x": 1}]}}}), encoding="utf-8")
            guide = world_index.player_entry(pathlib.Path(folder), "camps")
        self.assertIn("at least 20 chunks apart", guide)
        self.assertNotIn("one chunk in", guide)


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
            ledger = bundles.assign_slots(found, bundles.empty_ledger(), {"families": {"stone": {"first": 0, "count": 4}}, "item_count": 4, "mobs": {"monster": 1, "creature": 1}})
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
