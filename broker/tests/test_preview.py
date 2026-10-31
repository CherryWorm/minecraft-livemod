#!/usr/bin/env python3
"""The art preview and the vanilla textures it reads, on made-up files. Needs no game, and runs in the agent image."""
import ast
import json
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

import numpy as np
from PIL import Image

from assetkit import bbmodel, textures as tx
from broker import reference_textures
from orchestrator import preview

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def solid(colour):
    return Image.new("RGBA", (16, 16), tuple(colour) + (255,))


def noise(seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray(np.dstack([rng.integers(0, 255, (16, 16, 3), dtype=np.uint8), np.full((16, 16), 255, dtype=np.uint8)]))


def checks(dark=20, light=235):
    """Grey, so saturation stays out of it, with as much contrast as a block can have."""
    ys, xs = np.mgrid[0:16, 0:16]
    v = np.where((xs + ys) % 2 == 0, dark, light).astype(np.uint8)
    return Image.fromarray(np.dstack([v, v, v, np.full_like(v, 255)]))


def colours_in(img):
    return set(map(tuple, np.asarray(img.convert("RGB")).reshape(-1, 3).tolist()))


class PreviewCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.out = self.root / "out" / "preview.png"
        self.refs = self.root / "refs"
        for name, img in (("block/stone", tx.stone(seed=1)), ("block/deepslate", tx.stone((76, 76, 84), seed=2, style="deepslate")),
                          ("block/oak_planks", tx.planks()), ("block/iron_block", tx.metal("#d8d8d8")),
                          ("block/grass_block_top", solid((201, 201, 201))), ("block/oak_leaves", tx.leaves((180, 180, 180))),
                          ("item/iron_ingot", tx.ingot("#123456")), ("item/iron_pickaxe", tx.pickaxe("#c0c0c0")),
                          ("item/apple", tx.food("fruit", "#ce3e36"))):
            path = self.refs / f"{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path)

    def feature(self, manifest, textures=(), name="thing"):
        folder = self.root / name
        (folder / "assets" / "textures").mkdir(parents=True, exist_ok=True)
        (folder / "feature.json").write_text(json.dumps(manifest) if isinstance(manifest, dict) else manifest, encoding="utf-8")
        for texture, img in dict(textures).items():
            img.save(folder / "assets" / "textures" / f"{texture}.png")
        return folder

    def blocks(self, **blocks):
        """A feature with one block per argument, named after it, given as (family, image)."""
        manifest = {"id": "thing", "blocks": {name: {"family": family, "display": name.title()} for name, (family, _) in blocks.items()}}
        return self.feature(manifest, {name: img for name, (_, img) in blocks.items()})

    def render(self, folder, references="default"):
        result = preview.render(folder, self.out, self.refs if references == "default" else references)
        self.assertEqual(result["path"], str(self.out))
        with Image.open(self.out) as image:
            self.assertEqual(image.format, "PNG")
            image.verify()
        return result

    def image(self):
        return Image.open(self.out).convert("RGB")

    def notes_about(self, result, *words):
        return [note for note in result["notes"] if all(word in note for word in words)]


class Rendering(PreviewCase):
    def test_everything_at_once(self):
        ore = tx.ore("#e8742c", seed=1)
        ingot = tx.ingot("#a03070")
        manifest = {"id": "thing",
                    "blocks": {"ember_ore": {"family": "ore", "display": "Ember Ore", "texture": "ore_art"},
                               "deep_ember": {"family": "deep_ore", "display": "Deep Ember"},
                               "ember_block": {"family": "metal", "display": "Block of Ember"},
                               "ember_wood": {"family": "wood", "display": "Emberwood"},
                               "ember_soil": {"family": "soil", "display": "Ember Soil"},
                               "ember_lamp": {"family": "glow", "display": "Ember Lamp"},
                               "ember_forge": {"family": "machine", "display": "Ember Forge"},
                               "ember_leaf": {"family": "cutout", "display": "Ember Leaf"},
                               "ember_cap": {"family": "plant", "display": "Ember Cap"},
                               "ember_grass": {"family": "tinted_plant", "display": "Ember Grass"}},
                    "items": {"ember_ingot": {"display": "Ember Ingot", "texture": "ingot_art"},
                              "ember_pick": {"display": "Ember Pick", "handheld": True},
                              "ember_fruit": {"display": "Ember Fruit", "components": {"minecraft:food": {"nutrition": 2}}}},
                    "mobs": {"husk": {"display": "Ember Husk", "model": "husk"}}}
        folder = self.feature(manifest, {
            "ore_art": ore, "deep_ember": tx.ore("#e8742c", base="deepslate", seed=2), "ember_block": tx.metal("#e8742c"),
            "ember_wood": tx.planks("#8a5040"), "ember_soil": tx.soil("#704030"), "ember_lamp": tx.glow("#ffc45c"),
            "ember_forge": tx.machine("front"), "ember_leaf": tx.leaves("#a06030"), "ember_cap": tx.plant("mushroom", "#d04030"),
            "ember_grass": tx.plant("grass", (150, 150, 150), (150, 150, 150)), "ingot_art": ingot,
            "ember_pick": tx.pickaxe("#e8742c"), "ember_fruit": tx.food("fruit", "#e0a030")})
        (folder / "assets" / "models").mkdir()
        bbmodel.save(bbmodel.slime("husk", size=8, translucent=False, seed=1), folder / "assets" / "models" / "husk.bbmodel")

        with mock.patch.object(preview, "_text", wraps=preview._text) as text:
            result = self.render(folder)
        drawn = " | ".join(call.args[2] for call in text.call_args_list)
        for name in ("Ember Ore", "Deep Ember", "Block of Ember", "Ember Cap", "Ember Ingot", "Ember Fruit", "Ember Husk"):
            self.assertIn(name, drawn)
        self.assertNotIn("ember_ore", drawn, "labels use display names, not ids")

        shown = colours_in(self.image())
        self.assertLessEqual(colours_in(ore), shown, "the new texture is there, unscaled in colour")
        self.assertLessEqual(colours_in(tx.stone(seed=1)), shown, "and vanilla's rock around it")
        self.assertLessEqual(colours_in(ingot) - {(0, 0, 0)}, shown)
        self.assertLessEqual(colours_in(tx.ingot("#123456")) - {(0, 0, 0)}, shown, "and the vanilla item beside it")
        self.assertEqual(self.notes_about(result, "No vanilla"), [])

    def test_fixture_manifest_with_generated_art(self):
        manifest = (FIXTURES / "ember" / "feature.json").read_text(encoding="utf-8")
        folder = self.feature(manifest, {"ember_ore": tx.ore("#e8742c", seed=1), "ember_block": tx.metal("#e8742c"), "ember": tx.gem("#e8742c")})
        result = self.render(folder)
        self.assertEqual(self.notes_about(result, "missing"), [])

    def test_animated_strip_shows_its_first_frame(self):
        first, later = (10, 200, 30), (200, 10, 30)
        folder = self.feature({"blocks": {"lamp": {"family": "glow", "display": "Lamp"}}})
        tx.save_animated([solid(first), solid(later), solid(later)], folder / "assets" / "textures" / "lamp.png", frametime=3)
        result = self.render(folder)
        shown = colours_in(self.image())
        self.assertIn(first, shown)
        self.assertNotIn(later, shown)
        self.assertEqual(self.notes_about(result, "mcmeta"), [])

    def test_strip_without_mcmeta_is_noted(self):
        strip = Image.new("RGBA", (16, 32), (10, 200, 30, 255))
        result = self.render(self.feature({"items": {"coil": {"display": "Coil"}}}, {"coil": strip}))
        self.assertEqual(len(self.notes_about(result, "Coil", ".mcmeta")), 1)

    def test_tinted_plant_and_vanilla_grass_get_the_biome_colour(self):
        grey = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        grey.paste((150, 150, 150, 255), (6, 4, 10, 16))
        self.render(self.blocks(reed=("tinted_plant", grey)))
        shown = colours_in(self.image())
        self.assertIn(tuple(int(150 * c / 255) for c in preview.GRASS_TINT), shown)
        self.assertIn(tuple(int(201 * c / 255) for c in preview.GRASS_TINT), shown)

    def test_oversized_texture_is_drawn_at_block_size(self):
        self.render(self.blocks(fine=("stone", tx.stone("#807060", seed=1, size=32))))
        with_32 = self.image().size
        self.render(self.blocks(fine=("stone", tx.stone("#807060", seed=1))))
        self.assertEqual(with_32, self.image().size)

    def test_awkward_names_do_not_crash(self):
        manifest = {"blocks": {"a": {"family": "stone", "display": "Sälzstein — 塩石 \U0001f9c2"},
                               "b": {"family": "not_a_family", "display": "Long " * 80},
                               "c": {"family": ["stone"], "display": 7, "texture": ["c"]}},
                    "items": {"d": {"display": "Long " * 80}, "e": {"display": None, "components": "nope", "stats": 3}}}
        result = self.render(self.feature(manifest, {"a": tx.stone(seed=1), "b": tx.stone(seed=2), "d": tx.gem("#40a0e0")}))
        self.assertTrue(self.notes_about(result, "missing"))


class Missing(PreviewCase):
    def test_no_references(self):
        empty = self.root / "empty"
        empty.mkdir()
        for references in (None, self.root / "nowhere", empty):
            folder = self.blocks(ember=("ore", tx.ore("#e8742c", seed=1)))
            result = self.render(folder, references)
            self.assertEqual(len(self.notes_about(result, "No vanilla textures")), 1, references)

    def test_some_references_missing(self):
        result = self.render(self.blocks(ember=("metal", tx.metal("#e8742c"))))
        self.assertEqual(len(self.notes_about(result, "left out", "block/copper_block")), 1)

    def test_nothing_visual(self):
        folder = self.feature({"id": "lorebook", "knowledge": {"a": {"title": "A", "text": "b"}}})
        result = self.render(folder)
        self.assertEqual(len(self.notes_about(result, "Nothing visual")), 1)

    def test_broken_or_absent_feature_json(self):
        for manifest in ("{ not json", "[1, 2]", '{"blocks": 3, "items": ["x"], "mobs": {"y": 1}}'):
            result = self.render(self.feature(manifest))
            self.assertTrue(self.notes_about(result, "Nothing visual"), manifest)
        result = self.render(self.root / "no_such_feature")
        self.assertTrue(self.notes_about(result, "feature.json"))

    def test_missing_and_broken_textures(self):
        folder = self.feature({"id": "thing", "blocks": {"gone": {"family": "stone", "display": "Gone"},
                                                         "torn": {"family": "stone", "display": "Torn"}},
                               "items": {"lost": {"display": "Lost"}}})
        (folder / "assets" / "textures" / "torn.png").write_text("this isn't a picture", encoding="utf-8")
        result = self.render(folder)
        for label, word in (("Gone", "missing"), ("Torn", "can't be read"), ("Lost", "missing")):
            self.assertEqual(len(self.notes_about(result, label, word)), 1, result["notes"])
        self.assertEqual(self.notes_about(result, "saturation") + self.notes_about(result, "contrast"), [],
                         "the placeholder isn't the block's art, so it isn't measured")
        self.assertIn((248, 0, 248), colours_in(self.image()))

    def test_missing_and_broken_models(self):
        folder = self.feature({"id": "thing", "mobs": {"a": {"display": "Gone Mob", "model": "gone"}, "b": {"display": "Torn Mob", "model": "torn"}}})
        (folder / "assets" / "models").mkdir()
        (folder / "assets" / "models" / "torn.bbmodel").write_text('{"elements": [{}]}', encoding="utf-8")
        result = self.render(folder)
        self.assertEqual(len(self.notes_about(result, "Gone Mob", "missing")), 1)
        self.assertEqual(len(self.notes_about(result, "Torn Mob", "can't be drawn")), 1)

    def test_art_nothing_uses_is_noted(self):
        folder = self.feature({"items": {"used": {"display": "Used"}}}, {"used": tx.gem("#40a0e0"), "spare": tx.gem("#a040e0")})
        result = self.render(folder)
        self.assertEqual(len(self.notes_about(result, "never reach the game", "spare.png")), 1)
        self.assertEqual(self.notes_about(result, "used.png"), [])

    def test_custom_model_is_noted(self):
        folder = self.blocks(odd=("stone", tx.stone("#807060", seed=1)))
        (folder / "assets" / "models").mkdir()
        (folder / "assets" / "models" / "odd.json").write_text("{}", encoding="utf-8")
        self.assertEqual(len(self.notes_about(self.render(folder), "Odd", "custom model")), 1)


class Notes(PreviewCase):
    def test_block_identical_to_vanilla(self):
        same = Image.open(self.refs / "block" / "oak_planks.png").convert("RGBA")
        result = self.render(self.blocks(copy=("wood", same)))
        self.assertEqual(len(self.notes_about(result, "Copy", "vanilla oak_planks", "nearly the same")), 1, result["notes"])

    def test_block_unlike_vanilla_has_no_such_note(self):
        result = self.render(self.blocks(azure=("wood", tx.planks("#4060c0"))))
        self.assertEqual(self.notes_about(result, "nearly the same"), [], result["notes"])

    def test_vanilla_tint_counts_when_comparing(self):
        """The grass file is grey, but players see it green, so green is what could be confused with it."""
        green = solid(tuple(int(201 * c / 255) for c in preview.GRASS_TINT))
        result = self.render(self.blocks(turf=("soil", green)))
        self.assertEqual(len(self.notes_about(result, "Turf", "vanilla grass_block_top")), 1, result["notes"])
        result = self.render(self.blocks(ash=("soil", solid((201, 201, 201)))))
        self.assertEqual(self.notes_about(result, "vanilla grass_block_top"), [], result["notes"])

    def test_two_blocks_in_the_feature_alike(self):
        result = self.render(self.blocks(one=("metal", solid((200, 40, 90))), two=("metal", solid((203, 42, 88)))))
        self.assertEqual(len(self.notes_about(result, "One and Two", "nearly the same")), 1, result["notes"])
        result = self.render(self.blocks(one=("metal", solid((200, 40, 90))), two=("metal", solid((40, 200, 90)))))
        self.assertEqual(self.notes_about(result, "One and Two"), [], result["notes"])

    def test_ores_only_answer_to_ores(self):
        ore = tx.ore("#b080d0", seed=1)
        rock = tx.stone(seed=1)
        self.assertLess(preview._distance(preview._surface(ore), preview._surface(rock)), preview.SAME_COLOUR, "mostly rock, like any ore")
        result = self.render(self.blocks(lilac=("ore", ore), plain=("stone", tx.stone("#807060", seed=1))))
        self.assertEqual(self.notes_about(result, "Lilac", "nearly the same"), [], result["notes"])
        result = self.render(self.blocks(lilac=("ore", ore), grey=("stone", rock)))
        self.assertEqual(self.notes_about(result, "Lilac and Grey"), [], "an ore in its own rock is how ores look")
        ore.save(self.refs / "block" / "copper_ore.png")
        result = self.render(self.blocks(lilac=("ore", ore)))
        self.assertEqual(len(self.notes_about(result, "Lilac", "vanilla copper_ore")), 1, result["notes"])
        result = self.render(self.blocks(lilac=("ore", ore), other=("ore", tx.ore("#b080d0", seed=1))))
        self.assertEqual(len(self.notes_about(result, "Lilac and Other")), 1, result["notes"])

    def test_too_many_colours(self):
        result = self.render(self.blocks(loud=("stone", noise())))
        self.assertEqual(len(self.notes_about(result, "Loud", "colours", "over the limit")), 1, result["notes"])
        result = self.render(self.blocks(quiet=("stone", tx.stone("#807060", seed=1))))
        self.assertEqual(self.notes_about(result, "over the limit"), [], result["notes"])
        folder = self.feature({"items": {"loud": {"display": "Loud Item"}}}, {"loud": noise()})
        self.assertEqual(len(self.notes_about(self.render(folder), "Loud Item", "over the limit")), 1)

    def test_saturated_rock(self):
        result = self.render(self.blocks(rose=("stone", tx.stone("#d0407a", seed=1))))
        self.assertEqual(len(self.notes_about(result, "Rose", "saturation", "vanilla stone")), 1, result["notes"])
        result = self.render(self.blocks(rose=("deep_ore", tx.stone("#d0407a", seed=1))))
        self.assertEqual(len(self.notes_about(result, "Rose", "saturation", "vanilla deepslate")), 1, result["notes"])

    def test_colourful_flecks_and_colourful_wood_are_fine(self):
        result = self.render(self.blocks(ember=("ore", tx.ore("#e8742c", seed=1)), azure=("wood", tx.planks("#2050d0"))))
        self.assertEqual(self.notes_about(result, "saturation"), [], result["notes"])

    def test_high_contrast(self):
        result = self.render(self.blocks(harsh=("stone", checks())))
        self.assertEqual(len(self.notes_about(result, "Harsh", "contrast", "vanilla stone")), 1, result["notes"])

    def test_frames_on_purpose_are_fine(self):
        result = self.render(self.blocks(plate=("metal", checks()), forge=("machine", checks(25, 230)), lamp=("glow", checks(30, 225))))
        self.assertEqual(self.notes_about(result, "contrast"), [], result["notes"])

    def test_plants_are_not_surfaces(self):
        result = self.render(self.blocks(rose=("plant", tx.plant("flower", "#ff2060", seed=1))))
        self.assertEqual(self.notes_about(result, "saturation") + self.notes_about(result, "contrast"), [], result["notes"])

    def test_nothing_to_measure_against_without_references(self):
        result = self.render(self.blocks(rose=("stone", tx.stone("#d0407a", seed=1))), None)
        self.assertEqual(self.notes_about(result, "saturation") + self.notes_about(result, "nearly the same"), [])


class ItemPeers(unittest.TestCase):
    def test_comparable_vanilla_items(self):
        for name, item, peer in (("tin_ingot", {}, "iron_ingot"), ("tin_pick", {}, "iron_pickaxe"), ("tide_berry", {}, "apple"),
                                 ("oddment", {"components": {"minecraft:food": {}}}, "apple"), ("oddment", {"display": "Sun Blade"}, "iron_sword"),
                                 ("ember_plate", {"stats": {"slot": "chest"}}, "iron_helmet"), ("oddment", {"handheld": True}, "iron_pickaxe"),
                                 ("capstone", {}, "iron_ingot")):
            self.assertIn(peer, preview._item_peers(name, item), name)


class References(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.jar = self.root / "client.jar"
        with zipfile.ZipFile(self.jar, "w") as jar:
            jar.writestr("assets/minecraft/textures/block/stone.png", b"stone bytes")
            jar.writestr("assets/minecraft/textures/item/apple.png", b"apple bytes")
            jar.writestr("assets/minecraft/textures/block/tnt_side.png", b"not on the list")
            jar.writestr("net/minecraft/Main.class", b"not a texture")
        self.target = self.root / "deep" / "refs"

    def test_copies_only_what_is_listed(self):
        result = reference_textures.extract(self.jar, self.target)
        self.assertEqual((self.target / "block" / "stone.png").read_bytes(), b"stone bytes")
        self.assertEqual((self.target / "item" / "apple.png").read_bytes(), b"apple bytes")
        self.assertEqual(sorted(result["copied"]), ["block/stone.png", "item/apple.png"])
        written = sorted(path.relative_to(self.target).as_posix() for path in self.target.rglob("*") if path.is_file())
        self.assertEqual(written, ["block/stone.png", "item/apple.png"])
        self.assertIn("block/deepslate.png", result["missing"])

    def test_skips_files_already_there(self):
        reference_textures.extract(self.jar, self.target)
        (self.target / "block" / "stone.png").write_bytes(b"kept")
        result = reference_textures.extract(self.jar, self.target)
        self.assertEqual((self.target / "block" / "stone.png").read_bytes(), b"kept")
        self.assertEqual(result["copied"], [])
        self.assertEqual(sorted(result["skipped"]), ["block/stone.png", "item/apple.png"])

    def test_jar_is_not_needed_once_everything_is_there(self):
        names = [f"block/{name}" for name in reference_textures.BLOCKS] + [f"item/{name}" for name in reference_textures.ITEMS]
        for name in names:
            path = self.target / f"{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        result = reference_textures.extract(self.root / "no_such.jar", self.target)
        self.assertEqual(len(result["skipped"]), len(names))

    def test_a_half_written_jar_is_reported_not_raised(self):
        self.jar.write_bytes(b"PK not really a zip")
        result = reference_textures.extract(self.jar, self.target)
        self.assertEqual(result["copied"], [])
        self.assertEqual(len(result["missing"]), len(reference_textures.BLOCKS) + len(reference_textures.ITEMS))

    def test_preview_reads_what_extract_writes(self):
        buffer = self.root / "stone.png"
        stone = tx.stone(seed=3)
        stone.save(buffer)
        with zipfile.ZipFile(self.jar, "a") as jar:
            jar.writestr("assets/minecraft/textures/block/deepslate.png", buffer.read_bytes())
        reference_textures.extract(self.jar, self.target)
        (self.target / "block" / "stone.png").unlink()  # the fake bytes from setUp aren't a picture
        (self.target / "item" / "apple.png").unlink()
        folder = self.root / "feature"
        (folder / "assets" / "textures").mkdir(parents=True)
        (folder / "feature.json").write_text(json.dumps({"blocks": {"x": {"family": "deep_ore", "display": "X"}}}), encoding="utf-8")
        tx.ore("#e8742c", base="deepslate", seed=1).save(folder / "assets" / "textures" / "x.png")
        out = self.root / "out.png"
        preview.render(folder, out, self.target)
        self.assertLessEqual(colours_in(stone), colours_in(Image.open(out)), "deepslate from the jar surrounds the block")


class Imports(unittest.TestCase):
    def imported(self, module):
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        return names

    def test_preview_can_run_in_the_agent_container(self):
        self.assertLessEqual(self.imported(preview) - set(sys.stdlib_module_names), {"numpy", "PIL", "assetkit"})

    def test_reference_textures_is_standard_library_only(self):
        self.assertLessEqual(self.imported(reference_textures), set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
