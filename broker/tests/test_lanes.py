"""Quick jobs don't wait behind slow ones, and jobs running at the same time can't touch each other's files."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from broker import daemon, runtime

WAIT_SECONDS = 10


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.requests = self.root / "requests"
        self.responses = self.root / "responses"
        self.requests.mkdir()
        self.responses.mkdir()
        for name, value in (("REQUESTS", self.requests), ("RESPONSES", self.responses), ("STARTED", self.root / "started.json"),
                            ("DRAINING", self.root / "draining")):
            patcher = mock.patch.object(daemon, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.running = {}
        self.age = 1000
        self.ran = []
        self.overlap = []
        self.active = set()
        self.lock = threading.Lock()
        self.slow = threading.Event()
        self.addCleanup(self.slow.set)  # So a test that fails doesn't leave a job waiting forever.

    def request(self, name, kind, **fields):
        path = self.requests / f"{name}.json"
        path.write_text(json.dumps({"id": name, "kind": kind, **fields}), encoding="utf-8")
        self.age += 1
        os.utime(path, (self.age, self.age))
        return path

    def stand_in(self, request, lane=""):
        """Takes as long as this test says, in place of really doing the job."""
        with self.lock:
            self.ran.append((request["id"], lane))
            self.overlap.append(set(self.active))
            self.active.add(request["id"])
        try:
            if request["kind"] in ("gates", "release", "check"):
                self.slow.wait(WAIT_SECONDS)
            return {"result": "done", "lane": lane}
        finally:
            with self.lock:
                self.active.discard(request["id"])

    def serve_until(self, done):
        """Runs the broker's loop until something's true, and says how long that took."""
        began = time.monotonic()
        with mock.patch.object(daemon, "handle", self.stand_in):
            while not done():
                self.assertLess(time.monotonic() - began, WAIT_SECONDS, "it never happened")
                if not daemon.tick(self.running):
                    time.sleep(0.01)
        return time.monotonic() - began

    def answered(self, name):
        return (self.responses / f"{name}.json").exists()

    def answer(self, name):
        return json.loads((self.responses / f"{name}.json").read_text(encoding="utf-8"))

    def finish_all(self):
        self.slow.set()
        for job in self.running.values():
            job.thread.join(WAIT_SECONDS)


class QuickJobs(Case):
    def test_a_lookup_and_a_lint_are_answered_while_a_test_run_goes_on(self):
        self.request("slow", "gates")
        self.serve_until(lambda: "slow" in self.active)
        self.request("lookup", "javap", class_name="a.B")
        self.request("linting", "lint", commit="abc")
        seconds = self.serve_until(lambda: self.answered("lookup") and self.answered("linting"))
        self.assertLess(seconds, 2, "they waited for something")
        self.assertIn("slow", self.active)
        self.assertFalse(self.answered("slow"))
        self.finish_all()
        self.assertEqual(self.answer("slow")["result"], "done")

    def test_a_release_doesnt_hold_them_up_either(self):
        self.request("going_out", "release", commit="abc")
        self.serve_until(lambda: "going_out" in self.active)
        self.request("lookup", "javap", class_name="a.B")
        self.serve_until(lambda: self.answered("lookup"))
        self.assertIn("going_out", self.active)
        self.finish_all()

    def test_quick_jobs_run_at_the_same_time_as_each_other(self):
        count = 6
        meeting = threading.Barrier(count, timeout=WAIT_SECONDS)

        def wait_for_the_others(request, lane=""):
            meeting.wait()  # Only gets past this if they're all running at once.
            return {"result": "done"}

        for number in range(count):
            self.request(f"q{number}", "lint" if number % 2 else "javap", commit="abc", class_name="a.B")
        began = time.monotonic()
        with mock.patch.object(daemon, "handle", wait_for_the_others):
            while not all(self.answered(f"q{number}") for number in range(count)):
                self.assertLess(time.monotonic() - began, WAIT_SECONDS)
                if not daemon.tick(self.running):
                    time.sleep(0.01)
        self.assertEqual({self.answer(f"q{number}")["result"] for number in range(count)}, {"done"})

    def test_each_lint_at_the_same_time_has_its_own_lane(self):
        lanes = [daemon.free_lane("lint", {})]
        running = {"a": daemon.Job("lint", lanes[0], None)}
        lanes.append(daemon.free_lane("lint", running))
        self.assertEqual(len(set(lanes)), 2)
        self.assertNotIn("", lanes)

    def test_theres_a_limit_on_how_many(self):
        running = {str(number): daemon.Job("lint", f"lint-{number}", None) for number in range(daemon.MOST_AT_ONCE)}
        self.assertIsNone(daemon.free_lane("lint", running))
        self.assertIsNotNone(daemon.free_lane("javap", running))

    def test_whats_left_still_goes_in_order(self):
        self.request("big", "gates")
        self.request("small", "gates", hurry=True)
        self.serve_until(lambda: self.active)
        self.assertEqual(self.active, {"small"})
        self.slow.set()
        self.serve_until(lambda: self.answered("small") and self.answered("big"))
        self.assertEqual(self.overlap[1], set(), "two test runs overlapped")


class Crashes(Case):
    def test_a_request_taken_back_is_skipped(self):
        path = self.request("gone", "gates")
        real = daemon.next_request

        def take_it_back(ready):
            found = real(ready)
            path.unlink()
            return found

        with mock.patch.object(daemon, "next_request", take_it_back), mock.patch.object(daemon, "handle", self.stand_in):
            self.assertTrue(daemon.tick(self.running))
        self.assertEqual(self.ran, [])
        self.assertFalse(self.answered("gone"))

    def test_a_job_that_fails_is_told_and_the_rest_carry_on(self):
        def fails(request, lane=""):
            if request["id"] == "bad":
                raise ValueError("it broke")
            return {"result": "done"}

        self.request("bad", "javap", class_name="a.B")
        self.request("fine", "javap", class_name="a.B")
        with mock.patch.object(daemon, "handle", fails):
            began = time.monotonic()
            while not (self.answered("bad") and self.answered("fine")):
                self.assertLess(time.monotonic() - began, WAIT_SECONDS)
                if not daemon.tick(self.running):
                    time.sleep(0.01)
        self.assertEqual(self.answer("bad")["result"], "blocked")
        self.assertIn("it broke", self.answer("bad")["reason"])
        self.assertEqual(self.answer("fine")["result"], "done")

    def test_a_job_running_right_now_isnt_started_again(self):
        self.request("slow", "javap", class_name="a.B")
        self.slow.clear()
        with mock.patch.object(daemon, "handle", lambda request, lane="": self.slow.wait(WAIT_SECONDS) and {"result": "done"}):
            daemon.tick(self.running)
            self.assertEqual(len(self.running), 1)
            self.assertFalse(daemon.tick(self.running))
            self.assertEqual(len(self.running), 1)
            self.assertEqual(json.loads(daemon.STARTED.read_text(encoding="utf-8")), {"slow": 1})
        self.finish_all()

    def test_one_that_keeps_killing_the_broker_is_refused(self):
        self.request("poison", "gates")
        daemon.STARTED.write_text(json.dumps({"poison": daemon.TRIES_BEFORE_REFUSING}), encoding="utf-8")
        self.slow.set()
        with mock.patch.object(daemon, "handle", self.stand_in):
            daemon.retry_suspects()
        self.assertEqual(self.ran, [])
        self.assertEqual(self.answer("poison")["result"], "blocked")
        self.assertIn("died", self.answer("poison")["reason"])

    def test_after_a_crash_each_goes_alone_so_only_the_bad_one_is_refused(self):
        self.request("poison", "gates")
        self.request("harmless", "lint", commit="abc")
        self.request("harmless_too", "javap", class_name="a.B")
        self.request("new", "javap", class_name="a.B")
        daemon.STARTED.write_text(json.dumps({"poison": 2, "harmless": 1, "harmless_too": 1}), encoding="utf-8")
        self.slow.set()
        with mock.patch.object(daemon, "handle", self.stand_in):
            daemon.retry_suspects()
        self.assertEqual(sorted(name for name, _ in self.ran), ["harmless", "harmless_too"])
        self.assertTrue(all(not beside for beside in self.overlap), "something ran beside a suspect")
        self.assertEqual(self.answer("poison")["result"], "blocked")
        self.assertEqual(self.answer("harmless")["result"], "done")
        self.assertFalse(self.answered("new"), "a new request went ahead of them")

    def test_a_suspect_taken_back_is_skipped(self):
        self.request("gone", "gates")
        daemon.STARTED.write_text(json.dumps({"gone": 1}), encoding="utf-8")
        (self.requests / "gone.json").unlink()
        with mock.patch.object(daemon, "handle", self.stand_in):
            daemon.retry_suspects()
        self.assertEqual(self.ran, [])


class Draining(Case):
    def test_nothing_new_starts_but_whats_running_finishes(self):
        self.request("slow", "gates")
        self.serve_until(lambda: "slow" in self.active)
        daemon.DRAINING.touch()
        self.request("lookup", "javap", class_name="a.B")
        with mock.patch.object(daemon, "handle", self.stand_in):
            self.assertFalse(daemon.tick(self.running))
        self.assertNotIn("lookup", {name for name, _ in self.ran})
        self.finish_all()
        self.assertTrue(self.answered("slow"))

    def test_it_doesnt_last_for_ever_if_whoever_asked_died(self):
        daemon.DRAINING.touch()
        self.assertTrue(daemon.draining())
        old = time.time() - daemon.MOST_DRAINING_SECONDS - 1
        os.utime(daemon.DRAINING, (old, old))
        self.assertFalse(daemon.draining())


class Folders(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)

    def test_a_lane_is_given_its_own_folders(self):
        for lane in ("lint-3", ""):
            script = "from broker import runtime; print(runtime.WORK); print(runtime.LAST_REPORT)"
            found = subprocess.run([sys.executable, "-c", script], cwd=runtime.REPO, env={**os.environ, "BROKER_LANE": lane},
                                   capture_output=True, text=True, check=True).stdout.splitlines()
            self.assertEqual(found, [str(runtime.lane_folder(lane) / "work"), str(runtime.lane_folder(lane) / "last.json")])
        self.assertEqual(runtime.lane_folder(""), runtime.BROKER)
        self.assertNotEqual(runtime.lane_folder("lint-3"), runtime.BROKER)

    def test_promote_keeps_each_lanes_files_apart(self):
        """One lint's report can't be read by another, and one's source can't replace another's."""
        seen = []

        def fake_run(command, **kwargs):
            lane = kwargs["env"]["BROKER_LANE"]
            seen.append((lane, command[command.index("--source") + 1]))
            runtime.lane_folder(lane).mkdir(parents=True, exist_ok=True)
            (runtime.lane_folder(lane) / "last.json").write_text(json.dumps({"result": "passed_lint", "lane": lane}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(runtime, "RUNTIME", self.root), mock.patch.object(runtime, "BROKER", self.root / "broker"), \
                mock.patch.object(daemon, "assemble", lambda commit, lane="": runtime.lane_folder(lane) / "assembled"), \
                mock.patch.object(daemon.subprocess, "run", fake_run):
            answers = [daemon.promote("abc", f"r{index}", "--lint-only", lane=lane) for index, lane in enumerate(("lint-0", "lint-1", ""))]
        self.assertEqual([answer["lane"] for answer in answers], ["lint-0", "lint-1", ""])
        self.assertEqual(len({source for _, source in seen}), 3)
        self.assertEqual(seen[2][1], str(self.root / "broker" / "assembled"))

    def test_a_lane_that_dies_doesnt_answer_with_an_old_report(self):
        with mock.patch.object(runtime, "RUNTIME", self.root), \
                mock.patch.object(daemon, "assemble", lambda commit, lane="": self.root), \
                mock.patch.object(daemon.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "it died")):
            old = runtime.lane_folder("lint-0") / "last.json"
            old.parent.mkdir(parents=True)
            old.write_text(json.dumps({"result": "passed_lint"}), encoding="utf-8")
            answer = daemon.promote("abc", "r", "--lint-only", lane="lint-0")
        self.assertEqual(answer["result"], "blocked")
        self.assertIn("it died", answer["reason"])

    def test_the_state_file_is_never_half_written(self):
        state_file = self.root / "state.json"
        real_replace = pathlib.Path.replace
        seen = []

        def look_first(path, target):
            seen.append(not target.exists() or json.loads(target.read_text(encoding="utf-8"))["current"] == "old")
            return real_replace(path, target)

        with mock.patch.object(runtime, "STATE_FILE", state_file), mock.patch.object(pathlib.Path, "replace", look_first):
            runtime.save_state({"current": "old"})
            runtime.save_state({"current": "new"})
        self.assertEqual(seen, [True, True])
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["current"], "new")


if __name__ == "__main__":
    unittest.main()
