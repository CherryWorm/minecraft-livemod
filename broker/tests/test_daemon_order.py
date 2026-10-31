"""With several builders working, quick checks go ahead of full test runs, and otherwise the oldest goes first."""
import json
import os
import pathlib
import tempfile
import unittest

from broker import daemon


class Order(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        self.age = 1000

    def request(self, name, kind):
        path = self.folder / f"{name}.json"
        path.write_text(json.dumps({"id": name, "kind": kind}), encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
