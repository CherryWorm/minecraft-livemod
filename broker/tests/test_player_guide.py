"""What the voices are told about the world, so they can give real answers."""
import json
import pathlib
import tempfile
import unittest

from orchestrator import world_index

MOSS = {
    "summary": "Glow Moss grows in caves. It feeds $item:lamp/lantern. It leads to atmospheric machines later.",
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
        self.guide = world_index.player_entry(self.features, "moss")

    def test_it_uses_the_names_players_see(self):
        self.assertNotIn("$", self.guide)
        self.assertNotIn("minecraft:", self.guide)
        self.assertIn("It feeds Tide Lantern.", self.guide)
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

    def test_what_is_still_to_come_is_not_in_it(self):
        self.assertNotIn("atmospheric", self.guide)
        self.assertNotIn("atmospheric", world_index.player_index(self.features))

    def test_the_index_has_a_line_for_everything_with_the_names_players_see(self):
        index = world_index.player_index(self.features)
        self.assertEqual(len(index.splitlines()), 2)
        self.assertIn("- lamp: A lantern. (Tide Lantern)", index)
        self.assertIn("- moss: Glow Moss grows in caves. (Moss Vein, Moss Spore, Moss Mite, moss weald, old camp)", index)

    def test_nothing_ever_falls_off_the_index_however_big_the_world_gets(self):
        for number in range(400):
            (self.features / f"thing{number}").mkdir()
            (self.features / f"thing{number}" / "feature.json").write_text(json.dumps({"summary": "A big one. " + "y" * 90000}), encoding="utf-8")
        index = world_index.player_index(self.features)
        for number in range(400):
            self.assertIn(f"- thing{number}: A big one.", index)
        self.assertLess(len(index), 400 * 40)

    def test_a_long_description_is_shortened_at_a_word(self):
        (self.features / "long").mkdir()
        (self.features / "long" / "feature.json").write_text(json.dumps({"summary": "word " * 100}), encoding="utf-8")
        line = next(line for line in world_index.player_index(self.features).splitlines() if line.startswith("- long"))
        self.assertLess(len(line), world_index.INDEX_DESCRIPTION + 20)
        self.assertTrue(line.endswith("word..."))

    def test_an_entry_can_be_asked_for_by_a_name_players_see(self):
        self.assertIn("A lantern.", world_index.player_entry(self.features, "Tide Lantern"))
        self.assertIn("A lantern.", world_index.player_entry(self.features, " LAMP "))

    def test_asking_for_something_else_reads_nothing(self):
        for wanted in ("moonstone", "../moss", "", None, "moss/feature.json"):
            self.assertIn("nothing by that name", world_index.player_entry(self.features, wanted))

    def test_an_entry_is_never_huge(self):
        (self.features / "big").mkdir()
        (self.features / "big" / "feature.json").write_text(json.dumps({"summary": "z" * 90000}), encoding="utf-8")
        self.assertLessEqual(len(world_index.player_entry(self.features, "big")), world_index.ENTRY_LIMIT)

    def test_an_empty_world_says_so(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(world_index.player_index(pathlib.Path(empty)), "Nothing yet.")


class Plans(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = pathlib.Path(folder.name)
        self.features = root / "mods" / "genesis" / "features"
        (self.features / "vault").mkdir(parents=True)
        (self.features / "vault" / "feature.json").write_text(json.dumps({
            "node": "m_vault",
            "summary": "The Vault, part 1 of Big Storage: a room that holds items. It has no remote access (that's x_launch). It uses m_vault power. More comes later."}), encoding="utf-8")
        (root / "bible").mkdir()
        (root / "bible" / "progression.json").write_text(json.dumps({"nodes": {"m_vault": {}, "x_launch": {}}}), encoding="utf-8")
        self.entry = world_index.player_entry(self.features, "vault")

    def test_that_it_is_one_part_of_something_bigger_is_left_out(self):
        self.assertIn("The Vault: a room that holds items.", self.entry)
        self.assertIn("- vault: The Vault: a room that holds items.", world_index.player_index(self.features))

    def test_a_part_of_the_world_with_nothing_out_is_left_out(self):
        self.assertNotIn("x_launch", self.entry)
        self.assertNotIn("remote access", self.entry)

    def test_a_part_of_the_world_that_is_out_can_stay(self):
        self.assertIn("It uses m_vault power.", self.entry)

    def test_talk_of_later_is_left_out(self):
        self.assertNotIn("More comes", self.entry)


if __name__ == "__main__":
    unittest.main()
