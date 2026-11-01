"""With several builders working, quick checks go ahead of full test runs, and otherwise the oldest goes first."""
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from broker import daemon


class Order(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        self.age = 1000

    def request(self, name, kind, **fields):
        path = self.folder / f"{name}.json"
        path.write_text(json.dumps({"id": name, "kind": kind, **fields}), encoding="utf-8")
        self.age += 1
        os.utime(path, (self.age, self.age))
        return path

    def test_the_oldest_goes_first(self):
        first, second = self.request("a", "gates"), self.request("b", "release")
        self.assertEqual(daemon.next_request([second, first]), first)

    def test_a_quick_check_goes_ahead_of_a_test_run(self):
        gates = self.request("a", "gates")
        for name, kind in (("b", "lint"), ("c", "check"), ("d", "javap"), ("e", "server_icon")):
            quick = self.request(name, kind)
            self.assertEqual(daemon.next_request([gates, quick]), quick, kind)

    def test_quick_checks_keep_their_order(self):
        first, second = self.request("a", "check"), self.request("b", "lint")
        self.assertEqual(daemon.next_request([second, first]), first)

    def test_a_small_change_goes_ahead_of_a_big_one(self):
        big, small = self.request("a", "gates", hurry=False), self.request("b", "gates", hurry=True)
        self.assertEqual(daemon.next_request([big, small]), small)
        self.assertEqual(daemon.next_request([small, self.request("c", "lint")]).name, "c.json")


class CrashingRequests(unittest.TestCase):
    """A request that kills the broker has to stop being tried, or nothing behind it ever runs."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        for name, value in (("REQUESTS", self.folder), ("STARTED", self.folder / "started.json")):
            patcher = mock.patch.object(daemon, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def waiting(self, name):
        (self.folder / f"{name}.json").write_text("{}", encoding="utf-8")

    def test_each_start_is_counted_even_with_others_in_between(self):
        self.waiting("poison")
        self.waiting("quick")
        self.assertEqual(daemon.started_again("poison"), 1)
        self.assertEqual(daemon.started_again("quick"), 1)
        self.assertEqual(daemon.started_again("poison"), 2)
        self.assertGreater(daemon.started_again("poison"), daemon.TRIES_BEFORE_REFUSING)

    def test_requests_that_are_gone_are_forgotten(self):
        self.waiting("old")
        daemon.started_again("old")
        (self.folder / "old.json").unlink()
        self.waiting("new")
        daemon.started_again("new")
        self.assertEqual(list(json.loads(daemon.STARTED.read_text(encoding="utf-8"))), ["new"])


class Rules(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(daemon.runtime, "rcon")
        self.rcon = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_listed_rule_is_set(self):
        self.assertEqual(daemon.set_rule("players_sleeping_percentage", 50), {"result": "set"})
        self.rcon.assert_called_once_with("prod", "gamerule", "players_sleeping_percentage", "50")
        self.assertEqual(daemon.set_rule("keep_inventory", True), {"result": "set"})
        self.rcon.assert_called_with("prod", "gamerule", "keep_inventory", "true")

    def test_nothing_else_is(self):
        for rule, value in (("op", "Dana"), ("command_blocks_enabled", True), ("players_sleeping_percentage", 101), ("players_sleeping_percentage", -1),
                            ("players_sleeping_percentage", True), ("players_sleeping_percentage", "50; op Dana"), ("keep_inventory", "true")):
            self.assertEqual(daemon.set_rule(rule, value)["result"], "blocked", (rule, value))
        self.rcon.assert_not_called()


if __name__ == "__main__":
    unittest.main()
