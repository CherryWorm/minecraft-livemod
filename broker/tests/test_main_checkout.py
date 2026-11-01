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

from orchestrator import llm, wording, workshop, world_index

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


class Guard(unittest.TestCase):
    """With real git, because what matters is what it refuses."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.name", "Test", cwd=self.repo)
        git("config", "user.email", "test@localhost", cwd=self.repo)
        (self.repo / "bible").mkdir()
        (self.repo / "bible/theme.md").write_text("a theme", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "Start", cwd=self.repo)
        self.tree = self.root / "tree"
        git("worktree", "add", "-q", "-b", "feature/demo", str(self.tree), "main", cwd=self.repo)
        (self.tree / "mine.txt").write_text("a builder's work", encoding="utf-8")
        git("add", "-A", cwd=self.tree)
        git("commit", "-q", "-m", "work in progress", cwd=self.tree)
        for target, name, value in ((workshop, "REPO", self.repo), (workshop._git, "__kwdefaults__", {"cwd": self.repo})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        workshop.guard_main()
        self.start = git("rev-parse", "main", cwd=self.repo)

    def refused(self, *args, cwd):
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            git(*args, cwd=cwd)
        self.assertEqual(git("rev-parse", "main", cwd=self.repo), self.start, args)
        return caught.exception.stderr

    def test_a_builder_cant_move_main_from_its_own_tree(self):
        self.assertIn("main only moves when a feature is released", self.refused("update-ref", "refs/heads/main", "feature/demo", cwd=self.tree))
        self.refused("branch", "-f", "main", "feature/demo", cwd=self.tree)

    def test_nor_from_the_main_checkout(self):
        (self.repo / "stray.txt").write_text("x", encoding="utf-8")
        git("add", "stray.txt", cwd=self.repo)
        self.refused("commit", "-q", "-m", "straight onto main", cwd=self.repo)
        self.refused("merge", "-q", "--no-ff", "-m", "merging myself", "feature/demo", cwd=self.repo)

    def test_nor_by_going_backwards(self):
        workshop._git("commit", "-q", "--allow-empty", "-m", "Later")
        self.start = git("rev-parse", "main", cwd=self.repo)
        self.refused("reset", "-q", "--hard", "HEAD~1", cwd=self.repo)

    def test_a_builder_can_still_commit_to_its_own_branch(self):
        (self.tree / "more.txt").write_text("more", encoding="utf-8")
        git("add", "-A", cwd=self.tree)
        git("commit", "-q", "-m", "more work", cwd=self.tree)
        self.assertEqual(git("rev-parse", "main", cwd=self.repo), self.start)

    def test_and_merge_main_into_it(self):
        workshop._git("commit", "-q", "--allow-empty", "-m", "Released something")
        git("merge", "-q", "--no-edit", "main", cwd=self.tree)

    def test_the_agent_can_still_release_and_commit_its_own_files(self):
        workshop._git("merge", "-q", "--no-ff", "-m", "Released demo", "feature/demo")
        self.assertTrue((self.repo / "mine.txt").exists())
        (self.repo / "bible/theme.md").write_text("a better theme", encoding="utf-8")
        workshop.commit_files("A better theme", "bible")
        self.assertEqual(git("log", "-1", "--format=%s", "main", cwd=self.repo), "A better theme")

    def test_new_builders_get_their_own_branch_as_usual(self):
        other = self.root / "other"
        git("worktree", "add", "-q", "-B", "feature/other", str(other), "main", cwd=self.repo)
        self.assertEqual(git("rev-parse", "HEAD", cwd=other), self.start)

    def test_the_prompt_tells_them(self):
        self.assertIn("Never move or commit to `main`", llm.prompt_text("builder"))


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
