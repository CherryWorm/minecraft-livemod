"""What the sidebar says about what's being built. Everyone can read it, so nothing that isn't out yet can get through."""
import unittest
from unittest import mock

from orchestrator import feedback, llm, voice

GRAPH = {"nodes": {"e_one": {"stage": "early"}, "m_one": {"stage": "mid"}, "x_one": {"stage": "end"}}}
FEATURE = {"id": "brass_kiln", "category": "machine", "node": "e_one",
           "spec": "A machine that melts `rune_dust` into plates. Players find the Hollow Forge beneath the hills, near Ashmere."}


class Teasers(unittest.TestCase):
    def test_a_careful_line_is_kept(self):
        self.assertEqual(feedback.safe_teaser("a furnace for mixing metals.", FEATURE), "a furnace for mixing metals")

    def test_nothing_from_its_own_id_or_brief_gets_through(self):
        for text in ("a kiln for metals", "a brass furnace", "made from rune plates", "a machine for dust", "found near ashmere", "a hollow machine"):
            self.assertIsNone(feedback.safe_teaser(text, FEATURE), text)

    def test_anything_like_a_name_is_refused(self):
        self.assertIsNone(feedback.safe_teaser("a furnace called Emberheart", FEATURE))

    def test_the_first_word_can_have_a_capital(self):
        self.assertEqual(feedback.safe_teaser("A furnace for mixing metals", FEATURE), "A furnace for mixing metals")

    def test_too_long_or_empty_is_refused(self):
        self.assertIsNone(feedback.safe_teaser("a very large furnace for mixing many kinds of metals", FEATURE))
        self.assertIsNone(feedback.safe_teaser("", FEATURE))
        self.assertIsNone(feedback.safe_teaser(None, FEATURE))

    def test_formatting_codes_are_taken_out(self):
        self.assertEqual(feedback.safe_teaser("a §kfurnace for metals", FEATURE), "a kfurnace for metals")

    def test_only_saying_what_kind_of_thing_it_is_is_refused(self):
        for text in ("machine", "a machine", "a new machine", "a new kind of tool", "some new building block", "A better item"):
            self.assertIsNone(feedback.safe_teaser(text, FEATURE), text)
        self.assertEqual(feedback.safe_teaser("a new tool for miners", FEATURE), "a new tool for miners")

    def test_a_refusal_says_what_to_change(self):
        self.assertIn("characters", feedback.teaser_problem("a very large furnace for mixing many kinds of metals", FEATURE))
        self.assertIn("Emberheart", feedback.teaser_problem("a furnace called Emberheart", FEATURE))
        self.assertIn("kiln", feedback.teaser_problem("a kiln for metals", FEATURE))
        self.assertIn("what it's for", feedback.teaser_problem("a new machine", FEATURE))
        self.assertIsNone(feedback.teaser_problem("a furnace for mixing metals", FEATURE))


class Writing(unittest.IsolatedAsyncioTestCase):
    def answers(self, *lines):
        return mock.AsyncMock(side_effect=[llm.Result("", {"teaser": line}, "", 0.0, False, "", 0.0) for line in lines])

    async def test_a_refused_line_is_tried_again_knowing_why(self):
        ask = self.answers("a new machine", "a furnace for mixing metals")
        with mock.patch.object(llm, "ask", ask):
            self.assertEqual(await voice.teaser(mock.Mock(), FEATURE, "early game"), "a furnace for mixing metals")
        self.assertIn("what it's for", ask.await_args_list[1].args[2])

    async def test_it_stops_trying_in_the_end(self):
        ask = self.answers(*["a new machine"] * voice.TEASER_TRIES)
        with mock.patch.object(llm, "ask", ask):
            self.assertIsNone(await voice.teaser(mock.Mock(), FEATURE, "early game"))
        self.assertEqual(ask.await_count, voice.TEASER_TRIES)


class Reasons(unittest.TestCase):
    def test_plan_says_the_line_when_there_is_one(self):
        self.assertEqual(feedback.describe({**FEATURE, "teaser": "a furnace for metals"}, GRAPH), "a furnace for metals (early game)")
        self.assertEqual(feedback.describe(FEATURE, GRAPH), "early game machine")

    def test_a_fix_says_what_it_fixes(self):
        self.assertEqual(feedback.fix_reason("a furnace burns fuel twice."), "fixing \"a furnace burns fuel twice\"")

    def test_a_fix_with_a_name_or_nothing_to_say_stays_general(self):
        for title in ("the Hollow Kiln burns fuel twice", "", None, "x" * (feedback.MOST_IN_A_FIX_TITLE + 1)):
            self.assertEqual(feedback.fix_reason(title), "a bug fix")

    def test_a_balance_change_says_what_kind_of_number(self):
        self.assertEqual(feedback.balance_reason("mobs", "spawn.weight"), "a balance change to mobs: spawn weight")
        self.assertEqual(feedback.balance_reason("mobs", "followRange"), "a balance change to mobs: follow range")
        self.assertEqual(feedback.balance_reason("items", "attack_damage"), "a balance change to items: attack damage")
        self.assertEqual(feedback.balance_reason("recipes", "json.result.count"), "a balance change to recipes: result count")


class Lines(unittest.TestCase):
    def test_a_teaser_goes_with_its_stage(self):
        self.assertEqual(feedback.board_line({**FEATURE, "teaser": "a furnace for metals"}, GRAPH), {"text": "a furnace for metals", "tag": "early"})
        self.assertEqual(feedback.board_line({**FEATURE, "node": "x_one", "teaser": "a big fight"}, GRAPH)["tag"], "late")

    def test_without_one_it_says_only_the_category(self):
        self.assertEqual(feedback.board_line(FEATURE, GRAPH), {"text": "machine", "tag": "early"})
        self.assertEqual(feedback.board_line({**FEATURE, "teaser": None}, GRAPH)["text"], "machine")

    def test_a_category_that_isnt_on_the_list_says_nothing(self):
        self.assertEqual(feedback.board_line({**FEATURE, "category": "the Hollow Forge"}, GRAPH)["text"], "something new")

    def test_small_jobs_keep_their_titles_at_a_width_that_fits(self):
        self.assertEqual(feedback.board_line({"small": True, "title": "a minimap"}, GRAPH), {"text": "a minimap", "tag": "small"})
        line = feedback.board_line({"small": True, "title": "fix for the sound the old machine makes when it stops"}, GRAPH)
        self.assertLessEqual(len(line["text"]), feedback.BOARD_WIDTH)
        self.assertTrue(line["text"].endswith("…"))


if __name__ == "__main__":
    unittest.main()
