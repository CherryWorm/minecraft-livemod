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
                            ("DRAINING", self.root / "draining"), ("CHECK_LANES", 1), ("GATE_LANES", 1), ("lanes_used", set())):
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
        running = {"a": daemon.Job("lint", lanes[0], None, 0)}
        lanes.append(daemon.free_lane("lint", running))
        self.assertEqual(len(set(lanes)), 2)
        self.assertNotIn("", lanes)

    def test_theres_a_limit_on_how_many(self):
        running = {str(number): daemon.Job("lint", f"lint-{number}", None, 0) for number in range(daemon.MOST_AT_ONCE)}
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


class CompileChecks(Case):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(daemon, "CHECK_LANES", 3), mock.patch.object(daemon, "memory_available_gb", return_value=30)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_several_run_side_by_side_each_in_its_own_lane(self):
        for name in ("a", "b", "c"):
            self.request(name, "check", commit=name)
        self.serve_until(lambda: len(self.active) == 3)
        self.assertEqual(len({lane for _, lane in self.ran}), 3)
        self.assertNotIn("", {lane for _, lane in self.ran})
        self.finish_all()

    def test_any_more_wait_for_a_lane(self):
        for name in ("a", "b", "c", "d"):
            self.request(name, "check", commit=name)
        self.serve_until(lambda: len(self.active) == 3)
        for _ in range(5):
            daemon.tick(self.running)
        self.assertEqual(len(self.active), 3)
        self.assertEqual(self.active, {"a", "b", "c"}, "the oldest should have gone first")
        self.slow.set()
        self.serve_until(lambda: self.answered("d"))

    def test_they_dont_wait_for_a_test_run(self):
        self.request("slow", "gates")
        self.serve_until(lambda: "slow" in self.active)
        self.request("compile", "check", commit="abc")
        self.serve_until(lambda: "compile" in self.active)
        self.finish_all()

    def test_the_lanes_go_to_the_promote_that_builds_there(self):
        seen = {}
        with mock.patch.object(daemon, "promote", lambda commit, release_id, *flags, lane="": seen.update(flags=flags, lane=lane) or {"result": "passed_gates"}):
            daemon.handle({"id": "x", "kind": "check", "commit": "abc"}, "check-2")
        self.assertEqual(seen, {"flags": ("--check-only",), "lane": "check-2"})


class Memory(Case):
    def job(self, kind, age=1000):
        return daemon.Job(kind, f"{kind}-0", None, time.monotonic() - age)

    def test_one_alone_always_goes_ahead(self):
        with mock.patch.object(daemon, "memory_available_gb", return_value=0.5):
            self.assertTrue(daemon.room_for("gates", "", {}))
            self.assertTrue(daemon.room_for("gates", "", {"a": self.job("lint")}))

    def test_small_jobs_never_wait_for_memory(self):
        with mock.patch.object(daemon, "memory_available_gb", return_value=0.5):
            self.assertIsNotNone(daemon.free_lane("lint", {"a": self.job("gates")}))
            self.assertIsNotNone(daemon.free_lane("javap", {"a": self.job("gates")}))

    def test_a_big_one_beside_another_needs_room_and_some_to_spare(self):
        running = {"a": self.job("gates")}
        need = daemon.BIG_JOBS["check"] + daemon.KEEP_FREE_GB
        with mock.patch.object(daemon, "memory_available_gb", return_value=need):
            self.assertTrue(daemon.room_for("check", "check-0", running))
        with mock.patch.object(daemon, "memory_available_gb", return_value=need - 0.1):
            self.assertFalse(daemon.room_for("check", "check-0", running))

    def test_what_a_job_that_just_started_will_use_is_counted(self):
        need = daemon.BIG_JOBS["check"] + daemon.KEEP_FREE_GB
        with mock.patch.object(daemon, "memory_available_gb", return_value=need + 1):
            self.assertTrue(daemon.room_for("check", "check-0", {"a": self.job("gates")}))
            self.assertFalse(daemon.room_for("check", "check-0", {"a": self.job("gates", age=1)}))

    def test_a_lane_thats_never_been_used_needs_room_for_its_test_server_too(self):
        running = {"a": self.job("gates")}
        need = daemon.BIG_JOBS["gates"] + daemon.KEEP_FREE_GB
        with mock.patch.object(daemon, "memory_available_gb", return_value=need + daemon.NEW_LANE_GB - 0.1):
            self.assertFalse(daemon.room_for("gates", "gates-1", running))
            daemon.lanes_used.add("gates-1")
            self.assertTrue(daemon.room_for("gates", "gates-1", running))

    def test_memory_going_at_the_last_moment_only_means_another_look(self):
        path = self.request("late", "check", commit="a")
        with mock.patch.object(daemon, "free_lane", return_value=None):
            daemon.start_job(path, self.running)
        self.assertEqual(self.running, {})
        self.assertFalse(daemon.STARTED.exists(), "it hasn't been tried, so that shouldn't count as a try")
        self.assertTrue(path.exists())

    def test_waiting_for_memory_starts_when_theres_room(self):
        with mock.patch.object(daemon, "CHECK_LANES", 2), mock.patch.object(daemon, "memory_available_gb", return_value=1) as memory:
            self.request("a", "check", commit="a")
            self.request("b", "check", commit="b")
            self.serve_until(lambda: "a" in self.active)
            for _ in range(5):
                daemon.tick(self.running)
            self.assertEqual(self.active, {"a"})
            memory.return_value = 30
            self.running = {name: job._replace(began=0) for name, job in self.running.items()}
            self.serve_until(lambda: "b" in self.active)
            self.finish_all()


class TestRuns(Case):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(daemon, "GATE_LANES", 3), mock.patch.object(daemon, "memory_available_gb", return_value=30)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_several_run_side_by_side_each_in_its_own_lane(self):
        for name in ("a", "b", "c"):
            self.request(name, "gates", commit=name)
        self.serve_until(lambda: len(self.active) == 3)
        self.assertEqual(sorted(lane for _, lane in self.ran), ["", "gates-1", "gates-2"])
        self.finish_all()

    def test_any_more_wait_and_small_ones_are_still_first(self):
        for name in ("a", "b", "c"):
            self.request(name, "gates", commit=name)
        self.serve_until(lambda: len(self.active) == 3)
        self.request("big", "gates", commit="big")
        self.request("small", "gates", commit="small", hurry=True)
        for _ in range(5):
            daemon.tick(self.running)
        self.assertEqual(self.active, {"a", "b", "c"})
        self.slow.set()
        self.serve_until(lambda: self.answered("small") and self.answered("big"))
        started = [name for name, _ in self.ran]
        self.assertLess(started.index("small"), started.index("big"))

    def test_a_release_gets_the_next_lane_before_anything_else(self):
        for name in ("a", "b", "c"):
            self.request(name, "gates", commit=name)
        self.serve_until(lambda: len(self.active) == 3)
        self.request("waiting", "gates", commit="w")
        self.request("going_out", "release", commit="r")
        self.slow.set()
        self.serve_until(lambda: self.answered("waiting") and self.answered("going_out"))
        started = [name for name, _ in self.ran]
        self.assertLess(started.index("going_out"), started.index("waiting"))

    def test_only_one_release_at_a_time_however_many_lanes_there_are(self):
        self.request("first", "release", commit="a")
        self.request("second", "release", commit="b")
        self.request("gating", "gates", commit="c")
        self.serve_until(lambda: {"first", "gating"} <= self.active)
        for _ in range(5):
            daemon.tick(self.running)
        self.assertEqual(self.active, {"first", "gating"})
        self.slow.set()
        self.serve_until(lambda: self.answered("second"))
        for name, beside in zip([name for name, _ in self.ran], self.overlap):
            if name == "second":
                self.assertNotIn("first", beside)

    def test_a_release_runs_in_a_lane_a_test_run_isnt_using(self):
        self.request("gating", "gates", commit="c")
        self.serve_until(lambda: "gating" in self.active)
        self.request("going_out", "release", commit="a")
        self.serve_until(lambda: "going_out" in self.active)
        self.assertEqual(sorted(lane for _, lane in self.ran), ["", "gates-1"])
        self.finish_all()

    def test_quick_jobs_and_checks_dont_wait_for_any_of_them(self):
        for name in ("a", "b", "c"):
            self.request(name, "gates", commit=name)
        self.serve_until(lambda: len(self.active) == 3)
        self.request("lookup", "javap", class_name="a.B")
        self.request("linting", "lint", commit="abc")
        self.serve_until(lambda: self.answered("lookup") and self.answered("linting"))
        self.request("compile", "check", commit="abc")
        self.serve_until(lambda: "compile" in self.active)
        self.finish_all()

    def test_asking_again_doesnt_run_beside_the_first_try(self):
        self.request("first_try", "gates", commit="a", release_id="feature-1")
        self.serve_until(lambda: "first_try" in self.active)
        (self.requests / "first_try.json").unlink()
        self.request("second_try", "gates", commit="a", release_id="feature-1")
        for _ in range(5):
            daemon.tick(self.running)
        self.assertEqual(self.active, {"first_try"})
        self.slow.set()
        self.serve_until(lambda: self.answered("second_try"))

    def test_one_lane_means_what_it_always_has(self):
        with mock.patch.object(daemon, "GATE_LANES", 1):
            self.assertEqual(daemon.lanes_for("gates"), [""])
            self.assertEqual(daemon.lanes_for("release"), [""])

    def test_a_job_keeps_its_place_when_memory_is_short_and_one_is_running(self):
        with mock.patch.object(daemon, "memory_available_gb", return_value=1):
            self.request("a", "gates", commit="a")
            self.request("b", "gates", commit="b")
            self.serve_until(lambda: "a" in self.active)
            for _ in range(5):
                daemon.tick(self.running)
            self.assertEqual(self.active, {"a"})
            self.slow.set()
            self.serve_until(lambda: self.answered("b"))
            self.assertEqual([lane for name, lane in self.ran if name == "b"], [""], "it should have got the first lane back")


class TestServerFolders(unittest.TestCase):
    """Each lane's test server has to be separate from every other's, and it has to be impossible for one to reach the live one."""

    def settings(self, lane):
        script = ("import json; from broker import runtime as r; from broker.gates import client; print(json.dumps({'env': r.SHADOW_ENV, 'port': r.SHADOW_PROXY_PORT, "
                  "'services': r.SHADOW_SERVICES, 'shadow': str(r.server_folder('shadow')), 'proxy': str(r.server_folder('shadow-proxy')), 'prod': str(r.server_folder('prod')), "
                  "'candidate': str(r.candidate_folder()), 'diff': str(r.DIFF), 'work': str(r.WORK), 'shadow_container': r.container('shadow'), 'prod_container': r.container('prod'), "
                  "'client': client.CONTAINER, 'report': str(r.LAST_REPORT)}))")
        return json.loads(subprocess.run([sys.executable, "-c", script], cwd=runtime.REPO, env={**os.environ, "BROKER_LANE": lane}, capture_output=True, text=True, check=True).stdout)

    def test_the_first_lane_is_what_its_always_been(self):
        first = self.settings("")
        self.assertEqual(first["env"], {})
        self.assertEqual(first["services"], ["shadow", "shadow-proxy"])
        self.assertEqual(first["shadow"], str(runtime.RUNTIME / "shadow"))
        self.assertEqual(first["candidate"], str(runtime.RELEASES / "candidate"))
        self.assertEqual(first["diff"], str(runtime.BROKER / "diff"))
        self.assertEqual(first["client"], f"{runtime.PROJECT}-gate-client")
        self.assertEqual(first["shadow_container"], f"{runtime.PROJECT}-shadow-1")

    def test_no_two_lanes_share_anything_of_their_own(self):
        lanes = [self.settings(lane) for lane in ("", "gates-1", "gates-2")]
        for key in ("port", "shadow", "proxy", "candidate", "diff", "work", "shadow_container", "client", "report"):
            self.assertEqual(len({lane[key] for lane in lanes}), 3, key)
        pack_ports = {lane["env"].get("SHADOW_PACK_PORT", "25568") for lane in lanes}
        self.assertEqual(len(pack_ports | {lane["port"] for lane in lanes}), 6, "two lanes would fight over a port")

    def test_every_lane_still_means_the_real_live_server(self):
        for lane in ("", "gates-1", "check-0", "lint-0"):
            found = self.settings(lane)
            self.assertEqual(found["prod"], str(runtime.RUNTIME / "prod"), lane)
            self.assertEqual(found["prod_container"], f"{runtime.PROJECT}-prod-1", lane)

    def test_a_lane_never_asks_for_the_site_or_the_live_server(self):
        found = self.settings("gates-1")
        self.assertEqual(found["services"], ["--no-deps", "shadow", "shadow-proxy", "shadow-pack"])
        self.assertEqual(found["env"]["COMPOSE_PROJECT_NAME"], f"{runtime.PROJECT}-gates-1")

    def test_other_jobs_have_no_test_server_settings(self):
        for lane in ("check-0", "lint-0"):
            self.assertEqual(self.settings(lane)["env"], {})

    def test_server_commands_go_to_the_right_project(self):
        calls = []
        with mock.patch.object(runtime, "SHADOW_ENV", {"COMPOSE_PROJECT_NAME": "lane"}), \
                mock.patch.object(runtime, "run", lambda command, **kwargs: calls.append(kwargs["env"]) or subprocess.CompletedProcess(command, 0, "", "")):
            runtime.rcon("shadow", "list")
            runtime.rcon("prod", "list")
        self.assertEqual(calls, [{"COMPOSE_PROJECT_NAME": "lane"}, {}])


class WorldCopies(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        patcher = mock.patch.object(runtime, "BROKER", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_one_thing_at_a_time_has_saving_turned_off(self):
        """Run as separate processes, because that's what lanes are."""
        script = ("import sys, time; from broker import runtime; import pathlib; runtime.BROKER = pathlib.Path(sys.argv[1])\n"
                  "with runtime.world_lock():\n    print('in', time.monotonic(), flush=True); time.sleep(0.4); print('out', time.monotonic(), flush=True)\n")
        first = subprocess.Popen([sys.executable, "-c", script, str(self.root)], cwd=runtime.REPO, stdout=subprocess.PIPE, text=True)
        second = subprocess.Popen([sys.executable, "-c", script, str(self.root)], cwd=runtime.REPO, stdout=subprocess.PIPE, text=True)
        events = sorted((float(line.split()[1]), line.split()[0]) for process in (first, second) for line in process.communicate()[0].splitlines())
        self.assertEqual([kind for _, kind in events], ["in", "out", "in", "out"], "they overlapped")

    def test_a_clone_holds_it_and_turns_saving_back_on_when_it_fails(self):
        order = []
        lock = mock.MagicMock()
        lock.__enter__.side_effect = lambda: order.append("locked")
        lock.__exit__.side_effect = lambda *args: order.append("unlocked")
        (self.root / "prod" / "world").mkdir(parents=True)
        with mock.patch.object(runtime, "RUNTIME", self.root), mock.patch.object(runtime, "world_lock", return_value=lock), \
                mock.patch.object(runtime, "inspect_state", return_value={"Running": True}), \
                mock.patch.object(runtime, "rcon", side_effect=lambda server, *command, **_: order.append(command[0])), \
                mock.patch.object(runtime, "sync_tree", side_effect=OSError("disk full")):
            from broker.gates import shadow
            with self.assertRaises(OSError):
                shadow.clone_prod_world()
        self.assertEqual(order, ["locked", "save-off", "save-all", "save-on", "unlocked"])

    def test_a_test_server_started_with_other_jars_is_started_again(self):
        from broker.gates import shadow
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "conduit.jar").write_bytes(b"old engine")
        new = self.root / "built" / "conduit.jar"
        new.parent.mkdir()
        new.write_bytes(b"new engine")
        with mock.patch.object(runtime, "candidate_folder", return_value=candidate):
            self.assertFalse(shadow.running_these_jars([new]))
            new.write_bytes(b"old engine")
            self.assertTrue(shadow.running_these_jars([new]))


class Passes(unittest.TestCase):
    """A release can use a pass from any lane, and a pass in one lane can't hide one in another."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.passes = pathlib.Path(folder.name) / "passed_gates"

    def test_several_are_kept_at_once(self):
        from broker import promote
        promote.remember_pass(self.passes, "one", ["a.png"])
        promote.remember_pass(self.passes, "two", ["b.png"])
        self.assertEqual(json.loads((self.passes / "one.json").read_text(encoding="utf-8"))["screenshots"], ["a.png"])
        self.assertEqual(json.loads((self.passes / "two.json").read_text(encoding="utf-8"))["screenshots"], ["b.png"])
        self.assertEqual(list(self.passes.glob("*.tmp")), [])

    def test_old_ones_are_tidied_away(self):
        from broker import promote
        promote.remember_pass(self.passes, "old", [])
        long_ago = time.time() - promote.PASSES_KEPT_SECONDS - 1
        os.utime(self.passes / "old.json", (long_ago, long_ago))
        promote.remember_pass(self.passes, "new", [])
        self.assertEqual([path.stem for path in self.passes.glob("*.json")], ["new"])


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

    def test_each_lane_starts_its_gradle_files_from_the_main_ones(self):
        (self.root / "cache" / "gradle" / "caches").mkdir(parents=True)
        (self.root / "cache" / "gradle" / "caches" / "a.jar").write_text("jar", encoding="utf-8")
        (self.root / "cache" / "gradle" / "caches" / "modules-2.lock").write_text("somebody's", encoding="utf-8")
        calls = []

        def sync(source, target, *excludes):
            calls.append((source, excludes))
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", "-r", str(source), str(target)], check=True)

        with mock.patch.object(runtime, "RUNTIME", self.root), mock.patch.object(runtime, "LANE", "check-1"), mock.patch.object(runtime, "sync_tree", sync):
            env = runtime.tools_cache()
            self.assertEqual(env, {"TOOLS_CACHE": str(self.root / "lanes" / "check-1" / "cache")})
            self.assertTrue((self.root / "lanes" / "check-1" / "cache" / "gradle" / "caches" / "a.jar").exists())
            self.assertIn("*.lock", calls[0][1])
            self.assertEqual(runtime.tools_cache(), env)
            self.assertEqual(len(calls), 1, "only the first build needs a copy")

    def test_no_lane_means_the_main_gradle_files(self):
        with mock.patch.object(runtime, "LANE", ""):
            self.assertEqual(runtime.tools_cache(), {})

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
