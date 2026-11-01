"""What happens to a feature when the machine building it comes and goes, and how work gets handed to one. Needs no server."""
import asyncio
import hashlib
import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from orchestrator import lanes, llm, worker_hub, workshop


class Hub(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        self.hub = worker_hub.WorkerHub(self.folder, mock.AsyncMock(), mock.Mock(), lambda: ())

    def machine(self, name="pc", slots=2, seen=None):
        self.hub.machines[name] = {"slots": slots, "lane": lanes.SELF_HOSTED, "seen": time.time() if seen is None else seen}

    def waiting_job(self, feature="demo", session=None):
        task = asyncio.create_task(self.hub.attempt(feature, self.folder, {"session": session, "prompt": "Go."}))
        return task

    async def test_only_machines_heard_from_lately_have_room(self):
        self.assertEqual(self.hub.free_slots(), 0)
        self.machine()
        self.assertEqual(self.hub.free_slots(), 2)
        self.machine("gone", slots=5, seen=time.time() - worker_hub.SEEN_WITHIN_SECONDS - 1)
        self.assertEqual(self.hub.free_slots(), 2)

    async def test_a_job_takes_up_a_slot_whether_or_not_its_been_picked_up(self):
        self.machine()
        task = self.waiting_job()
        await asyncio.sleep(0)
        self.assertEqual(self.hub.free_slots(), 1)
        task.cancel()

    async def test_a_job_nobody_picks_up_doesnt_hold_up_the_feature(self):
        task = self.waiting_job()
        await asyncio.sleep(0)
        for job in self.hub.jobs.values():
            job.last_heard = 0
        self.hub.check_silent()
        self.assertEqual((await task).stop_reason, lanes.MACHINE_GONE[0])

    async def test_a_machine_that_goes_quiet_doesnt_either(self):
        task = self.waiting_job()
        await asyncio.sleep(0)
        job = next(iter(self.hub.jobs.values()))
        self.hub.waiting.remove(job)
        job.worker = "pc"
        job.last_heard = 0
        self.hub.check_silent()
        self.assertEqual((await task).stop_reason, lanes.MACHINE_GONE[1])
        self.assertEqual(self.hub.jobs, {})

    async def test_a_quiet_moment_is_fine(self):
        task = self.waiting_job()
        await asyncio.sleep(0)
        self.hub.check_silent()
        self.assertFalse(task.done())
        task.cancel()

    async def test_carrying_on_goes_back_to_the_machine_with_the_conversation(self):
        self.machine()
        self.hub.sessions["demo"] = "pc"
        task = self.waiting_job(session="abc")
        await asyncio.sleep(0)
        job = next(iter(self.hub.jobs.values()))
        self.assertEqual((job.worker, job.details["session"]), ("pc", "abc"))
        task.cancel()

    async def test_if_that_machine_has_gone_it_starts_over_anywhere(self):
        self.hub.sessions["demo"] = "pc"
        task = self.waiting_job(session="abc")
        await asyncio.sleep(0)
        job = next(iter(self.hub.jobs.values()))
        self.assertEqual((job.worker, job.details["session"]), ("", None))
        task.cancel()


class Tokens(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = pathlib.Path(folder.name) / "workers.json"
        path.write_text(json.dumps({"pc": {"token_sha256": hashlib.sha256(b"right").hexdigest(), "slots": 1}}), encoding="utf-8")
        patcher = mock.patch.object(worker_hub, "MACHINES", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hub = worker_hub.WorkerHub(pathlib.Path(folder.name), None, None, None)

    def who(self, header):
        return self.hub._who(mock.Mock(headers={"authorization": header}))

    def test_the_right_token_says_which_machine(self):
        self.assertEqual(self.who("Bearer right"), "pc")

    def test_anything_else_is_nobody(self):
        for header in ("Bearer wrong", "Bearer ", "", "right"):
            self.assertIsNone(self.who(header), header)


class Attempts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.shop = workshop.Workshop(mock.Mock(), None, mock.Mock(), lambda: ())
        self.shop.governor.why_not_build.return_value = None
        self.shop.hub = mock.Mock()
        self.shop.hub.attempt = mock.AsyncMock()
        self.ask = mock.AsyncMock(return_value=llm.Result("", None, "s", 0.0, False, "end_turn", 0.0))
        for patcher in (mock.patch.object(llm, "ask", self.ask), mock.patch.object(workshop, "ready_commit", return_value="abc"),
                        mock.patch.object(llm, "prompt_text", return_value="Be good.")):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def attempt(self, lane):
        return await self.shop._attempt("demo", pathlib.Path("/tmp/demo"), "Build it.", None, False, lane, "e_one", "early", 10, 1.0, ["Read"], None)

    async def test_claude_by_default(self):
        await self.attempt(None)
        self.assertIsNone(self.ask.await_args.kwargs["lane"])
        self.shop.hub.attempt.assert_not_awaited()

    async def test_another_model_gets_its_lane_and_its_note(self):
        lane = lanes.Lane(lanes.SELF_HOSTED, {}, note="No images. ")
        self.shop.lanes[lanes.SELF_HOSTED] = lane
        await self.attempt(lanes.SELF_HOSTED)
        self.assertIs(self.ask.await_args.kwargs["lane"], lane)
        self.assertEqual(self.ask.await_args.args[2], "No images. Build it.")

    async def test_another_machine_gets_everything_it_needs_and_no_model_runs_here(self):
        await self.attempt(lanes.REMOTE)
        self.ask.assert_not_awaited()
        details = self.shop.hub.attempt.await_args.args[2]
        self.assertEqual((details["prompt"], details["node"], details["max_turns"], details["system"]), ("Build it.", "e_one", 10, "Be good."))

    async def test_a_machine_going_away_puts_the_feature_back_in_the_queue(self):
        self.shop.hub.attempt.return_value = llm.Result("", None, "", 0.0, True, lanes.MACHINE_GONE[1], 0.0)
        self.shop.web_research.server.return_value = None
        with mock.patch.object(self.shop, "_prepare_tree", return_value=pathlib.Path(tempfile.gettempdir()) / "m21-unit"):
            shipped = await self.shop.build("demo", "A spec.", "e_one", "early", lane=lanes.REMOTE)
        self.assertIsNone(shipped)
        self.shop.governor.record_gate_result.assert_not_called()


class Version(unittest.TestCase):
    def test_it_stays_the_same_until_the_code_changes(self):
        self.assertEqual(worker_hub.code_version(), worker_hub.code_version())


if __name__ == "__main__":
    unittest.main()
