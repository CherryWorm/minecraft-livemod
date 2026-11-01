#!/usr/bin/env python3
"""The world in another language: what's written into the pack from what's been translated, and that nothing gets worse than English.

Usage: python3 -m unittest broker.tests.test_languages
"""
import json
import pathlib
import re
import tempfile
import unittest

from PIL import Image

from broker import bundles, guide, promote
from broker.gates import GateFailed, advice, static
from orchestrator import wording

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DATA_FORMAT = 90
GERMAN = {
    wording.NAMES: {"Ember Ore": "Gluterz", "Ember": "Glut", "Old Crab": "Alte Krabbe", "On Embers": "Über Glut", "First Node": "Erster Knoten"},
    wording.TEXTS: {
        "Glows in the dark": "Leuchtet im Dunkeln",
        "Burns 50% hotter": "Brennt 50% heißer",
        "You need $item:ember to make it. Look deep.": "Dafür brauchst du $item:ember. Such tief unten.",
        "The block is warm.": "Der Block ist warm.",
        "You have %s of %s.": "Du hast %s von %s.",
        "Kiln": "Brennofen",
        "Cold": "Kalt",
        "Light": "Anzünden und noch viel mehr Worte",
        "Burns one coal": "Verbrennt eine Kohle",
        "Offers": "Angebote",
        "Name it": "Benenne es",
    },
}


def feature(folder, **extra):
    manifest = {
        "id": "ember", "node": "e_one",
        "blocks": {"ember_ore": {"family": "ore", "display": "Ember Ore", "texture": "ember"}},
        "items": {"ember": {"display": "Ember", "texture": "ember", "tooltip": ["Glows in the dark", "Burns 50% hotter", "Not translated yet"]}},
        "knowledge": {"on_embers": {"title": "On Embers", "text": "You need $item:ember to make it. Look deep.", "routes": [{"type": "obtain", "id": "$item:ember"}]}},
        "texts": {"warm": "The block is warm.", "count": "You have %s of %s.", "other": "Nobody has translated this."},
        **extra,
    }
    (folder / "assets" / "textures").mkdir(parents=True)
    (folder / "assets" / "panels").mkdir()
    Image.new("RGBA", (16, 16), (200, 80, 20, 255)).save(folder / "assets" / "textures" / "ember.png")
    (folder / "feature.json").write_text(json.dumps(manifest), encoding="utf-8")


def panel():
    return {"title": "Kiln", "width": 176, "height": 166, "widgets": [
        {"type": "label", "id": "state", "x": 8, "y": 20, "text": "Cold"},
        {"type": "button", "id": "light", "x": 8, "y": 60, "width": 40, "height": 18, "text": "Light", "tooltip": "Burns one coal"},
        {"type": "tabs", "id": "pages", "x": 0, "y": 0, "tabs": [{"id": "offers", "text": "Offers"}]},
        {"type": "text_field", "id": "name", "x": 8, "y": 80, "width": 80, "height": 16, "max_length": 20, "hint": "Name it"},
    ]}


class Codes(unittest.TestCase):
    def test_a_translation_has_to_keep_every_code(self):
        keeps = wording.keeps_codes
        self.assertTrue(keeps("You need $item:ember.", "Dafür brauchst du $item:ember."))
        self.assertFalse(keeps("You need $item:ember.", "Dafür brauchst du Glut."))
        self.assertFalse(keeps("Found in $biome:ash_wastes.", "Zu finden in der Aschewüste."))
        self.assertEqual(wording.CODES.findall("$block:a $item:other/b $mob:c $sound:d $biome:e $dimension:f"), bundles.TOKEN.sub(lambda found: found[0], "$block:a $item:other/b $mob:c $sound:d $biome:e $dimension:f").split(), "the same tokens the pack replaces")
        self.assertFalse(keeps("§7Warm §fnow", "§7Warm jetzt"))
        self.assertFalse(keeps("You have %s of %s.", "Du hast %s."))
        self.assertTrue(keeps("You have %1$s of %2$s.", "Von %2$s hast du %1$s."))
        self.assertFalse(keeps("Read $(br2)this", "Lies das"))
        self.assertFalse(keeps("Ember", ""))
        self.assertFalse(keeps("Ember", None))

    def test_a_percent_in_a_sentence_isnt_a_code(self):
        self.assertTrue(wording.keeps_codes("Burns 50% hotter", "Brennt 50% heißer"))

    def test_anything_much_longer_isnt_a_translation_of_it(self):
        self.assertFalse(wording.keeps_codes("Ember", "word " * 40))

    def test_a_bad_translation_in_the_store_is_never_used(self):
        words = wording.Words("de_de", {wording.NAMES: {}, wording.TEXTS: {"You need $item:ember.": "Du brauchst Glut."}})
        self.assertEqual(words.text("You need $item:ember."), "You need $item:ember.")


class Store(unittest.TestCase):
    def test_it_keeps_what_it_read_and_reads_nothing_as_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            self.assertEqual(wording.read_store(root, "de_de"), {wording.NAMES: {}, wording.TEXTS: {}})
            wording.write_store(root, "de_de", GERMAN)
            self.assertEqual(wording.read_store(root, "de_de"), GERMAN)
            self.assertIn("Über Glut", (root / "bible/lang/de_de.json").read_text(encoding="utf-8"), "readable, for anyone looking at it")

    def test_only_what_a_player_reads_is_asked_about(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary) / "ember"
            folder.mkdir()
            feature(folder, panels={"kiln": panel()})
            found = {(part, english) for part, english, _, _ in wording.wanted_in(folder)}
        self.assertIn((wording.NAMES, "Ember Ore"), found)
        self.assertIn((wording.NAMES, "On Embers"), found)
        self.assertIn((wording.TEXTS, "Burns 50% hotter"), found)
        self.assertIn((wording.TEXTS, "You have %s of %s."), found)
        self.assertIn((wording.TEXTS, "Offers"), found)
        self.assertIn((wording.TEXTS, "Name it"), found)
        self.assertFalse(any(english in ("ember", "ember_ore", "e_one") for _, english in found))


class Files(unittest.TestCase):
    def render(self, **extra):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        features = root / "features"
        (features / "ember").mkdir(parents=True)
        feature(features / "ember", **extra)
        loaded = bundles.load_features(features)
        pool = bundles.read_pool(ROOT)
        ledger = bundles.assign_slots(loaded, bundles.empty_ledger(), pool)
        out = root / "out"
        nodes = {"e_one": {"stage": "early", "name": "First Node"}}
        bundles.render(loaded, ledger, out, DATA_FORMAT, nodes=nodes, languages={"de_de": wording.Words("de_de", GERMAN)})
        return loaded, ledger, out

    def read(self, out, path):
        return json.loads((out / path).read_text(encoding="utf-8"))

    def test_names_go_in_a_language_file_of_their_own_under_the_same_keys(self):
        _, ledger, out = self.render()
        item, block = ledger["items"]["ember/ember"]["slot"], ledger["blocks"]["ember/ember_ore"]["slot"]
        english, german = self.read(out, "pack/assets/gm/lang/en_us.json"), self.read(out, "pack/assets/gm/lang/de_de.json")
        self.assertEqual(english[f"item.gm.{item}"], "Ember")
        self.assertEqual(german[f"item.gm.{item}"], "Glut")
        self.assertEqual(english[f"block.gm.{block}"], "Ember Ore")
        self.assertEqual(german[f"block.gm.{block}"], "Gluterz")

    def test_what_has_no_translation_is_left_to_fall_back(self):
        _, ledger, out = self.render(items={"ember": {"display": "Ember", "texture": "ember"}, "unknown": {"display": "Nothing Known", "texture": "ember"}})
        german = self.read(out, "pack/assets/gm/lang/de_de.json")
        self.assertNotIn(f"item.gm.{ledger['items']['ember/unknown']['slot']}", german)
        self.assertNotIn("Nothing Known", json.dumps(german))

    def test_the_game_reads_its_regional_german_from_the_same_words(self):
        _, _, out = self.render()
        german = self.read(out, "pack/assets/gm/lang/de_de.json")
        for variant in ("de_at", "de_ch"):
            self.assertEqual(self.read(out, f"pack/assets/gm/lang/{variant}.json"), german)
            self.assertTrue(list((out / f"pack/{guide.BOOKS}/{variant}/entries").glob("*.json")))

    def test_a_tooltip_goes_out_as_keys_with_its_english_alongside(self):
        _, ledger, out = self.render()
        item = ledger["items"]["ember/ember"]["slot"]
        lore = self.read(out, "config/item_defaults.json")[f"gm:{item}"]["components"]["minecraft:lore"]
        self.assertEqual(lore[0], {"translate": f"tooltip.gm.{item}.0", "fallback": "Glows in the dark", "italic": False, "color": "gray"})
        english, german = self.read(out, "pack/assets/gm/lang/en_us.json"), self.read(out, "pack/assets/gm/lang/de_de.json")
        self.assertEqual(english[f"tooltip.gm.{item}.0"], "Glows in the dark")
        self.assertEqual(german[f"tooltip.gm.{item}.0"], "Leuchtet im Dunkeln")
        # A percent sign means something in a key's text, and it didn't in what was written.
        self.assertEqual(english[f"tooltip.gm.{item}.1"], "Burns 50%% hotter")
        self.assertEqual(german[f"tooltip.gm.{item}.1"], "Brennt 50%% heißer")
        self.assertEqual(lore[2]["fallback"], "Not translated yet")
        self.assertNotIn(f"tooltip.gm.{item}.2", german)

    def test_a_modules_text_is_under_a_key_that_gives_nothing_away(self):
        _, _, out = self.render()
        key = f"text.gm.{wording.text_id('ember', 'warm')}"
        self.assertEqual(self.read(out, "pack/assets/gm/lang/en_us.json")[key], "The block is warm.")
        self.assertEqual(self.read(out, "pack/assets/gm/lang/de_de.json")[key], "Der Block ist warm.")
        self.assertRegex(key, r"^text\.gm\.t[0-9a-f]{16}$")

    def test_the_codex_has_a_folder_for_each_language_with_the_same_files(self):
        _, ledger, out = self.render()
        english = out / "pack" / guide.BOOKS / "en_us"
        german = out / "pack" / guide.BOOKS / "de_de"
        found = sorted(path.relative_to(english) for path in english.rglob("*.json"))
        self.assertTrue(found)
        self.assertEqual(sorted(path.relative_to(german) for path in german.rglob("*.json")), found)
        page = json.loads(next((german / "entries").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(page["name"], "Über Glut")
        text = " ".join(piece["text"] for piece in page["pages"] if piece["type"] == "patchouli:text")
        self.assertEqual(text, "Dafür brauchst du Glut. Such tief unten.", "with the name in that language, where the token was")
        original = json.loads(next((english / "entries").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(original["name"], "On Embers")
        self.assertIn("You need Ember to make it", original["pages"][0]["text"])
        self.assertEqual({key: page[key] for key in ("flag", "category", "icon")}, {key: original[key] for key in ("flag", "category", "icon")})

    def test_the_codexs_own_categories_are_translated_too(self):
        _, _, out = self.render()
        german = self.read(out, f"pack/{guide.BOOKS}/de_de/categories/s_early.json")
        self.assertEqual(german["name"], "Erste Schritte")
        node = next(path for path in (out / "pack" / guide.BOOKS / "de_de" / "categories").glob("n*.json"))
        self.assertEqual(json.loads(node.read_text(encoding="utf-8"))["name"], "Erster Knoten")
        self.assertIn("Erster Knoten", json.loads(node.read_text(encoding="utf-8"))["description"])
        self.assertEqual(self.read(out, f"pack/{guide.BOOKS}/en_us/categories/s_early.json")["name"], "First Steps")

    def test_a_page_with_no_translation_at_all_isnt_written_twice(self):
        _, _, out = self.render(knowledge={"other": {"title": "Nothing Known", "text": "Nothing known at all.", "routes": [{"type": "obtain", "id": "$item:ember"}]}})
        self.assertFalse(list((out / "pack" / guide.BOOKS / "de_de" / "entries").glob("*.json")))
        self.assertTrue(list((out / "pack" / guide.BOOKS / "en_us" / "entries").glob("*.json")))

    def test_the_server_can_read_what_a_page_says_in_each_language(self):
        _, _, out = self.render()
        flag = guide.flag("ember/on_embers")
        english, german = self.read(out, "pack/assets/gm/lang/en_us.json"), self.read(out, "pack/assets/gm/lang/de_de.json")
        self.assertEqual(english[f"knowledge.gm.{flag}"], "On Embers")
        self.assertEqual(german[f"knowledge.gm.{flag}"], "Über Glut")
        self.assertEqual(german[f"knowledge.gm.{flag}.text"], "Dafür brauchst du Glut. Such tief unten.")

    def test_engine_words_only_go_where_they_have_a_translation(self):
        _, _, out = self.render()
        german = self.read(out, "pack/assets/gm/lang/de_de.json")
        self.assertEqual(german["conduit.read_it"], "[Lesen]")
        self.assertEqual(german["key.companion.guide"], "Kodex öffnen")
        self.assertNotIn("conduit.read_it", self.read(out, "pack/assets/gm/lang/en_us.json"), "English is in the code, for when there's no pack at all")

    def test_a_panel_has_a_file_for_each_language_that_works_the_same(self):
        _, _, out = self.render(panels={"kiln": panel()})
        english, german = self.read(out, "config/panels.json")["ember/kiln"], self.read(out, "config/panels.de_de.json")["ember/kiln"]
        self.assertEqual(english["title"], "Kiln")
        self.assertEqual(german["title"], "Brennofen")
        widgets = {widget["id"]: widget for widget in german["widgets"]}
        self.assertEqual(widgets["state"]["text"], "Kalt")
        self.assertEqual(widgets["pages"]["tabs"][0]["text"], "Angebote")
        self.assertEqual(widgets["name"]["hint"], "Benenne es")
        self.assertEqual(widgets["light"]["tooltip"], "Verbrennt eine Kohle")
        self.assertEqual(json.dumps(english["widgets"]).count("chest_slot"), json.dumps(german["widgets"]).count("chest_slot"))
        strip = lambda rendered: [{key: value for key, value in widget.items() if key not in ("text", "tooltip", "hint", "tabs")} for widget in rendered["widgets"]]
        self.assertEqual(strip(english), strip(german))

    def test_words_too_long_for_a_button_stay_in_english(self):
        _, _, out = self.render(panels={"kiln": panel()})
        german = {widget["id"]: widget for widget in self.read(out, "config/panels.de_de.json")["ember/kiln"]["widgets"]}
        self.assertEqual(german["light"]["text"], "Light")

    def test_the_book_stays_in_english_with_no_words_at_all(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        (root / "features" / "ember").mkdir(parents=True)
        feature(root / "features" / "ember")
        loaded = bundles.load_features(root / "features")
        bundles.render(loaded, bundles.assign_slots(loaded, bundles.empty_ledger(), bundles.read_pool(ROOT)), root / "out", DATA_FORMAT, nodes={})
        self.assertFalse((root / "out/pack/assets/gm/lang/de_de.json").exists())
        self.assertFalse((root / "out" / "pack" / guide.BOOKS / "de_de").exists())

    def test_nothing_in_the_pack_breaks_the_rule_on_meaningless_names(self):
        _, _, out = self.render(panels={"kiln": panel()})
        static.check_spoilers(out / "pack")
        german = out / "pack/assets/gm/lang/de_de.json"
        for path in (out / "pack").rglob("*"):
            self.assertNotIn("ember", path.relative_to(out).as_posix().lower())
        self.assertTrue(german.exists())

    def test_new_words_alone_dont_mean_testing_everything_again(self):
        _, _, out = self.render()
        before = bundles.tree_hash(out, wording.is_translation)
        (out / "pack/assets/gm/lang/de_de.json").write_text("{}", encoding="utf-8")
        (out / "pack" / guide.BOOKS / "de_de" / "new.json").write_text("{}", encoding="utf-8")
        (out / "config/panels.de_de.json").write_text("{}", encoding="utf-8")
        self.assertEqual(bundles.tree_hash(out, wording.is_translation), before)
        (out / "pack/assets/gm/lang/en_us.json").write_text("{}", encoding="utf-8")
        self.assertNotEqual(bundles.tree_hash(out, wording.is_translation), before)

    def test_the_gates_proof_goes_by_the_same_rule(self):
        self.assertIn("is_translation", promote.fingerprint.__code__.co_names)


class EngineWords(unittest.TestCase):
    def test_every_key_the_game_says_has_german(self):
        german = wording.engine_words("de_de", "game")
        said = set()
        for folder in ("mods/conduit/src/main/java", "mods/companion/src/main/java"):
            for path in (ROOT / folder).rglob("*.java"):
                said.update(re.findall(r"\"((?:conduit|companion)\.[a-z_.0-9]+)\"", path.read_text(encoding="utf-8")))
        said.update(re.findall(r"\"(conduit\.[a-z_.0-9]+)\"", (ROOT / "broker/deploy.py").read_text(encoding="utf-8")))
        said = {key for key in said if not key.endswith((".json", ".mixins"))}
        self.assertTrue(said, "the game says something")
        self.assertEqual(sorted(said - set(german)), [])
        self.assertEqual(sorted(key for key in set(german) - said if key.startswith(("conduit.", "companion."))), [], "and nothing's kept that nothing says")

    def test_german_keeps_the_codes_of_what_the_agent_says(self):
        for english, german in wording.engine_words("de_de", "said").items():
            self.assertEqual(sorted(re.findall(r"§.|\{[a-z]+\}", english)), sorted(re.findall(r"§.|\{[a-z]+\}", german)), english)

    def test_the_book_keeps_its_places_for_values(self):
        for english, german in wording.engine_words("de_de", "book").items():
            self.assertEqual(wording.codes(english), wording.codes(german), english)

    def test_what_the_agent_says_goes_by_what_a_game_is_set_to(self):
        line = "§7Sorry, I didn't catch that. Could you say it again?"
        self.assertIn("nicht mitbekommen", wording.said("de_de", line))
        self.assertIn("nicht mitbekommen", wording.said("de_at", line))
        self.assertEqual(wording.said("en_us", line), line)
        self.assertEqual(wording.said("fr_fr", line), line)
        self.assertEqual(wording.said(None, line), line)

    def test_a_line_put_together_from_pieces_comes_out_whole(self):
        said = wording.said("de_de", "§c[Bug]§r §7Thanks. I'm looking into that now, ahead of everything else, and I'll tell you what I find.")
        self.assertEqual(said, "§c[Bug]§r §7Danke. Ich sehe mir das jetzt vor allem anderen an und sage dir, was ich finde.")


class Checks(unittest.TestCase):
    def features(self, text, source=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = pathlib.Path(temporary.name) / "ember"
        code = folder / "server" / "src" / "main" / "java" / "gm" / "feature" / "ember"
        code.mkdir(parents=True)
        if source:
            (code / "EmberModule.java").write_text(source, encoding="utf-8")
        return {"ember": {"manifest": {"id": "ember", "texts": text}, "dir": folder}}

    def test_text_is_names_and_strings(self):
        with self.assertRaises(GateFailed):
            static.check_texts(self.features(["The block is warm."]))
        static.check_texts(self.features({"warm": "The block is warm."}))

    def test_a_place_for_a_value_has_to_be_one_the_game_knows(self):
        with self.assertRaisesRegex(GateFailed, "%s"):
            static.check_texts(self.features({"count": "You have %d of them."}))
        with self.assertRaises(GateFailed):
            static.check_texts(self.features({"count": "Nearly 100%"}))
        static.check_texts(self.features({"count": "%s of %1$s at 100%% and 50% more"}))

    def test_asking_for_a_text_that_isnt_there_is_found_at_once(self):
        with self.assertRaisesRegex(GateFailed, "warmer"):
            static.check_texts(self.features({"warm": "Warm."}, 'player.sendSystemMessage(context.text("warmer"));'))
        with self.assertRaisesRegex(GateFailed, "warmer"):
            static.check_texts(self.features({"warm": "Warm."}, 'panel.setText("state", context.textFor(panel.player(), "warmer"));'))
        static.check_texts(self.features({"warm": "Warm."}, 'player.sendSystemMessage(context.text("warm"));'))
        static.check_texts(self.features({"warm": "Warm."}, 'context.text("warm", "a value"); context.text(name, "a value"); context.text("other/thing");'))

    def test_text_written_into_code_is_pointed_out(self):
        features = self.features({}, 'player.sendSystemMessage(Component.literal("The block is warm."));')
        found = re.findall("texts", " ".join(_note for path in features["ember"]["dir"].rglob("*.java")
                                             for _note in advice.LITERAL_TEXT.findall(path.read_text(encoding="utf-8"))) + "texts")
        self.assertTrue(found)
        self.assertEqual(advice.LITERAL_TEXT.findall('player.sendSystemMessage(Component.literal("The block is warm."));'), ["The block is warm."])
        self.assertEqual(advice.LITERAL_TEXT.findall('panel.setText("state", "Burning hot");'), ["Burning hot"])
        self.assertEqual(advice.LITERAL_TEXT.findall('Component.literal("3");'), [])
        self.assertEqual(advice.LITERAL_TEXT.findall('context.text("warm");'), [])


if __name__ == "__main__":
    unittest.main()
