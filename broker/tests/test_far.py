"""Test runs on another machine: it can't get anything live, it isn't believed about anything but how a test went, and if it goes away nobody notices."""
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from broker import daemon, far, runtime

WAIT_SECONDS = 10
REAL_RUN = far._run


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        for target, name, value in ((far, "MACHINE", "someone@elsewhere"), (far, "HOME", "/there"), (far, "LANES", 2), (far, "down_until", 0), (far, "world_sent", None),
                                    (runtime, "RUNTIME", self.root), (runtime, "REPORTS", self.root / "reports"), (runtime, "HISTORY", self.root / "history"),
                                    (runtime, "STATE_FILE", self.root / "state.json")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime.STATE_FILE.write_text(json.dumps({"current": "r1"}), encoding="utf-8")
        (runtime.HISTORY / "r1").mkdir(parents=True)
        (self.root / "assembled").mkdir()
        self.commands = []
        self.report = {"result": "passed_gates", "stages": {"build": 12}}
        patcher = mock.patch.object(far.shadow, "copy_live_world", side_effect=lambda target: self.commands.append(["copy world", str(target)]))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(far, "_run", side_effect=self.fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fails_on = None

    def fake_run(self, command, timeout):
        self.commands.append(command)
        if self.fails_on and any(self.fails_on in str(part) for part in command):
            return subprocess.CompletedProcess(command, 255 if command[0] == "ssh" else 12, "", "no route to host")
        stdout = json.dumps(self.report) if command[0] == "ssh" and "broker.promote" in command[-1] else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    def run_far(self, flags=("--no-deploy",), lane="far-1", release_id="feature-1"):
        return far.run(self.root / "assembled", release_id, flags, lane)

    def promote_command(self):
        return next(command[-1] for command in self.commands if command[0] == "ssh" and "broker.promote" in command[-1])


class Lanes(Case):
    def test_none_without_a_machine(self):
        with mock.patch.object(far, "LANES", 0):
            self.assertEqual(far.lanes(), [])

    def test_a_test_run_goes_there_first(self):
        with mock.patch.object(daemon, "GATE_LANES", 2):
            self.assertEqual(daemon.lanes_for("gates"), ["far-1", "far-2", "", "gates-1"])

    def test_a_release_never_does(self):
        with mock.patch.object(daemon, "GATE_LANES", 2):
            self.assertEqual(daemon.lanes_for("release"), ["", "gates-1"])

    def test_nor_does_anything_else(self):
        self.assertFalse(any(far.is_far(lane) for kind in ("check", "lint", "javap", "server_icon", "set_rule", "server_errors") for lane in daemon.lanes_for(kind)))

    def test_a_machine_that_let_a_job_down_is_left_alone_for_a_while(self):
        far.mark_down()
        self.assertEqual(far.lanes(), [])
        with mock.patch.object(far.time, "monotonic", return_value=time.monotonic() + far.DOWN_SECONDS + 1):
            self.assertEqual(far.lanes(), ["far-1", "far-2"])

    def test_they_dont_use_this_machines_memory(self):
        job = daemon.Job("gates", "far-1", None, time.monotonic())
        with mock.patch.object(daemon, "memory_available_gb", return_value=0.5):
            self.assertTrue(daemon.room_for("gates", "far-2", {"a": job}))
            self.assertTrue(daemon.room_for("check", "check-0", {"a": job}), "a job over there isn't one here")


class Running(Case):
    def test_only_a_test_run_can_go_there(self):
        for flags in (("--why=x",), ("--check-only",), ()):
            with self.assertRaises(ValueError):
                self.run_far(flags)
        self.assertEqual(self.commands, [])

    def test_it_runs_in_the_lane_of_the_same_number_there(self):
        self.run_far(lane="far-2")
        command = self.promote_command()
        self.assertIn("BROKER_LANE=gates-2", command)
        self.assertIn("cd /there/repo-gates-2", command)
        self.assertIn("--no-deploy", command)

    def test_what_comes_from_a_builder_cant_become_a_command(self):
        self.run_far(release_id="x; rm -rf /")
        self.assertIn("'x; rm -rf /'", self.promote_command())

    def test_what_it_needs_arrives_before_it_starts(self):
        self.run_far()
        order = [" ".join(map(str, command)) for command in self.commands]
        started = next(index for index, text in enumerate(order) if "broker.promote" in text)
        for sent in ("state.json", "history/r1", "runtime/prod/world", "repo-gates-1"):
            self.assertLess(next(index for index, text in enumerate(order) if sent in text), started, sent)

    def test_its_own_settings_survive_the_code_being_sent(self):
        self.run_far()
        sending = next(command for command in self.commands if "repo-gates-1/" in str(command[-1]))
        self.assertIn("--exclude=.env", sending)
        self.assertIn("ln -sf /there/machine.env .env", self.promote_command())

    def test_a_job_left_over_from_a_restart_here_is_waited_for(self):
        self.run_far()
        self.assertIn("flock -w", self.promote_command())

    def test_a_failure_there_is_an_ordinary_answer(self):
        self.report = {"result": "blocked", "gate": "client", "reason": "It didn't render."}
        answer = self.run_far()
        self.assertEqual((answer["result"], answer["gate"], answer["reason"]), ("blocked", "client", "It didn't render."))
        self.assertEqual(far.lanes(), ["far-1", "far-2"], "that's the work's fault and not the machine's")


class World(Case):
    def test_its_copied_here_first_and_only_then_sent(self):
        self.run_far()
        order = [str(command[0]) + " " + " ".join(map(str, command[1:])) for command in self.commands]
        copied = next(index for index, text in enumerate(order) if text.startswith("copy world"))
        sent = next(index for index, text in enumerate(order) if "runtime/prod/world/" in text and text.startswith("rsync"))
        self.assertLess(copied, sent)

    def test_it_holds_the_machines_own_lock_while_it_arrives(self):
        self.run_far()
        sending = next(command for command in self.commands if "runtime/prod/world/" in str(command[-1]))
        self.assertIn("--rsync-path=flock /there/runtime/broker/world.lock rsync", sending)

    def test_its_only_sent_every_so_often(self):
        self.run_far()
        self.run_far(lane="far-2")
        self.assertEqual(sum(command[0] == "copy world" for command in self.commands), 1)
        with mock.patch.object(far.time, "monotonic", return_value=time.monotonic() + far.WORLD_MOST_STALE_SECONDS + 1):
            self.run_far()
        self.assertEqual(sum(command[0] == "copy world" for command in self.commands), 2)

    def test_not_being_able_to_copy_it_counts_as_the_machine_not_being_ready(self):
        with mock.patch.object(far.shadow, "copy_live_world", side_effect=RuntimeError("the live server isn't answering")):
            with self.assertRaises(far.Gone):
                self.run_far()


class Believing(Case):
    def test_it_cant_claim_a_release_went_out(self):
        for result in ("released", "rolled_back", None, "anything"):
            self.report = {"result": result}
            with self.assertRaises(far.Gone):
                self.run_far()

    def test_nor_send_anything_that_isnt_a_report(self):
        for report in ([1, 2], "passed_gates", 5):
            self.report = report
            with self.assertRaises(far.Gone):
                self.run_far()

    def test_only_what_says_how_a_test_went_is_kept(self):
        self.report = {"result": "passed_gates", "deploy": {"backup": "/x"}, "release": "something-else", "anything": "else", "tier": "T2"}
        answer = self.run_far()
        self.assertEqual(set(answer), {"result", "tier", "release", "screenshots"})
        self.assertEqual(answer["release"], "feature-1")

    def test_a_long_reason_is_cut_short(self):
        self.report = {"result": "blocked", "reason": "x" * 100000}
        self.assertEqual(len(self.run_far()["reason"]), far.MOST_REASON_CHARACTERS)

    def test_only_pictures_from_the_right_place_come_back(self):
        good = "/there/runtime/broker/reports/feature-1/shot.png"
        self.report = {"result": "passed_gates", "screenshots": [good, "/etc/passwd", "/there/runtime/secrets/rcon.png", "/there/runtime/broker/reports/../../secrets/x.png",
                                                                 "/there/runtime/broker/reports/feature-1/shot.sh", 7]}
        answer = self.run_far()
        self.assertEqual(answer["screenshots"], [str(runtime.REPORTS / "feature-1" / "shot.png")])
        pulling = next(command for command in self.commands if command[0] == "rsync" and f"someone@elsewhere:{good}" in command)
        self.assertEqual(sum("someone@elsewhere:" in str(part) for part in pulling), 1)
        self.assertTrue(any(str(part).startswith("--max-size=") for part in pulling))

    def test_a_pass_there_leaves_nothing_a_release_would_trust(self):
        with mock.patch.object(runtime, "BROKER", self.root / "broker"):
            self.run_far()
            self.assertFalse((runtime.BROKER / "passed_gates").exists())


class GoingAway(Case):
    def test_any_step_failing_is_the_machine_going_away(self):
        for step in ("mkdir -p", "state.json", "history/r1", "versions", "runtime/prod/world", "repo-gates-1/", "broker.promote"):
            with mock.patch.object(far, "world_sent", None), mock.patch.object(far, "down_until", 0):
                self.fails_on = step
                with self.assertRaises(far.Gone, msg=step):
                    self.run_far()
                self.assertEqual(far.lanes(), [], step)

    def test_no_report_is_the_machine_going_away(self):
        with mock.patch.object(far, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            with self.assertRaises(far.Gone):
                self.run_far()
        self.assertEqual(far.lanes(), [])

    def test_taking_too_long_is_too(self):
        def too_long(command, timeout, **_):
            raise subprocess.TimeoutExpired(command, timeout)

        with mock.patch.object(far.subprocess, "run", side_effect=too_long), mock.patch.object(far, "_run", REAL_RUN):
            with self.assertRaises(far.Gone):
                self.run_far()


class Broker(Case):
    """Through the broker's own loop, with the job itself replaced."""

    def setUp(self):
        super().setUp()
        self.requests = self.root / "requests"
        self.responses = self.root / "responses"
        self.requests.mkdir()
        self.responses.mkdir()
        for target, name, value in ((daemon, "REQUESTS", self.requests), (daemon, "RESPONSES", self.responses), (daemon, "STARTED", self.root / "started.json"),
                                    (daemon, "DRAINING", self.root / "draining"), (daemon, "GATE_LANES", 1), (daemon, "CHECK_LANES", 1), (daemon, "lanes_used", set()),
                                    (daemon, "given_back", set())):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.running = {}
        self.lanes_tried = []
        self.age = 1000

    def request(self, name, kind, **fields):
        path = self.requests / f"{name}.json"
        path.write_text(json.dumps({"id": name, "kind": kind, **fields}), encoding="utf-8")
        self.age += 1
        os.utime(path, (self.age, self.age))
        return path

    def serve(self, name, handle):
        began = time.monotonic()
        with mock.patch.object(daemon, "handle", handle):
            while not (self.responses / f"{name}.json").exists():
                self.assertLess(time.monotonic() - began, WAIT_SECONDS, "it never answered")
                if not daemon.tick(self.running):
                    time.sleep(0.01)
        return json.loads((self.responses / f"{name}.json").read_text(encoding="utf-8"))

    def test_if_the_machine_goes_away_the_job_runs_here_and_nobody_hears(self):
        def handle(request, lane=""):
            self.lanes_tried.append(lane)
            if far.is_far(lane):
                far.mark_down()
                raise far.Gone("no route to host")
            return {"result": "passed_gates"}

        self.request("job", "gates", commit="abc")
        answer = self.serve("job", handle)
        self.assertEqual(self.lanes_tried, ["far-1", ""])
        self.assertEqual(answer, {"result": "passed_gates"})

    def test_that_doesnt_use_up_its_tries(self):
        def handle(request, lane=""):
            if far.is_far(lane):
                far.mark_down()
                raise far.Gone("no route to host")
            return {"result": "passed_gates"}

        self.request("job", "gates", commit="abc")
        began = time.monotonic()
        with mock.patch.object(daemon, "handle", handle):
            while "job.json" not in daemon.given_back:
                self.assertLess(time.monotonic() - began, WAIT_SECONDS)
                daemon.tick(self.running)
            while self.running and any(job.thread.is_alive() for job in self.running.values()):
                time.sleep(0.01)
            with mock.patch.object(daemon, "free_lane", return_value=None):
                daemon.tick(self.running)
        self.assertEqual(json.loads(daemon.STARTED.read_text(encoding="utf-8")).get("job"), 0)

    def test_a_release_waits_here_even_with_the_machine_free(self):
        self.request("going_out", "release", commit="abc")
        answer = self.serve("going_out", lambda request, lane="": self.lanes_tried.append(lane) or {"result": "released"})
        self.assertEqual(self.lanes_tried, [""])
        self.assertEqual(answer["result"], "released")

    def test_a_test_run_there_leaves_this_machines_lanes_free_for_a_release(self):
        slow = threading.Event()
        self.addCleanup(slow.set)
        seen = {}

        def handle(request, lane=""):
            seen[request["id"]] = lane
            if request["kind"] == "gates":
                slow.wait(WAIT_SECONDS)
            return {"result": "done"}

        self.request("testing", "gates", commit="a")
        with mock.patch.object(daemon, "handle", handle):
            daemon.tick(self.running)
            self.request("going_out", "release", commit="b")
            began = time.monotonic()
            while not (self.responses / "going_out.json").exists():
                self.assertLess(time.monotonic() - began, WAIT_SECONDS, "the release waited for the test run")
                if not daemon.tick(self.running):
                    time.sleep(0.01)
            slow.set()
            for job in self.running.values():
                job.thread.join(WAIT_SECONDS)
        self.assertEqual(seen, {"testing": "far-1", "going_out": ""})

    def test_the_lane_and_flags_reach_the_machine(self):
        with mock.patch.object(daemon, "assemble", return_value=self.root / "assembled"), mock.patch.object(far, "run", return_value={"result": "passed_gates"}) as run:
            daemon.handle({"id": "x", "kind": "gates", "commit": "abc", "release_id": "r"}, "far-2")
        run.assert_called_once_with(self.root / "assembled", "r", ("--no-deploy",), "far-2")

    def test_pictures_reach_the_agent_as_usual(self):
        picture = self.root / "reports" / "r" / "day.png"
        picture.parent.mkdir(parents=True)
        picture.write_bytes(b"png")
        with mock.patch.object(daemon, "assemble", return_value=self.root / "assembled"), mock.patch.object(daemon, "REPORTS_FOR_AGENT", self.root / "for-agent"), \
                mock.patch.object(far, "run", return_value={"result": "passed_gates", "screenshots": [str(picture)]}):
            answer = daemon.promote("abc", "r", "--no-deploy", lane="far-1")
        self.assertEqual(answer["screenshots"], ["/workspace/reports/r/day.png"])
        self.assertTrue((self.root / "for-agent" / "r" / "day.png").exists())


if __name__ == "__main__":
    unittest.main()
