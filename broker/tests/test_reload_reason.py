#!/usr/bin/env python3
"""Players are told why the game's about to freeze or restart, in plain words and before it happens.

Usage: python3 -m unittest broker.tests.test_reload_reason
"""
import asyncio
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from broker import daemon, deploy
from broker.tests.test_batched_release import Base
from orchestrator import feedback

GRAPH = {"nodes": {"e_one": {"stage": "early"}}}


class Deploy(unittest.TestCase):
    def setUp(self):
        self.calls = []
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.release = pathlib.Path(folder.name) / "r1"
        (self.release / "content").mkdir(parents=True)
        (self.release / "jars").mkdir()

        def record(name):
            return mock.Mock(side_effect=lambda *args, **kwargs: self.calls.append((name, args)))

        for target, name, stand_in in ((deploy.runtime, "rcon", mock.Mock(side_effect=self.rcon)), (deploy.runtime, "apply_content", record("apply")),
                                       (deploy.runtime, "reload_content", record("reload")), (deploy.runtime, "load_state", mock.Mock(return_value={})),
                                       (deploy.runtime, "save_state", mock.Mock()), (deploy.runtime, "utc_now", mock.Mock(return_value="now")),
                                       (deploy.runtime, "world_lock", mock.MagicMock()),
                                       (deploy, "wait_for_safe_moment", mock.Mock(side_effect=lambda: self.calls.append(("safe", ())) or True)),
                                       (deploy, "backup", record("backup")), (deploy, "_install_jars", record("jars")),
                                       (deploy, "_restart_prod", record("restart")), (deploy, "health_check", mock.Mock(return_value=None))):
            patcher = mock.patch.object(target, name, stand_in)
            patcher.start()
            self.addCleanup(patcher.stop)

    def rcon(self, server, *command, check=True):
        self.calls.append(("told", json.loads(command[2])["text"]) if command[0] == "tellraw" else ("rcon", command))
        self.assertFalse(check, "a message that can't be sent must not stop a release")
        return ""

    def order(self):
        return [call[0] for call in self.calls]

    def said(self):
        return [call[1] for call in self.calls if call[0] == "told"]

    def test_a_reload_says_why_before_anything_happens(self):
        deploy.deploy("T2", self.release, "a recipe fix and early game machine")
        self.assertEqual(self.order(), ["safe", "told", "apply", "reload"])
        self.assertIn("Reloading", self.said()[0])
        self.assertIn("a recipe fix and early game machine", self.said()[0])

    def test_a_restart_says_so_before_anything_happens(self):
        deploy.deploy("T3", self.release, "a recipe fix")
        self.assertEqual(self.order()[:3], ["safe", "told", "backup"])
        self.assertLess(self.order().index("told"), self.order().index("restart"))
        self.assertIn("Restarting", self.said()[0])
        self.assertIn("a recipe fix", self.said()[0])

    def test_an_engine_update_still_gives_a_reason(self):
        deploy.deploy("T3", self.release)
        self.assertIn(deploy.NOTHING_NAMED, self.said()[0])

    def test_a_long_reason_is_cut_short(self):
        deploy.deploy("T2", self.release, "x" * 1000)
        self.assertLess(len(self.said()[0]), deploy.MOST_WHY + 100)

    def test_undoing_a_bad_release_says_so(self):
        deploy.rollback({}, "the server stopped running")
        self.assertIn("undo", self.said()[0])
        self.assertLess(self.order().index("told"), self.order().index("restart"))


class Daemon(unittest.TestCase):
    def test_the_reason_reaches_the_release(self):
        with mock.patch.object(daemon, "promote") as promote, mock.patch.object(daemon.runtime, "agent_disabled", return_value=False):
            daemon.handle({"id": "1", "kind": "release", "commit": "abc", "release_id": "r1", "why": "a recipe fix"})
        promote.assert_called_once_with("abc", "r1", "--why=a recipe fix", lane="")


class Words(unittest.TestCase):
    def test_a_small_job_goes_by_its_title(self):
        self.assertEqual(feedback.about({"small": True, "title": "a recipe fix", "teaser": "unused"}, GRAPH), "a recipe fix")

    def test_anything_else_uses_the_sidebars_careful_words(self):
        self.assertEqual(feedback.about({"teaser": "a slow furnace", "node": "e_one", "category": "machine"}, GRAPH), "a slow furnace")

    def test_without_those_it_only_says_stage_and_category(self):
        self.assertEqual(feedback.about({"node": "e_one", "category": "machine", "spec": "The Secret Furnace"}, GRAPH), "early game machine")

    def test_a_release_lists_what_it_brings(self):
        self.assertEqual(feedback.release_reason(["a"]), "a")
        self.assertEqual(feedback.release_reason(["a", "b"]), "a and b")
        self.assertEqual(feedback.release_reason(["a", "b", "c"]), "a, b and c")
        self.assertEqual(feedback.release_reason(["a", "b", "c", "d", "e"]), "a, b, c and 2 more")

    def test_the_same_words_arent_repeated(self):
        self.assertEqual(feedback.release_reason(["a", "a", "b"]), "a and b")

    def test_it_always_has_something_to_say(self):
        self.assertEqual(feedback.release_reason(["", ""]), "something new")


class Workshop(Base):
    async def test_a_release_of_several_names_them_all(self):
        await asyncio.gather(*(self.shop._release(name, self.feature(name), "e_one", f"thing {name}") for name in ("a", "b")))
        self.assertEqual(self.releases[0]["why"], "thing a and thing b")


if __name__ == "__main__":
    unittest.main()
