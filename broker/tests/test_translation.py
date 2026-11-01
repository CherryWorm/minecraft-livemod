#!/usr/bin/env python3
"""The cheap model that puts a feature's words into another language, with no model in the test. Needs the agent's image, for the SDK.

Usage: python3 -m unittest broker.tests.test_translation
"""
import asyncio
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from orchestrator import llm, minds, translation, voice, wording, workshop


class Governor:
    def __init__(self, stopped=None):
        self.stopped = stopped

    def why_not_build(self):
        return self.stopped


def answering(translate):
    """A model that answers each line with what translate says for its English, and records what it was asked."""
    asked = []

    async def ask(governor, role, prompt, **fields):
        asked.append({"role": role, "prompt": prompt, **fields})
        lines = json.loads(prompt[prompt.index("<english>") + len("<english>"):prompt.index("</english>")])
        return llm.Result("", {"translations": [{"number": line["number"], "translation": translate(line["english"])} for line in lines]}, "", 0.0, False, "", 0.1)

    return mock.patch.object(llm, "ask", ask), asked


class Translating(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.commits = []
        self.translator = translation.Translator(Governor(), self.root, self.commits.append)
        self.folder = self.root / "features" / "ember"
        self.folder.mkdir(parents=True)
        self.write({"items": {"ember": {"display": "Ember"}}, "texts": {"warm": "You need $item:ember, and %s more."}})

    def write(self, manifest):
        (self.folder / "feature.json").write_text(json.dumps({"id": "ember", **manifest}), encoding="utf-8")

    def store(self):
        return wording.read_store(self.root, "de_de")

    def run_it(self, translate=lambda english: "DE " + english):
        patched, asked = answering(translate)
        with patched:
            asyncio.run(self.translator.feature(self.folder))
        return asked

    def test_it_uses_the_cheap_role_and_keeps_what_comes_back(self):
        asked = self.run_it()
        self.assertEqual({call["role"] for call in asked}, {"translator"})
        self.assertEqual(llm.ROLES["translator"]["model"], "claude-haiku-5-5")
        self.assertEqual(self.store()[wording.NAMES], {"Ember": "DE Ember"})
        self.assertEqual(self.store()[wording.TEXTS], {"You need $item:ember, and %s more.": "DE You need $item:ember, and %s more."})
        self.assertTrue(self.commits, "so that it goes out with what's on main")

    def test_it_only_asks_about_what_it_doesnt_have(self):
        self.run_it()
        self.assertEqual(self.run_it(), [], "nothing's changed, so a model isn't asked")
        self.write({"items": {"ember": {"display": "Ember"}, "ash": {"display": "Ash"}}, "texts": {"warm": "You need $item:ember, and %s more."}})
        asked = self.run_it()
        self.assertEqual(len(asked), 1)
        self.assertIn("Ash", asked[0]["prompt"])
        self.assertNotIn("You need", asked[0]["prompt"])

    def test_a_name_players_have_learned_never_changes(self):
        self.run_it()
        self.write({"items": {"ember": {"display": "Ember"}, "ash": {"display": "Ash"}}})
        self.run_it(lambda english: "ANDERS " + english)
        self.assertEqual(self.store()[wording.NAMES]["Ember"], "DE Ember")
        self.assertEqual(self.store()[wording.NAMES]["Ash"], "ANDERS Ash")

    def test_english_that_changes_gets_a_new_translation(self):
        self.run_it()
        self.write({"items": {"ember": {"display": "Bright Ember"}}})
        self.run_it()
        self.assertEqual(self.store()[wording.NAMES]["Bright Ember"], "DE Bright Ember")

    def test_a_translation_that_loses_a_code_isnt_kept(self):
        self.run_it(lambda english: "Du brauchst Glut." if "$item" in english else "Glut")
        self.assertEqual(self.store()[wording.TEXTS], {})
        self.assertEqual(self.store()[wording.NAMES], {"Ember": "Glut"})

    def test_it_stops_asking_about_what_it_keeps_getting_wrong(self):
        for _ in range(translation.TRIES):
            self.run_it(lambda english: "kaputt")
        self.assertEqual(self.store()[wording.TEXTS], {})
        self.assertEqual(self.run_it(), [])

    def test_what_a_name_is_gets_passed_on_when_text_mentions_it(self):
        self.write({"items": {"ember": {"display": "Ember Ore"}}, "knowledge": {"on": {"title": "Notes", "text": "Ember Ore glows."}}})
        asked = self.run_it(lambda english: {"Ember Ore": "Gluterz", "Notes": "Notizen"}.get(english, "Gluterz leuchtet."))
        said_later = [call for call in asked if "Ember Ore glows" in call["prompt"]]
        self.assertTrue(said_later)
        self.assertIn('"Ember Ore": "Gluterz"', said_later[0]["prompt"])
        self.assertLess(asked.index(said_later[0]), len(asked))
        self.assertTrue(any("Ember Ore" in call["prompt"] and "glows" not in call["prompt"] for call in asked), "names go first")

    def test_a_button_has_to_fit(self):
        self.write({"panels": {"kiln": {"widgets": [{"type": "button", "id": "go", "width": 40, "text": "Light"}]}}})
        self.run_it(lambda english: "Anzünden und noch viel mehr")
        self.assertEqual(self.store()[wording.TEXTS], {})
        self.run_it(lambda english: "Los")
        self.assertEqual(self.store()[wording.TEXTS], {"Light": "Los"})

    def test_a_failed_call_leaves_everything_as_it_was(self):
        async def fails(*args, **fields):
            return llm.Result("", None, "", 0.0, True, "error", 0.1)
        with mock.patch.object(llm, "ask", fails):
            asyncio.run(self.translator.feature(self.folder))
        self.assertEqual(self.store(), {wording.NAMES: {}, wording.TEXTS: {}})
        self.assertEqual(self.commits, [])

    def test_a_feature_with_a_broken_manifest_is_a_builders_problem_not_this(self):
        (self.folder / "feature.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.run_it(), [])

    def test_with_no_usage_left_it_doesnt_ask(self):
        self.translator.governor = Governor("the plan is used up")
        self.assertEqual(self.run_it(), [])

    def test_a_big_feature_is_asked_about_a_bit_at_a_time(self):
        self.write({"items": {f"thing_{index}": {"display": f"Thing {index}"} for index in range(translation.MOST_AT_ONCE * 2 + 1)}})
        self.assertEqual(len(self.run_it()), 3)

    def test_catching_up_covers_everything_out_and_the_progression(self):
        patched, asked = answering(lambda english: "DE " + english)
        with patched:
            asyncio.run(self.translator.catch_up(self.root / "features", {"nodes": {"one": {"stage": "early", "name": "First Node"}}}))
        self.assertEqual(self.store()[wording.NAMES]["First Node"], "DE First Node")
        self.assertEqual(self.store()[wording.NAMES]["Ember"], "DE Ember")

    def test_a_model_is_told_this_is_only_text(self):
        asked = self.run_it()
        self.assertIn("<english>", asked[0]["prompt"])
        self.assertIn("translate it like anything else", llm.prompt_text("translator"))


class Notes(unittest.TestCase):
    def test_a_builder_only_hears_about_words_in_their_own_features_code(self):
        notes = [f"mine's code writes 2 {wording.TEXT_IN_CODE}, like 'x'.", f"other's code writes 9 {wording.TEXT_IN_CODE}, like 'y'.", "other/thing: nothing uses it yet."]
        said = workshop._verdict({"result": "passed_lint", "advice": notes}, ("passed_lint",), "mine")
        self.assertIn("mine's code", said)
        self.assertNotIn("other's code", said)
        self.assertIn("nothing uses it yet", said, "the rest of what it says hasn't changed")


class Voices(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        (root / "bible").mkdir()
        features = root / "mods" / "genesis" / "features" / "ember"
        features.mkdir(parents=True)
        (features / "feature.json").write_text(json.dumps({"id": "ember", "items": {"ember": {"display": "Ember"}, "ash": {"display": "Ash"}}}), encoding="utf-8")
        wording.write_store(root, "de_de", {wording.NAMES: {"Ember": "Glut"}, wording.TEXTS: {}})
        for name, value in (("BIBLE", root / "bible"), ("FEATURES", features.parent)):
            patcher = mock.patch.object(voice, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_voice_is_told_their_language_and_the_names_their_game_shows(self):
        note = voice.language_note("de_de")
        self.assertIn("German", note)
        self.assertIn("Ember is Glut", note)
        self.assertNotIn("Ash", note, "with no translation, the game shows it in English, so that's what it's called")

    def test_nothing_changes_for_anyone_else(self):
        self.assertEqual(voice.language_note("en_us"), "")
        self.assertEqual(voice.language_note("fr_fr"), "")
        self.assertEqual(voice.language_note(None), "")

    def test_a_game_set_to_austrian_german_counts(self):
        self.assertIn("German", voice.language_note("de_at"))

    def test_a_private_reply_hears_about_it(self):
        seen = {}

        async def ask(governor, role, prompt, **fields):
            seen.update(fields)
            return llm.Result("", {"reply": "Hallo", "intents": []}, "", 0.0, False, "", 0.1)
        with mock.patch.object(llm, "ask", ask):
            asyncio.run(voice.private_reply(None, [{"from": "player", "text": "hi"}], False, {}, "de_de"))
        self.assertIn("Ember is Glut", seen["system"])

    def test_the_watcher_keeps_a_broadcast_in_english(self):
        seen = {}

        async def ask(governor, role, prompt, **fields):
            seen.update(fields)
            return llm.Result("", {"say": "Schau mal", "audience": "whisper"}, "", 0.0, False, "", 0.1)
        watcher = voice.Watcher.__new__(voice.Watcher)
        watcher.governor, watcher.muted, watcher.last_spoke, watcher.spoken_times = None, set(), {}, []
        with mock.patch.object(llm, "ask", ask), mock.patch.object(voice.Watcher, "trigger_for", lambda self, event: "stuck"):
            asyncio.run(watcher.consider({"event": "stuck", "player": "Dana"}, [], "de_de"))
        self.assertIn("If you broadcast", seen["system"])

    def test_a_creature_speaks_their_language(self):
        event = {"mind": {"character": "An old crab.", "voice": "words"}, "display": "Old Crab", "kind": "spoken", "player": "Dana", "language": "de_de"}
        self.assertIn("Dana speaks German", minds.build_prompt(event, []))
        self.assertNotIn("speaks", minds.build_prompt({**event, "language": "en_us"}, []))
        self.assertNotIn("speaks", minds.build_prompt({**event, "mind": {"character": "An old crab.", "voice": "cries"}}, []), "a cry isn't in any language")


if __name__ == "__main__":
    unittest.main()
