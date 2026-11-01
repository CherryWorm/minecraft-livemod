"""What the sidebar says about what's being built. Everyone can read it, so nothing that isn't out yet can get through."""
import unittest

from orchestrator import feedback

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
