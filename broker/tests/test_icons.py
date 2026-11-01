"""What the bundler makes of how blocks look in an inventory: flat for what isn't a cube, and always placed the way a block is. No servers
needed. A real client looks at these in M23.

Usage: python3 -m unittest broker.tests.test_icons
"""
import json
import pathlib
import tempfile
import unittest

from PIL import Image

from broker import bundles

POOL = {"families": {family: {"first": index * 100, "count": 10} for index, family in enumerate(
    ("stone", "machine", "model", "plant", "glow_plant", "tinted_plant", "crop", "connected", "cutout"))}, "item_count": 4, "mobs": {"monster": 1, "creature": 1}}
DATA_FORMAT = 97


class Icons(unittest.TestCase):
    def render(self, blocks, models=None):
        """Renders one feature with these blocks, and returns a way to read its pack's files, or None for one it doesn't have."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = pathlib.Path(temp.name) / "icons"
        textures = folder / "assets" / "textures"
        textures.mkdir(parents=True)
        for name, block in blocks.items():
            Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(textures / f"{block.get('texture', name)}.png")
            if block["family"] == "model":
                (folder / "assets" / "models").mkdir(exist_ok=True)
                (folder / "assets" / "models" / f"{block['model']}.bbmodel").write_text("{}", encoding="utf-8")
        for name, model in (models or {}).items():
            (folder / "assets" / "models").mkdir(exist_ok=True)
            (folder / "assets" / "models" / f"{name}.json").write_text(json.dumps(model), encoding="utf-8")
        manifest = {"id": "icons", "blocks": {name: {"display": name, **block} for name, block in blocks.items()}}
        features = {"icons": {"manifest": manifest, "dir": folder}}
        ledger = bundles.assign_slots(features, bundles.empty_ledger(), POOL)
        out = pathlib.Path(temp.name) / "out"
        bundles.render(features, ledger, out, DATA_FORMAT)

        def read(name, kind):
            slot = ledger["blocks"][f"icons/{name}"]["slot"]
            path = out / "pack" / "assets" / "gm" / kind.format(slot=slot)
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return read, out, ledger

    def test_what_isnt_a_cube_has_a_flat_picture(self):
        read, out, ledger = self.render({
            "press": {"family": "model", "model": "press", "texture": "press_icon"},
            "flower": {"family": "plant"},
            "lit_flower": {"family": "glow_plant"},
            "fern": {"family": "tinted_plant"},
            "wheat": {"family": "crop"},
        })
        for name in ("press", "flower", "lit_flower", "fern", "wheat"):
            slot = ledger["blocks"][f"icons/{name}"]["slot"]
            definition = read(name, "items/{slot}.json")
            self.assertEqual(definition["model"]["model"], f"gm:item/{slot}", name)
            model = read(name, "models/item/{slot}.json")
            self.assertEqual(model, {"parent": "minecraft:item/generated", "textures": {"layer0": f"gm:item/{slot}"}}, name)
            self.assertTrue((out / "pack" / "assets" / "gm" / "textures" / "item" / f"{slot}.png").exists(), name)

    def test_a_plant_coloured_by_its_biome_is_coloured_when_held_too(self):
        read, _, _ = self.render({"fern": {"family": "tinted_plant"}, "flower": {"family": "plant"}})
        self.assertEqual(read("fern", "items/{slot}.json")["model"]["tints"][0]["type"], "minecraft:grass")
        self.assertNotIn("tints", read("flower", "items/{slot}.json")["model"])

    def test_a_plant_still_grows_as_a_cross(self):
        read, _, ledger = self.render({"flower": {"family": "plant"}})
        slot = ledger["blocks"]["icons/flower"]["slot"]
        self.assertEqual(read("flower", "models/block/{slot}.json"), {"parent": "minecraft:block/cross", "textures": {"cross": f"gm:block/{slot}"}})

    def test_a_cube_keeps_its_block_model_as_its_icon(self):
        read, _, _ = self.render({"wall": {"family": "stone"}, "leaves": {"family": "cutout"}, "kiln": {"family": "machine"}})
        for name in ("wall", "leaves", "kiln"):
            self.assertIsNone(read(name, "items/{slot}.json"), name)
            self.assertEqual(read(name, "models/block/{slot}.json")["parent"], "minecraft:block/cube_all", name)

    def test_a_lit_cube_sits_in_an_inventory_like_any_block(self):
        read, _, _ = self.render({"lamp": {"family": "stone", "emissive": True}})
        model = read("lamp", "models/block/{slot}.json")
        self.assertEqual(model["parent"], "minecraft:block/block")
        self.assertEqual(model["elements"][0]["light_emission"], bundles.LIGHT_EMISSION_FULL)

    def test_a_features_own_model_sits_like_a_block_unless_it_says_otherwise(self):
        elements = [{"from": [0, 0, 0], "to": [16, 8, 16], "faces": {"up": {"texture": "#all"}}}]
        read, _, _ = self.render({"slab": {"family": "stone"}, "thing": {"family": "stone"}}, {
            "slab": {"elements": elements, "textures": {"all": "gm:block/x"}},
            "thing": {"parent": "minecraft:block/cube_all", "textures": {"all": "gm:block/x"}},
        })
        self.assertEqual(read("slab", "models/block/{slot}.json")["parent"], "minecraft:block/block")
        self.assertEqual(read("thing", "models/block/{slot}.json")["parent"], "minecraft:block/cube_all")


if __name__ == "__main__":
    unittest.main()
