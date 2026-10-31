"""What the voices are told about the world, so they can give real answers."""
import json
import pathlib
import tempfile
import unittest

from orchestrator import world_index

MOSS = {
    "summary": "Glow Moss grows in caves. It feeds $item:lamp/lantern and later atmospheric machines.",
    "items": {"spore": {"display": "Moss Spore"}},
    "blocks": {"moss_ore": {"display": "Moss Vein", "tool_level": "iron", "drops": {"item": "$item:spore"}}},
    "ores": [{"block": "moss_ore", "replaces": ["minecraft:stone", "minecraft:tuff"], "minY": -20, "maxY": 40, "biomes": ["minecraft:lush_caves"]}],
    "mobs": {"mite": {"display": "Moss Mite", "behaviour": "skittish", "drops": {"item": "$item:spore"}, "spawn": {"minY": -40, "maxY": 10, "underground": True}}},
    "plants": [{"block": "moss_ore", "perChunk": 2, "biomes": ["minecraft:taiga"]}],
    "ruins": {"old_camp": {"chance": 0.001, "minY": 50, "maxY": 140, "underground": False, "biomes": ["minecraft:desert"], "parts": [{"x": 1}],
                           "loot": {"pools": [{"entries": [{"name": "$item:spore"}, {"name": "$item:lamp/lantern"}, {"name": "$item:spore"}]}]}}},
    "biomes": {"moss_weald": {}},
    "recipes": {
        "shaped": {"mode": "open", "json": {"type": "minecraft:crafting_shaped", "pattern": ["SS", "I "], "key": {"S": "$item:spore", "I": "minecraft:iron_ingot"}, "result": {"id": "$item:lamp/lantern"}}},
        "smelted": {"mode": "known", "route": "moss_lore", "json": {"type": "minecraft:smelting", "ingredient": "$item:spore", "result": {"id": "minecraft:copper_nugget"}}},
        "guess": {"mode": "guessable", "machine": "$block:moss_ore", "inputs": [{"item": "minecraft:diamond"}], "output": {"item": "$item:spore"}},
        "pressed": {"mode": "known", "route": "moss_lore", "machine": "$block:moss_ore", "inputs": [{"item": "$item:spore"}], "output": {"item": "$item:lamp/lantern"}},
    },
    "knowledge": {"moss_lore": {"title": "Moss Lore", "text": "It likes $item:spore.", "routes": [{"type": "examine", "id": "$block:moss_ore"}, {"type": "obtain", "id": "$item:spore"}]}},
}
LAMP = {"summary": "A lantern.", "items": {"lantern": {"display": "Tide Lantern"}}}


class PlayerGuide(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.features = pathlib.Path(folder.name)
        for name, manifest in (("moss", MOSS), ("lamp", LAMP)):
            (self.features / name).mkdir()
            (self.features / name / "feature.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.guide = world_index.player_guide(self.features)

    def test_it_uses_the_names_players_see(self):
        self.assertNotIn("$", self.guide)
        self.assertNotIn("minecraft:", self.guide)
        self.assertIn("It feeds Tide Lantern and later", self.guide)
        self.assertIn("It likes Moss Spore.", self.guide)

    def test_it_says_where_things_are(self):
        self.assertIn("Moss Vein: ore veins, Y -20 to 40, only in lush caves, in stone, tuff", self.guide)
        self.assertIn("Moss Vein: needs iron tool or better, drops Moss Spore", self.guide)
        self.assertIn("Moss Mite: skittish creature, Y -40 to 10, underground, drops Moss Spore", self.guide)
        self.assertIn("Moss Vein: grows only in taiga", self.guide)
        self.assertIn("site old camp: on the surface, Y 50 to 140, only in desert, about one chunk in 1000, its chest can hold Moss Spore, Tide Lantern", self.guide)
        self.assertIn("biome moss weald", self.guide)

    def test_it_says_how_things_are_made(self):
        self.assertIn("recipe for Tide Lantern: crafting shaped, pattern SS / I , where S is Moss Spore, I is iron ingot", self.guide)
        self.assertIn("recipe for copper nugget: smelting from Moss Spore, once it's been learned", self.guide)
        self.assertIn("recipe for Tide Lantern: made at Moss Vein from Moss Spore, once it's been learned", self.guide)

    def test_it_says_how_things_are_learned(self):
        self.assertIn('to learn "Moss Lore": examine Moss Vein or obtain Moss Spore.', self.guide)

    def test_a_recipe_meant_for_experimenting_stays_that_way(self):
        self.assertIn("worked out by experimenting at Moss Vein", self.guide)
        self.assertNotIn("diamond", self.guide)

    def test_it_never_includes_how_a_site_is_built(self):
        self.assertNotIn('"x"', self.guide)
        self.assertNotIn("parts", self.guide)

    def test_it_stays_a_sensible_size(self):
        (self.features / "big").mkdir()
        (self.features / "big" / "feature.json").write_text(json.dumps({"summary": "x" * (world_index.GUIDE_LIMIT * 2)}), encoding="utf-8")
        self.assertLessEqual(len(world_index.player_guide(self.features)), world_index.GUIDE_LIMIT)

    def test_an_empty_world_says_so(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(world_index.player_guide(pathlib.Path(empty)), "Nothing yet.")


if __name__ == "__main__":
    unittest.main()
