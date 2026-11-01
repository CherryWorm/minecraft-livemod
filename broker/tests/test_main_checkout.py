"""The agent's main checkout holds what's out. A builder with a shell can wander into it, so what one leaves there mustn't get onto main,
and one bad file mustn't stop the voices. Needs the agent's libraries, so it runs in the agent's image.

Usage: python3 -m unittest broker.tests.test_main_checkout
"""
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import wording, workshop, world_index

FEATURES = "mods/genesis/features"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Checkout(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.repo = pathlib.Path(folder.name)
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.name", "Test", cwd=self.repo)
        git("config", "user.email", "test@localhost", cwd=self.repo)
        (self.repo / FEATURES / "kiln").mkdir(parents=True)
        (self.repo / FEATURES / "kiln/feature.json").write_text('{"id": "kiln"}', encoding="utf-8")
        (self.repo / "bible/lang").mkdir(parents=True)
        (self.repo / "bible/lang/de_de.json").write_text("{}", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "Start", cwd=self.repo)
        for target, name, value in ((workshop, "REPO", self.repo), (workshop._git, "__kwdefaults__", {"cwd": self.repo})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def stray(self):
        (self.repo / FEATURES / "half_built").mkdir()
        path = self.repo / FEATURES / "half_built/feature.json"
        path.write_text("placeholder", encoding="utf-8")
        return path

    def committed(self):
        return git("show", "--name-only", "--format=", "HEAD", cwd=self.repo).splitlines()

    def test_only_what_it_names_is_committed(self):
        self.stray()
        (self.repo / "bible/lang/de_de.json").write_text('{"a": "b"}', encoding="utf-8")
        workshop.commit_files("German", "bible/lang")
        self.assertEqual(self.committed(), ["bible/lang/de_de.json"])

    def test_even_what_a_builder_staged_stays_out(self):
        self.stray()
        git("add", "-A", cwd=self.repo)
        (self.repo / "bible/lang/de_de.json").write_text('{"a": "b"}', encoding="utf-8")
        workshop.commit_files("German", "bible/lang")
        self.assertEqual(self.committed(), ["bible/lang/de_de.json"])

    def test_the_translator_only_commits_its_own_files(self):
        shop = workshop.Workshop(mock.Mock(), mock.AsyncMock(), mock.Mock(), lambda: ())
        self.stray()
        (self.repo / "bible/lang/de_de.json").write_text('{"a": "b"}', encoding="utf-8")
        shop.translator.commit("German for 1 more things")
        self.assertEqual(self.committed(), ["bible/lang/de_de.json"])

    def test_nothing_to_commit_makes_no_commit(self):
        before = git("rev-parse", "HEAD", cwd=self.repo)
        workshop.commit_files("Nothing", "bible/lang", "not_there")
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.repo), before)

    def test_strays_are_cleared_and_whats_out_is_put_back(self):
        path = self.stray()
        released = self.repo / FEATURES / "kiln/feature.json"
        released.write_text("placeholder", encoding="utf-8")
        with mock.patch("builtins.print"):
            workshop.clear_strays()
        self.assertFalse(path.exists())
        self.assertEqual(json.loads(released.read_text(encoding="utf-8")), {"id": "kiln"})
        self.assertEqual(git("status", "--porcelain", cwd=self.repo), "")

    def test_clearing_leaves_everything_else_alone(self):
        words = self.repo / "bible/lang/de_de.json"
        words.write_text('{"being": "written"}', encoding="utf-8")
        workshop.clear_strays()
        self.assertEqual(json.loads(words.read_text(encoding="utf-8")), {"being": "written"})

    def test_a_clean_checkout_says_nothing(self):
        with mock.patch("builtins.print") as said:
            workshop.clear_strays()
        said.assert_not_called()

    def test_file_tools_cant_write_there(self):
        self.assertIn("Write(//workspace/repo/**)", workshop.BUILDER_DENIED)
        self.assertIn("Edit(//workspace/repo/**)", workshop.BUILDER_DENIED)


class OneBadFile(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.features = self.root / FEATURES
        (self.features / "kiln").mkdir(parents=True)
        (self.features / "kiln/feature.json").write_text(json.dumps({"id": "kiln", "summary": "A kiln.", "items": {"brick": {"display": "Brick"}}}), encoding="utf-8")
        (self.features / "half_built").mkdir()
        (self.features / "half_built/feature.json").write_text("placeholder", encoding="utf-8")
        (self.features / "a_list").mkdir()
        (self.features / "a_list/feature.json").write_text("[]", encoding="utf-8")
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_voices_guide_still_works(self):
        index = world_index.player_index(self.features)
        self.assertIn("kiln", index)
        self.assertNotIn("half_built", index)
        self.assertNotIn("a_list", index)

    def test_looking_one_up_still_works(self):
        self.assertIn("kiln", world_index.player_entry(self.features, "Brick").lower())

    def test_what_builders_see_still_works(self):
        self.assertIn("kiln", world_index.build(self.features))

    def test_the_progression_still_works(self):
        self.assertEqual(world_index.reached_nodes(self.features, ["Brick"]), set())

    def test_names_in_another_language_still_work(self):
        self.assertEqual(wording.known_names(self.root, self.features, "de_de"), {})


if __name__ == "__main__":
    unittest.main()
