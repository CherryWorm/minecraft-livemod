"""What the bundler and the gates make of dimensions: slots that stay put, land that can't change once it's out, what they bring with them, and when
they need a restart. No servers needed. A real client goes there and back in M25.

Usage: python3 -m unittest broker.tests.test_dimensions
"""
import json
import pathlib
import tempfile
import unittest

from PIL import Image

from broker import bundles, promote
from broker.gates import GateFailed, static
from orchestrator import world_index

POOL = {"families": {"stone": {"first": 0, "count": 4}, "ore": {"first": 10, "count": 4}, "plant": {"first": 20, "count": 4}}, "item_count": 4, "mobs": {"monster": 1, "creature": 1}}
FLAT = {"type": "minecraft:flat", "settings": {"biome": "minecraft:plains", "layers": [], "structure_overrides": []}}
DATA_FORMAT = 97
OVERWORLD_TYPE = {"ambient_light": 0.0, "has_skylight": True, "attributes": {"minecraft:visual/sky_color": "#78a7ff"}, "height": 384}
PLAINS = {"temperature": 0.8, "downfall": 0.4, "has_precipitation": True, "effects": {"water_color": "#3f76e4"}}


def dimension(**fields):
    return {"display": "Somewhere", "generator": FLAT, **fields}


def features(manifest):
    return {manifest["id"]: {"manifest": manifest, "dir": pathlib.Path("nowhere")}}


def refused(wanted, manifest):
    try:
        static.check_dimensions(features(manifest))
    except GateFailed as error:
        if wanted not in error.message:
            raise AssertionError(f"Refused for the wrong reason: {error.message}") from error
        return
    raise AssertionError(f"This should have been refused for {wanted!r}")


class Slots(unittest.TestCase):
    def test_a_dimension_keeps_its_slot_and_a_new_one_gets_the_next(self):
        ledger = bundles.assign_slots(features({"id": "a", "dimensions": {"one": dimension()}}), bundles.empty_ledger(), POOL)
        self.assertEqual(ledger["dimensions"]["a/one"]["slot"], "d0001")
        ledger = bundles.assign_slots(features({"id": "a", "dimensions": {"two": dimension(), "one": dimension()}}), ledger, POOL)
        self.assertEqual(ledger["dimensions"]["a/one"]["slot"], "d0001")
        self.assertEqual(ledger["dimensions"]["a/two"]["slot"], "d0002")

    def test_a_ledger_from_before_dimensions_can_have_one(self):
        ledger = bundles.assign_slots(features({"id": "a", "dimensions": {"one": dimension()}}), {"blocks": {}, "items": {}, "mobs": {}, "patches": []}, POOL)
        self.assertEqual(ledger["dimensions"]["a/one"]["slot"], "d0001")

    def test_its_land_cant_change_once_its_out(self):
        ledger = bundles.assign_slots(features({"id": "a", "dimensions": {"one": dimension()}}), bundles.empty_ledger(), POOL)
        changed = dimension(generator={**FLAT, "settings": {**FLAT["settings"], "biome": "minecraft:desert"}})
        with self.assertRaisesRegex(bundles.BundleError, "can't change once it's out"):
            bundles.assign_slots(features({"id": "a", "dimensions": {"one": changed}}), ledger, POOL)
        with self.assertRaisesRegex(bundles.BundleError, "can't change once it's out"):
            bundles.assign_slots(features({"id": "a", "dimensions": {"one": dimension(type="minecraft:the_nether")}}), ledger, POOL)

    def test_what_players_read_can_change(self):
        ledger = bundles.assign_slots(features({"id": "a", "dimensions": {"one": dimension()}}), bundles.empty_ledger(), POOL)
        bundles.assign_slots(features({"id": "a", "dimensions": {"one": dimension(display="Somewhere Else", spawn={"x": 4, "z": 4})}}), ledger, POOL)

    def test_a_dimension_stays_declared(self):
        ledger = bundles.assign_slots(features({"id": "a", "dimensions": {"one": dimension()}}), bundles.empty_ledger(), POOL)
        with self.assertRaisesRegex(GateFailed, "no feature declares it"):
            static.check_kept_names(features({"id": "a"}), ledger)


class Rendering(unittest.TestCase):
    def render(self, manifest):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = pathlib.Path(temp.name) / manifest["id"]
        (folder / "assets" / "textures").mkdir(parents=True)
        for name in manifest.get("blocks", {}):
            Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(folder / "assets" / "textures" / f"{name}.png")
        found = {manifest["id"]: {"manifest": manifest, "dir": folder}}
        ledger = bundles.assign_slots(found, bundles.empty_ledger(), POOL)
        out = pathlib.Path(temp.name) / "out"
        bundles.render(found, ledger, out, DATA_FORMAT, vanilla_biome=lambda name: PLAINS, vanilla_type=lambda name: OVERWORLD_TYPE)

        def config(name):
            return json.loads((out / "config" / name).read_text(encoding="utf-8"))
        return config, out, ledger

    def test_it_goes_to_the_server_by_slot_with_nothing_given_away(self):
        config, _, _ = self.render({"id": "a", "dimensions": {"moor": dimension(spawn={"x": 8, "z": -8})}})
        self.assertEqual(config("dimensions.json"), {"gm:d0001": {"type": "minecraft:overworld", "generator": FLAT, "spawn": {"x": 8, "z": -8}}})
        self.assertEqual(config("bindings.json"), {"dimension:a/moor": "d0001"})

    def test_a_vanilla_type_needs_nothing_in_the_data_pack(self):
        _, out, _ = self.render({"id": "a", "dimensions": {"moor": dimension(type="minecraft:the_end")}})
        self.assertFalse((out / "datapack/data/gm/dimension_type").exists())

    def test_its_own_type_starts_from_a_vanilla_one(self):
        config, out, _ = self.render({"id": "a", "dimensions": {"moor": dimension(type={"base": "minecraft:overworld", "ambient_light": 0.5, "attributes": {"minecraft:visual/fog_color": "#000000"}})}})
        self.assertEqual(config("dimensions.json")["gm:d0001"]["type"], "gm:d0001")
        written = json.loads((out / "datapack/data/gm/dimension_type/d0001.json").read_text(encoding="utf-8"))
        self.assertEqual(written["ambient_light"], 0.5)
        self.assertEqual(written["height"], 384)
        self.assertEqual(written["attributes"], {"minecraft:visual/sky_color": "#78a7ff", "minecraft:visual/fog_color": "#000000"})

    def test_a_field_the_game_would_ignore_is_refused(self):
        with self.assertRaisesRegex(bundles.BundleError, "nothing called ambientLight"):
            self.render({"id": "a", "dimensions": {"moor": dimension(type={"base": "minecraft:overworld", "ambientLight": 0.5})}})

    def test_a_biome_made_for_it_doesnt_spread_across_the_overworld(self):
        generator = {"type": "minecraft:noise", "settings": "minecraft:caves", "biome_source": {"type": "minecraft:fixed", "biome": "$biome:moor_land"}}
        config, out, _ = self.render({"id": "a", "biomes": {"moor_land": {"base": "minecraft:plains", "spread": False}, "elsewhere": {"base": "minecraft:plains"}},
                                      "dimensions": {"moor": dimension(generator=generator)}})
        used = config("dimensions.json")["gm:d0001"]["generator"]["biome_source"]["biome"]
        self.assertTrue(used.startswith("gm:b"))
        self.assertTrue((out / f"datapack/data/gm/worldgen/biome/{used.split(':')[1]}.json").exists())
        self.assertEqual([patch["to"] for patch in config("biome_patches.json") if patch["to"] == used], [])
        self.assertEqual(len(config("biome_patches.json")), 1)

    def test_what_belongs_to_it_says_so_and_the_rest_says_nothing(self):
        manifest = {"id": "a", "dimensions": {"moor": dimension()},
                    "blocks": {"stuff": {"family": "ore", "display": "Stuff"}, "bloom": {"family": "plant", "display": "Bloom"}},
                    "ores": [{"id": "there", "block": "stuff", "replaces": ["minecraft:stone"], "veinsPerChunk": 1, "veinSize": 2, "minY": 0, "maxY": 9, "dimension": "$dimension:moor"},
                             {"id": "here", "block": "stuff", "replaces": ["minecraft:stone"], "veinsPerChunk": 1, "veinSize": 2, "minY": 0, "maxY": 9}],
                    "plants": [{"id": "bloom_there", "block": "bloom", "on": ["minecraft:dirt"], "perChunk": 1, "minY": 0, "maxY": 9, "dimension": "$dimension:moor"}],
                    "ruins": {"pile": {"id": "pile_there", "parts": [{"x": 0, "y": 0, "z": 0, "block": "minecraft:stone"}], "on": ["minecraft:dirt"], "replaces": ["minecraft:air"],
                                       "chance": 0.1, "minY": 0, "maxY": 9, "dimension": "$dimension:moor"}}}
        config, _, _ = self.render(manifest)
        ores = {ore["id"]: ore for ore in config("ore_patches.json")}
        self.assertEqual(ores["there"]["dimension"], "gm:d0001")
        self.assertNotIn("dimension", ores["here"])
        self.assertEqual(config("surface_patches.json")[0]["dimension"], "gm:d0001")
        self.assertEqual(config("ruin_patches.json")[0]["dimension"], "gm:d0001")

    def test_an_unknown_dimension_is_refused(self):
        manifest = {"id": "a", "blocks": {"stuff": {"family": "ore", "display": "Stuff"}},
                    "ores": [{"id": "there", "block": "stuff", "replaces": ["minecraft:stone"], "veinsPerChunk": 1, "veinSize": 2, "minY": 0, "maxY": 9, "dimension": "$dimension:nowhere"}]}
        with self.assertRaisesRegex(bundles.BundleError, "unknown dimension"):
            self.render(manifest)


class Gates(unittest.TestCase):
    def test_a_good_one_is_fine(self):
        static.check_dimensions(features({"id": "a", "dimensions": {"moor": dimension(type={"base": "minecraft:the_end"}, spawn={"x": 1, "z": 2})}}))

    def test_it_needs_a_name(self):
        refused("needs a \"display\"", {"id": "a", "dimensions": {"moor": {"generator": FLAT}}})

    def test_only_generators_that_make_land(self):
        refused("generator", {"id": "a", "dimensions": {"moor": dimension(generator={"type": "minecraft:debug"})}})
        refused("generator", {"id": "a", "dimensions": {"moor": {"display": "Somewhere"}}})

    def test_a_biome_has_to_exist(self):
        refused("no feature declares", {"id": "a", "dimensions": {"moor": dimension(generator={**FLAT, "settings": {"biome": "$biome:nothing"}})}})

    def test_only_types_it_can_start_from(self):
        refused("\"type\"", {"id": "a", "dimensions": {"moor": dimension(type="minecraft:nowhere")}})
        refused("\"type\"", {"id": "a", "dimensions": {"moor": dimension(type={"ambient_light": 1})}})

    def test_a_spawn_is_a_place(self):
        refused("\"spawn\"", {"id": "a", "dimensions": {"moor": dimension(spawn=[0, 0])}})

    def test_only_so_many_can_be_open(self):
        refused("the limit is", {"id": "a", "dimensions": {f"d{index}": dimension() for index in range(static.MOST_DIMENSIONS + 1)}})


class Restarts(unittest.TestCase):
    def tier(self, before, after):
        """What a release needs if only these files under its data pack and config changed."""
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            old, new = root / "old", root / "new"
            for folder, files in ((old / "content", before), (new, after)):
                (folder / "config").mkdir(parents=True)
                for name, text in files.items():
                    (folder / name).parent.mkdir(parents=True, exist_ok=True)
                    (folder / name).write_text(text, encoding="utf-8")
            saved = (promote.runtime.HISTORY, promote.runtime.load_state)
            promote.runtime.HISTORY, promote.runtime.load_state = root, lambda: {"current": "old"}
            try:
                return promote.choose_tier(new, [])
            finally:
                promote.runtime.HISTORY, promote.runtime.load_state = saved

    def test_one_that_needs_nothing_new_has_no_restart(self):
        self.assertEqual(self.tier({"config/dimensions.json": "{}"}, {"config/dimensions.json": "{\"gm:d0001\": {}}"}), "T2")

    def test_its_own_type_has_one(self):
        self.assertEqual(self.tier({}, {"datapack/data/gm/dimension_type/d0001.json": "{}"}), "T3")

    def test_its_own_biome_has_one(self):
        self.assertEqual(self.tier({}, {"datapack/data/gm/worldgen/biome/b1.json": "{}"}), "T3")


class Guide(unittest.TestCase):
    def test_players_and_the_voices_hear_about_it_by_name(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp) / "mods" / "genesis" / "features"
            (folder / "a").mkdir(parents=True)
            manifest = {"id": "a", "summary": "A place.", "dimensions": {"moor": dimension(display="The Moor")},
                        "blocks": {"stuff": {"family": "ore", "display": "Stuff"}},
                        "ores": [{"id": "there", "block": "stuff", "replaces": ["minecraft:stone"], "veinsPerChunk": 1, "veinSize": 2, "minY": 0, "maxY": 9, "dimension": "$dimension:moor"}]}
            (folder / "a" / "feature.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertIn("The Moor", world_index.player_index(folder))
            entry = world_index.player_entry(folder, "a")
            self.assertIn("The Moor: a dimension of its own", entry)
            self.assertIn("Stuff: ore veins, Y 0 to 9, in The Moor", entry)


if __name__ == "__main__":
    unittest.main()
