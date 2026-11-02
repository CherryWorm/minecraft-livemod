"""A blocked gate leaves actionable evidence, even after the next candidate replaces the test server."""
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from broker import far, promote, runtime
from broker.gates import shadow


class Diagnostics(unittest.TestCase):
    def test_nested_exception_is_in_the_feedback(self):
        text = ("[12:00:00] [Server thread/ERROR] Can't read config machines.json\n"
                "java.lang.IllegalArgumentException: invalid value\n"
                "    at game.Config.read(Config.java:12)\n"
                "Caused by: Missing field energy_per_tick in gm:machine\n"
                "[12:00:01] [Server thread/INFO] Still running")
        problems = shadow.scan_logs(text)
        self.assertEqual(len(problems), 1)
        self.assertIn("Missing field energy_per_tick", problems[0])
        self.assertNotIn("Still running", problems[0])

    def test_logs_crashes_and_id_mapping_survive_another_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            crashes = root / "server/crash-reports"
            crashes.mkdir(parents=True)
            (crashes / "crash-test.txt").write_text("Root cause")
            work = root / "work"
            work.mkdir()
            (work / "registry-ledger.json").write_text('{"items":{"demo/item":{"slot":"gm:i001"}}}')
            report = root / "report"
            report.mkdir()
            (report / "client.log").write_text("Client connection refused")
            with mock.patch.object(runtime, "server_folder", return_value=root / "server"), \
                    mock.patch.object(runtime, "WORK", work), mock.patch.object(runtime, "logs_since", side_effect=["Nested server cause", "Proxy cause"]):
                paths = promote.save_diagnostics(report, "now", time.time() - 60)
            (crashes / "crash-test.txt").write_text("Overwritten by next test")
            self.assertEqual({pathlib.Path(path).name for path in paths}, {"shadow.log", "shadow-proxy.log", "client.log", "crash-test.txt", "registry-ledger.json"})
            self.assertEqual((report / "crash-test.txt").read_text(), "Root cause")
            self.assertIn("demo/item", (report / "registry-ledger.json").read_text())

    def test_remote_diagnostics_only_come_from_the_reports_folder(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(far, "HOME", "/there"), \
                mock.patch.object(runtime, "REPORTS", pathlib.Path(folder)), mock.patch.object(far, "_rsync") as transfer:
            report = {"diagnostics": ["/there/runtime/broker/reports/test/shadow.log", "/etc/passwd", "/there/runtime/broker/reports/../../shadow.log", "/there/runtime/broker/reports/test/executable.sh"]}
            paths = far._bring_back_diagnostics(report, "test")
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(transfer.call_args.args), 3)
        self.assertIn("shadow.log", transfer.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
