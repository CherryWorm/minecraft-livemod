"""Turning something back into the game's own things isn't a use, and the instant check says so before a reviewer has to."""
import unittest

from broker.gates import advice


def recipe(ingredient, output):
    return {"inputs": [([ingredient], 1)], "outputs": [(output, 1, {})]}


class BackToVanilla(unittest.TestCase):
    def test_something_that_only_turns_into_vanilla_things_is_noticed(self):
        found = advice.only_turns_into_vanilla([recipe("item:mob/grit", "minecraft:iron_nugget"), recipe("item:mob/grit", "minecraft:gravel")])
        self.assertEqual(found, {"item:mob/grit"})

    def test_one_recipe_for_something_of_this_worlds_own_is_enough(self):
        found = advice.only_turns_into_vanilla([recipe("item:mob/grit", "minecraft:iron_nugget"), recipe("item:mob/grit", "item:kiln/plate")])
        self.assertEqual(found, set())

    def test_the_games_own_things_are_not_its_concern(self):
        self.assertEqual(advice.only_turns_into_vanilla([recipe("minecraft:stone", "minecraft:gravel")]), set())


if __name__ == "__main__":
    unittest.main()
