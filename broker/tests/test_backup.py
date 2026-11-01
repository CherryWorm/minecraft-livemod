#!/usr/bin/env python3
"""The copy of the world taken before a restart. With players on, mods change small files while it's taken, and that mustn't stop a release.

Usage: python3 -m unittest broker.tests.test_backup
"""
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from broker import deploy


class Backup(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.commands = []
        for name, stand_in in (("RUNTIME", pathlib.Path(folder.name)), ("inspect_state", mock.Mock(return_value={"Running": True})),
                               ("rcon", mock.Mock(side_effect=lambda server, *command, **kwargs: self.commands.append(command[0])))):
            patcher = mock.patch.object(deploy.runtime, name, stand_in)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def tar_exits(code):
        result = types.SimpleNamespace(returncode=code, stdout="tar: world: file changed as we read it\n")
        return mock.patch.object(deploy.runtime, "run", mock.Mock(return_value=result))

    def test_a_file_changing_during_the_copy_does_not_stop_a_release(self):
        with self.tar_exits(1):
            self.assertTrue(deploy.backup().name.startswith("world-"))
        self.assertEqual(self.commands, ["save-off", "save-all", "save-on"])

    def test_a_copy_that_really_failed_does_and_saving_still_comes_back(self):
        with self.tar_exits(2), self.assertRaises(RuntimeError):
            deploy.backup()
        self.assertEqual(self.commands[-1], "save-on")


if __name__ == "__main__":
    unittest.main()
