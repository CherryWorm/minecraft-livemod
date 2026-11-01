"""What the broker lets someone looking into a bug see, and how a bug fix is put ahead of everything. No servers needed.

Usage: python3 -m unittest broker.tests.test_bug_evidence
"""
import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from broker import daemon

LOG = """[12:00:01] [Server thread/INFO]: Player0[/172.18.0.1:55826] logged in with entity id 17 at (-418.5, 111.0, -178.5)
[12:00:02] [Server thread/INFO]: System chat: Player0 joined the game
[12:00:03] [Server thread/WARN]: Something odd from 10.1.2.3:4567
[12:00:04] [Server thread/ERROR]: The kiln module failed
java.lang.IllegalStateException: no fuel
\tat gm.feature.kiln.KilnModule.tick(KilnModule.java:12)
Caused by: java.lang.NullPointerException
[12:00:05] [Server thread/INFO]: Dana has made the advancement
[12:00:06] [Server thread/ERROR]: Failed to read from https://discovery.minecraftservices.com/minecraft/client
[12:00:07] [Server thread/ERROR]: The mill module failed
"""


class Errors(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.log = pathlib.Path(folder.name) / "latest.log"
        self.log.write_text(LOG, encoding="utf-8")
        patcher = mock.patch.object(daemon, "PROD_LOG", self.log)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_what_went_wrong(self):
        output = daemon.server_errors()["output"]
        self.assertIn("The kiln module failed", output)
        self.assertIn("IllegalStateException", output)
        self.assertIn("at gm.feature.kiln.KilnModule.tick", output)
        self.assertIn("Caused by", output)
        self.assertNotIn("joined the game", output)
        self.assertNotIn("logged in", output)
        self.assertNotIn("made the advancement", output)

    def test_never_an_address(self):
        output = daemon.server_errors()["output"]
        self.assertNotIn("10.1.2.3", output)
        self.assertNotIn("172.18", output)
        self.assertIn("(address)", output)

    def test_what_the_server_always_says_is_left_out(self):
        self.assertNotIn("minecraftservices", daemon.server_errors()["output"])

    def test_it_can_be_narrowed_down(self):
        output = daemon.server_errors("KILN")["output"]
        self.assertIn("kiln module", output)
        self.assertNotIn("mill module", output)

    def test_it_says_so_when_theres_nothing(self):
        self.assertIn("Nothing like that", daemon.server_errors("no such thing")["output"])
        self.log.unlink()
        self.assertIn("no log", daemon.server_errors()["output"])

    def test_it_cant_be_huge(self):
        self.log.write_text("".join(f"[12:00:00] [Server thread/ERROR]: Failure number {index}\n" for index in range(50000)), encoding="utf-8")
        output = daemon.server_errors()["output"]
        self.assertLessEqual(len(output), daemon.MOST_LOG_CHARACTERS)
        self.assertIn("Failure number 49999", output)

    def test_the_broker_answers_it_as_a_quick_job(self):
        self.assertIn("server_errors", daemon.QUICK)
        with mock.patch.object(daemon.runtime, "agent_disabled", return_value=False):
            self.assertIn("kiln module", daemon.handle({"id": "x", "kind": "server_errors", "contains": "kiln"})["output"])


class Order(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)

    def request(self, name, age, **fields):
        path = self.root / f"{name}.json"
        path.write_text(json.dumps({"id": name, **fields}), encoding="utf-8")
        then = time.time() - age
        import os
        os.utime(path, (then, then))
        return path

    def test_a_bug_fix_goes_ahead_of_everything_that_isnt_a_quick_answer(self):
        waiting = [self.request("old_build", 500, kind="gates"), self.request("small", 400, kind="gates", hurry=True), self.request("out", 300, kind="release")]
        fix = self.request("fix", 1, kind="gates", first=True, hurry=True)
        self.assertEqual(daemon.next_request([*waiting, fix]), fix)
        quick = self.request("lint", 0, kind="lint")
        self.assertEqual(daemon.next_request([*waiting, fix, quick]), quick)

    def test_otherwise_its_as_it_was(self):
        waiting = [self.request("old_build", 500, kind="gates"), self.request("small", 400, kind="gates", hurry=True)]
        self.assertEqual(daemon.next_request(waiting).stem, "small")
        self.assertEqual(daemon.next_request([waiting[0]]).stem, "old_build")


if __name__ == "__main__":
    unittest.main()
