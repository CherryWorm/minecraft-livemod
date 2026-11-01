#!/usr/bin/env python3
"""The Codex is written from what a release contains: everything in it hidden until a player knows it, filed by the progression.

Usage: python3 -m unittest broker.tests.test_guide
"""
import json
import pathlib
import tempfile
import unittest

from broker import bundles, guide
from broker.gates import GateFailed, static

NODES = {
    "e_one": {"stage": "early", "name": "First Node"},
    "e_two": {"stage": "early", "name": "Second Node"},
    "m_one": {"stage": "mid", "name": "Later Node"},
}


def entry(key="f/a", text="Some words.", node="e_one", **fields):
    return {"key": key, "title": key.upper(), "text": text, "routes": [], "recipes": [], "node": node, "things": [], "icon": None, **fields}


def categories(files):
    return {path.rsplit("/", 1)[1][:-5]: value for path, value in files.items() if "/categories/" in path}


def entries(files):
    return [value for path, value in files.items() if "/entries/" in path]


class Pages(unittest.TestCase):
    def test_short_text_is_one_page(self):
        self.assertEqual(guide.text_pages("A short note."), ["A short note."])

    def test_long_text_breaks_between_sentences(self):
        sentence = "This sentence is here to take up some of the room on a page. "
        pages = guide.text_pages(sentence * 30)
        self.assertGreater(len(pages), 2)
        for page in pages:
            self.assertTrue(page.endswith("."), page)
            self.assertLessEqual(guide.lines(page), guide.PAGE_LINES)
        self.assertLessEqual(guide.lines(pages[0]), guide.FIRST_PAGE_LINES)
        self.assertEqual(" ".join(pages), (sentence * 30).strip())

    def test_a_sentence_too_long_for_a_page_still_fits(self):
        pages = guide.text_pages("word " * 400)
        self.assertGreater(len(pages), 2)
        self.assertTrue(all(guide.lines(page) <= guide.PAGE_LINES for page in pages))

    def test_paragraphs_take_up_room(self):
        paragraphs = "\n".join(["A short paragraph of a line."] * 10)
        self.assertGreater(len(guide.text_pages(paragraphs)), 1)

    def test_a_new_line_starts_a_paragraph(self):
        self.assertEqual(guide.text_pages("One.\nTwo.\n\nThree."), [f"One.{guide.PARAGRAPH}Two.{guide.PARAGRAPH}Three."])

    def test_text_cant_be_taken_for_a_command(self):
        self.assertNotIn("$(", guide.text_pages("Costs $(lots) today.")[0])


class Book(unittest.TestCase):
    def test_nothing_in_the_book_shows_without_its_flag(self):
        files = guide.book([entry("f/a"), entry("f/b"), entry("f/c", node="m_one")], NODES)
        for value in entries(files):
            self.assertTrue(value["flag"].startswith("k"))
        found = categories(files)
        a, b, c = guide.flag("f/a"), guide.flag("f/b"), guide.flag("f/c")
        self.assertEqual(set(found["s_early"]["flag"][1:].split(",")), {a, b})
        self.assertEqual(set(found["s_mid"]["flag"][1:].split(",")), {c})
        self.assertEqual(set(found[f"n{guide._node_hash('e_one')}"]["flag"][1:].split(",")), {a, b})

    def test_stages_hold_the_nodes_that_have_something(self):
        files = guide.book([entry("f/a")], NODES)
        found = categories(files)
        self.assertEqual(set(found), {"s_early", f"n{guide._node_hash('e_one')}"})
        node = found[f"n{guide._node_hash('e_one')}"]
        self.assertEqual(node["parent"], "companion:s_early")
        self.assertEqual(node["name"], "First Node")
        self.assertEqual(entries(files)[0]["category"], f"companion:n{guide._node_hash('e_one')}")

    def test_a_feature_without_a_node_still_gets_filed(self):
        files = guide.book([entry("f/a", node=None), entry("f/b", node="gone")], NODES)
        self.assertEqual(set(categories(files)), {"other"})
        self.assertEqual({value["category"] for value in entries(files)}, {"companion:other"})

    def test_a_stage_too_big_for_its_page_continues(self):
        nodes = {f"e{index}": {"stage": "early", "name": f"N{index}"} for index in range(guide.MOST_SUBCATEGORIES + 1)}
        files = guide.book([entry(f"f/{index}", node=f"e{index}") for index in range(guide.MOST_SUBCATEGORIES + 1)], nodes)
        found = categories(files)
        self.assertIn("s_early_2", found)
        self.assertEqual(sum(1 for value in found.values() if value.get("parent") == "companion:s_early"), guide.MOST_SUBCATEGORIES)
        self.assertEqual(sum(1 for value in found.values() if value.get("parent") == "companion:s_early_2"), 1)

    def test_recipes_come_after_the_words_two_to_a_page(self):
        files = guide.book([entry(recipes=["gm:r1", "gm:r2", "gm:r3"])], NODES)
        pages = entries(files)[0]["pages"]
        self.assertEqual(pages[0]["type"], "patchouli:text")
        self.assertEqual([page["recipes"] for page in pages[1:]], [["gm:r1", "gm:r2"], ["gm:r3"]])

    def test_an_entry_picks_something_to_show(self):
        def icon(**fields):
            return entries(guide.book([entry(**fields)], NODES))[0]["icon"]

        self.assertEqual(icon(), guide.DEFAULT_ICON)
        self.assertEqual(icon(icon="minecraft:apple"), "minecraft:apple")
        self.assertEqual(icon(icon="gm:i0007"), guide.STAND_IN.format("gm:i0007"))
        self.assertEqual(icon(things=["gm:s0002"]), guide.STAND_IN.format("gm:s0002"))
        # A mob has no item to draw, so this looks past it.
        self.assertEqual(icon(routes=[{"type": "kill", "id": "gm:e0001"}, {"type": "read", "id": "gm:i0003"}], things=["gm:s0002"]), guide.STAND_IN.format("gm:i0003"))


class Release(unittest.TestCase):
    def rendered(self, nodes=NODES):
        manifest = {
            "id": "f", "node": "e_one",
            "items": {"dust": {"display": "Bright Dust"}},
            "knowledge": {"on_dust": {"title": "On Dust", "text": "Grind $item:dust finely.", "routes": [{"type": "obtain", "id": "$item:dust"}]}},
            "recipes": {
                "gem": {"mode": "known", "route": "on_dust", "json": {"type": "minecraft:crafting_shapeless", "ingredients": ["$item:dust"], "result": {"id": "$item:dust"}}},
                "salt": {"mode": "known", "route": "on_dust", "machine": "press", "inputs": [{"item": "$item:dust", "count": 1}], "output": {"item": "$item:dust", "count": 1}},
            },
        }
        root = pathlib.Path(self.folder.name)
        feature = root / "features" / "f"
        (feature / "assets" / "textures").mkdir(parents=True)
        (feature / "assets" / "textures" / "dust.png").write_bytes(b"")
        (feature / "feature.json").write_text(json.dumps(manifest), encoding="utf-8")
        found = bundles.load_features(root / "features")
        ledger = bundles.assign_slots(found, bundles.empty_ledger(), {"families": {}, "item_count": 10, "mobs": {"monster": 1, "creature": 1}})
        bundles.render(found, ledger, root / "out", 1, nodes=nodes)
        return root / "out", ledger

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def page(self, out):
        return json.loads(next((out / "pack" / guide.BOOK / "entries").glob("*.json")).read_text(encoding="utf-8"))

    def test_a_release_writes_its_knowledge_into_the_book(self):
        out, ledger = self.rendered()
        page = self.page(out)
        self.assertEqual(page["name"], "On Dust")
        self.assertEqual(page["pages"][0]["text"], "Grind Bright Dust finely.")
        self.assertEqual(page["icon"], guide.STAND_IN.format("gm:" + ledger["items"]["f/dust"]["slot"]))
        recipes = page["pages"][1]["recipes"]
        self.assertEqual(len(recipes), 2)
        self.assertIn("f/salt", recipes)

    def test_the_server_is_told_what_turns_each_page_on(self):
        out, _ = self.rendered()
        plan = json.loads((out / "config" / "knowledge.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["entries"]["f/on_dust"]["guide"], self.page(out)["flag"])

    def test_the_book_passes_the_check_on_what_a_pack_can_hold(self):
        out, _ = self.rendered()
        static.check_spoilers(out / "pack")
        for path in guide.book([entry(node=None), entry("f/b")], NODES):
            self.assertTrue(static.SAFE_PATH.match(path), path)

    def test_a_bad_icon_is_refused(self):
        feature = {"f": {"manifest": {"knowledge": {"a": {"title": "A", "text": "B", "icon": "gm:i0001", "routes": [{"type": "obtain", "id": "x"}]}}}}}
        with self.assertRaises(GateFailed):
            static.check_knowledge(feature)


if __name__ == "__main__":
    unittest.main()
