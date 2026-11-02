"""Repair feedback survives interruptions; neither turn counts nor attempts decide a feature's fate."""
import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from broker.tests.test_batched_release import Base, git
from orchestrator import governor, ledger, llm, main, worker, workshop

PASS = {"result": "passed_gates", "screenshots": []}
APPROVED = {"approve": True, "serious": False, "problems": []}


class Recovery(Base):
    def setUp(self):
        super().setUp()
        self.shop.governor.why_not_build.return_value = None
        self.shop.web_research.server.return_value = None
        self.feature("demo")
        self.attempt = mock.AsyncMock(return_value=llm.Result("", None, "builder-session", 0, False, "end_turn", 0))
        self.review = mock.AsyncMock(return_value=APPROVED)
        self.gates = mock.AsyncMock(return_value=PASS)
        self.release = mock.AsyncMock(return_value={"result": "released"})
        for patch in (mock.patch.object(ledger, "FOLDER", self.root / "records"), mock.patch.object(ledger, "_open", {}),
                      mock.patch.object(ledger, "_loaded", False), mock.patch.object(self.shop, "_attempt", self.attempt),
                      mock.patch.object(self.shop, "_review", self.review), mock.patch.object(workshop, "checked_against_main", self.gates),
                      mock.patch.object(self.shop, "_release", self.release), mock.patch.object(self.shop, "_log_timing")):
            patch.start()
            self.addCleanup(patch.stop)

    async def build(self):
        return await self.shop.build("demo", "Make it work.", "e_one", "early", small=True)

    def saved(self):
        return json.loads(next((self.root / "records/runs").glob("*.json")).read_text())

    async def test_review_defects_keep_going_even_when_not_serious(self):
        self.review.side_effect = [{"approve": False, "serious": False, "problems": [f"Defect {i}"]} for i in range(8)] + [APPROVED]
        self.assertTrue(await self.build())
        self.assertEqual(self.attempt.await_count, 9)
        for i, call in enumerate(self.attempt.await_args_list[1:]):
            self.assertIn(f"Defect {i}", call.args[2])
            self.assertEqual(call.args[3], "builder-session")
        self.release.assert_awaited_once()

    async def test_gate_defects_keep_going_and_include_saved_diagnostics(self):
        failure = {"result": "blocked", "gate": "shadow", "reason": "Bad codec", "diagnostics": ["/workspace/reports/test/shadow.log"]}
        self.gates.side_effect = [failure] * 10 + [PASS]
        self.assertTrue(await self.build())
        self.assertEqual(self.attempt.await_count, 11)
        self.assertIn("/workspace/reports/test/shadow.log", self.attempt.await_args.args[2])

    async def test_reviewer_quota_resumes_review_without_rebuilding_after_restart(self):
        self.review.side_effect = [llm.ModelInterrupted("reviewer", "weekly limit", "review-session"), APPROVED]
        self.assertIsNone(await self.build())
        saved = self.saved()
        self.assertIsNone(saved["outcome"])
        self.assertEqual(saved["stage_now"], ledger.WAITING)
        self.assertEqual(saved["checkpoint"]["review_session"], "review-session")
        self.release.assert_not_awaited()
        ledger._open.clear()
        ledger._loaded = False
        self.assertTrue(await self.build())
        self.attempt.assert_awaited_once()
        self.assertEqual(self.review.await_args.kwargs["resume"], "review-session")
        self.assertEqual(self.gates.await_count, 2)

    async def test_changed_code_invalidates_the_old_review_session(self):
        self.review.side_effect = [llm.ModelInterrupted("reviewer", "connection closed", "old-session"), APPROVED]
        self.assertIsNone(await self.build())
        tree = workshop.TREES / "demo"
        (tree / "new.txt").write_text("Changed while paused")
        git("add", "-A", cwd=tree)
        git("commit", "-qm", "Changed", cwd=tree)
        self.assertTrue(await self.build())
        self.assertIsNone(self.review.await_args.kwargs["resume"])

    async def test_builder_session_survives_interruption(self):
        self.attempt.side_effect = [llm.ModelInterrupted("small_builder", "connection reset", "unfinished-session"),
                                    llm.Result("", None, "unfinished-session", 0, False, "end_turn", 0)]
        self.assertIsNone(await self.build())
        self.assertTrue(await self.build())
        self.assertEqual(self.attempt.await_args.args[3], "unfinished-session")

    async def test_failover_keeps_work_but_does_not_resume_a_session_on_another_machine(self):
        run = ledger.open_run("demo", "demo")
        run.data["checkpoint"] = {"step": "build", "session": "remote-only", "session_lane": "remote", "feedback": "Fix the codec."}
        self.assertTrue(await self.build())
        self.assertIsNone(self.attempt.await_args.args[3])
        self.assertIn("Fix the codec.", self.attempt.await_args.args[2])

    async def test_feedback_is_not_lost_when_usage_pauses_the_repair_loop(self):
        reason = "x" * 600 + " deepest cause"

        async def fail(*args, **kwargs):
            self.shop.governor.why_not_build.return_value = "usage reached"
            return {"result": "blocked", "gate": "shadow", "reason": reason}

        self.gates.side_effect = fail
        self.assertIsNone(await self.build())
        self.assertIsNone(self.saved()["outcome"])
        self.shop.governor.why_not_build.return_value = None
        self.gates.side_effect = None
        self.assertTrue(await self.build())
        self.assertIn(reason, self.attempt.await_args.args[2])

    async def test_checkpoint_cannot_replace_review_approval(self):
        run = ledger.open_run("demo", "demo")
        run.data["checkpoint"] = {"step": "verify", "approve": True, "attempt": 1}
        self.review.side_effect = [llm.ModelInterrupted("reviewer", "offline")]
        self.assertIsNone(await self.build())
        self.gates.assert_awaited_once()
        self.review.assert_awaited_once()
        self.release.assert_not_awaited()


class Calls(unittest.IsolatedAsyncioTestCase):
    async def test_every_role_has_unlimited_turns_and_a_larger_buffer(self):
        seen = []

        async def query(**kwargs):
            seen.append(kwargs["options"])
            if False:
                yield

        with mock.patch.object(llm, "query", query), mock.patch.object(llm, "prompt_text", return_value="Prompt"):
            for role in llm.ROLES:
                await llm._ask(mock.Mock(), role, "Start")
        self.assertEqual(len(seen), len(llm.ROLES))
        self.assertTrue(all(option.max_turns is None and option.max_buffer_size == 16 * 1024 * 1024 for option in seen))

    async def test_sdk_quota_exception_keeps_session_and_pauses_governor(self):
        async def query(**kwargs):
            yield types.SimpleNamespace(data={"session_id": "sdk-session"})
            raise RuntimeError("You've hit your limit · resets Nov 3, 12pm (UTC)")

        gov = mock.Mock()
        with mock.patch.object(llm, "query", query), mock.patch.object(llm, "prompt_text", return_value="Prompt"):
            with self.assertRaises(llm.ModelInterrupted) as caught:
                await llm._ask(gov, "reviewer", "Review")
        self.assertEqual(caught.exception.session_id, "sdk-session")
        gov.record_rate_limit.assert_called_once_with("rejected", None)

    async def test_stream_overflow_is_a_recoverable_interruption(self):
        async def query(**kwargs):
            raise RuntimeError("JSON message exceeded maximum buffer size")
            yield

        with mock.patch.object(llm, "query", query):
            with self.assertRaises(llm.ModelInterrupted):
                await llm._ask(mock.Mock(), "reviewer", "Review")

    async def test_quota_inside_an_sdk_exception_group_is_recoverable(self):
        async def query(**kwargs):
            raise ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("You've hit your weekly limit")])
            yield

        with mock.patch.object(llm, "query", query):
            with self.assertRaises(llm.ModelInterrupted):
                await llm._ask(mock.Mock(), "reviewer", "Review")

    async def test_remote_worker_returns_partial_work_and_quota_information(self):
        hub = mock.Mock()
        hub.post.return_value = (200, {})
        runner = worker.Worker(hub, None)

        async def interrupted(meter, *args, **kwargs):
            meter.record_rate_limit("rejected", 500000)
            raise llm.ModelInterrupted("builder", "weekly limit", "remote-session")

        token = ledger.ACTIVE.set(None)
        try:
            with mock.patch.object(runner, "_sync", return_value=pathlib.Path("/tmp/demo")), \
                    mock.patch.object(runner, "_is_new", return_value=True), mock.patch.object(runner, "_upload") as upload, \
                    mock.patch.object(workshop, "ready_commit", return_value="partial-commit"), \
                    mock.patch.object(workshop, "_tools_for"), mock.patch.object(runner, "_world_server"), \
                    mock.patch.object(llm, "ask", interrupted):
                await runner.run({"id": "job", "feature_id": "demo", "prompt": "Build", "system": "Prompt", "node": "e_one"})
        finally:
            ledger.ACTIVE.reset(token)
        upload.assert_called_once_with("job", "partial-commit")
        body = hub.post.call_args.args[1]
        self.assertEqual(body["commit"], "partial-commit")
        self.assertEqual(body["session_id"], "remote-session")
        self.assertEqual(body["rate_limits"], [["rejected", 500000]])
        self.assertTrue(body["is_error"])

    async def test_incomplete_review_is_retried_without_sending_fake_defects_to_builder(self):
        shop = workshop.Workshop(mock.Mock(), mock.AsyncMock(), mock.Mock())
        with mock.patch.object(workshop, "changes_to_others", return_value=""), mock.patch.object(llm, "ask", mock.AsyncMock(return_value=llm.Result("", None, "s", 0, True, "no_result", 0))):
            with self.assertRaises(llm.ModelInterrupted) as caught:
                await shop._review("Spec", "demo", pathlib.Path("/tmp/demo"), [])
        self.assertEqual(caught.exception.role, "reviewer")


class Pausing(unittest.TestCase):
    def test_the_builders_own_gate_tool_also_exposes_the_diagnostic_files(self):
        answer = {"result": "blocked", "gate": "shadow", "reason": "Bad codec", "diagnostics": ["/workspace/reports/run/shadow.log"]}
        self.assertIn("/workspace/reports/run/shadow.log", workshop._verdict(answer, ["passed_gates"]))

    def test_fallback_quota_pause_does_not_shorten_a_known_weekly_reset(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(governor, "STATE_ROOT", pathlib.Path(folder)), mock.patch.object(governor.time, "time", return_value=100):
            gov = governor.Governor()
            gov.record_rate_limit("rejected", 500000)
            gov.record_rate_limit("rejected", None)
            self.assertEqual(gov.state["paused_until"], 500000)

    def test_scheduler_gives_other_features_the_slot_during_backoff(self):
        agent = mock.Mock()
        waiting = {"id": "wait", "small": True, "retry_after": 200}
        ready = {"id": "ready", "small": True}
        agent.queue, agent.building = [waiting, ready], {}
        agent.governor.small_builders_allowed.return_value = 1
        agent.build_one = mock.Mock()
        with mock.patch.object(main.time, "time", return_value=100), mock.patch.object(main.asyncio, "create_task"):
            main.Agent.start_work(agent)
        self.assertEqual(agent.queue, [waiting])
        self.assertEqual(agent.building, {"ready": ready})


if __name__ == "__main__":
    unittest.main()
