"""Moving roles off Claude: which ones can go, what happens when that model fails, and art staying with Opus whatever builds around it."""
import os
import pathlib
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from orchestrator import lanes, llm, model_bridge, workshop
from orchestrator.governor import Governor

ANSWER = llm.Result("hi", {"say": "hi"}, "s", 0.0, False, "end_turn", 0.0)
NO_ANSWER = llm.Result("", None, "", 0.0, True, "api_error", 0.0)
LANE = lanes.Lane(lanes.SELF_HOSTED, {})
FEATURE = "mods/genesis/features/demo"


class WhichRolesCanMove(unittest.TestCase):
    def test_only_what_the_owner_listed(self):
        with mock.patch.dict(os.environ, {"AGENT_SELFHOSTED_ROLES": "dm,builder"}):
            self.assertEqual(lanes.SelfHosted().roles, {"dm", "builder"})

    def test_nothing_that_watches_over_the_rest_or_makes_art(self):
        with mock.patch.dict(os.environ, {"AGENT_SELFHOSTED_ROLES": "director,director_quick,direction,reviewer,artist,modeller,icon,researcher"}):
            self.assertEqual(lanes.SelfHosted().roles, set())

    def test_art_is_made_by_opus(self):
        for kind in workshop.ART_KINDS:
            self.assertEqual(llm.ROLES[kind]["model"], "claude-opus-5-5")

    def test_the_director_is_opus(self):
        self.assertEqual(llm.ROLES["director"]["model"], "claude-opus-5-5")

    def test_none_by_default(self):
        with mock.patch.dict(os.environ, clear=True):
            self.assertEqual(lanes.SelfHosted().roles, set())
            self.assertFalse(lanes.SelfHosted().takes("builder"))

    def test_it_only_takes_them_while_its_up(self):
        with mock.patch.dict(os.environ, {"AGENT_SELFHOSTED_URL": "http://gpu/v1", "AGENT_SELFHOSTED_BUILDERS": "1", "AGENT_SELFHOSTED_ROLES": "dm"}):
            hosted = lanes.SelfHosted()
        self.assertTrue(hosted.takes("dm"))
        self.assertFalse(hosted.takes("builder"))
        hosted.bridge.failures = model_bridge.FAILURES_TO_BE_DOWN
        hosted.bridge.failed_at = time.monotonic()
        self.assertFalse(hosted.takes("dm"))
        self.assertIs(hosted.is_up(), False)


class Budgets(unittest.IsolatedAsyncioTestCase):
    async def budget_with(self, lane):
        seen = {}

        async def query(prompt, options):
            seen["budget"] = options.max_budget_usd
            return
            yield

        with mock.patch.object(llm, "query", query):
            await llm._ask(mock.Mock(), "builder", "Build it.", system="Be good.", budget=5.0, lane=lane)
        return seen["budget"]

    async def test_claude_keeps_to_its_budget(self):
        self.assertEqual(await self.budget_with(None), 5.0)

    async def test_another_model_isnt_cut_off_by_claudes_prices(self):
        self.assertIsNone(await self.budget_with(LANE))


class Asking(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = mock.AsyncMock(return_value=ANSWER)
        for patcher in (mock.patch.object(llm, "_ask", self.calls), mock.patch.dict(llm.MOVED, {"dm": LANE, "builder": LANE}, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_a_moved_role_goes_to_its_lane(self):
        await llm.ask(None, "dm", "hello", schema={})
        self.assertIs(self.calls.await_args.kwargs["lane"], LANE)

    async def test_the_rest_stay_on_claude(self):
        await llm.ask(None, "director", "plan")
        self.assertIsNone(self.calls.await_args.kwargs["lane"])

    async def test_while_the_model_is_down_it_goes_straight_to_claude(self):
        with mock.patch.dict(llm.MOVED, {"dm": lanes.Lane(lanes.SELF_HOSTED, {}, is_down=lambda: True)}):
            await llm.ask(None, "dm", "hello")
        self.assertEqual(self.calls.await_count, 1)
        self.assertIsNone(self.calls.await_args.kwargs["lane"])

    async def test_a_player_still_gets_an_answer_when_it_fails(self):
        self.calls.side_effect = [NO_ANSWER, ANSWER]
        self.assertIs(await llm.ask(None, "dm", "hello"), ANSWER)
        self.assertIsNone(self.calls.await_args.kwargs["lane"])

    async def test_or_when_it_crashes(self):
        self.calls.side_effect = [RuntimeError("no"), ANSWER]
        self.assertIs(await llm.ask(None, "dm", "hello"), ANSWER)

    async def test_or_when_it_doesnt_answer_in_the_right_form(self):
        self.calls.side_effect = [llm.Result("hi", None, "s", 0.0, False, "end_turn", 0.0), ANSWER]
        self.assertIs(await llm.ask(None, "dm", "hello", schema={"type": "object"}), ANSWER)

    async def test_a_builder_doesnt_silently_redo_its_work_on_claude(self):
        self.calls.return_value = NO_ANSWER
        self.assertIs(await llm.ask(None, "builder", "build"), NO_ANSWER)
        self.assertEqual(self.calls.await_count, 1)


class TalkingWhenThePlanRunsOut(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("orchestrator.governor.STATE_ROOT", pathlib.Path(folder)):
            self.governor = Governor()
        self.governor._save = lambda: None
        self.governor.record_rate_limit("rejected", 9999999999)

    def test_on_the_plan_it_stops(self):
        self.assertTrue(self.governor.why_not_speak())

    def test_on_another_model_it_carries_on(self):
        self.governor.talks_on_plan = False
        self.assertIsNone(self.governor.why_not_speak())

    def test_building_still_waits_because_review_and_art_need_claude(self):
        self.governor.talks_on_plan = False
        self.assertTrue(self.governor.why_not_build())

    def test_the_kill_switch_stops_it_regardless(self):
        self.governor.talks_on_plan = False
        self.governor.owner_stopped = True
        self.assertEqual(self.governor.why_not_speak(), "kill switch")


class Art(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.tree = self.root / "tree"
        self.folder = self.tree / FEATURE
        (self.folder / "assets/textures").mkdir(parents=True)
        (self.folder / "assets/textures/old.png").write_bytes(b"shipped")
        (self.folder / "assets/lang.json").write_text("{}", encoding="utf-8")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first"]):
            subprocess.run(["git", *args], cwd=self.tree, check=True, capture_output=True)
        self.shop = workshop.Workshop(mock.Mock(**{"why_not_build.return_value": None}), mock.AsyncMock(), mock.Mock())
        self.shop.art_made = {}
        self.ask = mock.AsyncMock(return_value=ANSWER)
        for patcher in (mock.patch.object(llm, "ask", self.ask), mock.patch.object(workshop, "ART_MADE", self.root / "made.json"),
                        mock.patch.object(llm, "prompt_text", return_value="Be good."), mock.patch.dict(llm.MOVED, {"builder": LANE, "small_builder": LANE}, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def draw(self, name, content=b"art"):
        (self.folder / "assets/textures" / name).write_bytes(content)

    async def finish(self):
        return await self.shop._finish_art("demo", "A spec.", self.tree, "e_one", None)

    async def attempt(self, role_is_small=False, tools=("Read",)):
        return await self.shop._attempt("demo", self.tree, "Build it.", None, role_is_small, None, "e_one", "early", 10, 1.0, list(tools), None)

    async def test_git_and_this_agree_on_what_shipped_art_is(self):
        path = "assets/textures/old.png"
        self.assertEqual(workshop._art_in(self.folder)[path], workshop._shipped_art(self.tree, "demo")[path])

    async def test_text_for_players_isnt_art(self):
        self.assertNotIn("assets/lang.json", workshop._art_in(self.folder))

    async def test_nothing_new_means_opus_isnt_asked(self):
        self.assertTrue(await self.finish())
        self.ask.assert_not_awaited()

    async def test_what_a_builder_drew_goes_to_opus(self):
        self.draw("mine.png")
        self.assertTrue(await self.finish())
        self.assertEqual(self.ask.await_args.args[1], "artist")
        self.assertIsNone(self.ask.await_args.kwargs.get("lane"))
        self.assertIn("assets/textures/mine.png", self.ask.await_args.args[2])
        self.assertNotIn("old.png", self.ask.await_args.args[2])

    async def test_changing_shipped_art_goes_to_opus_too(self):
        self.draw("old.png", b"changed")
        await self.finish()
        self.assertIn("assets/textures/old.png", self.ask.await_args.args[2])

    async def test_it_only_gets_asked_once_about_each_thing(self):
        self.draw("mine.png")
        await self.finish()
        self.ask.reset_mock()
        await self.finish()
        self.ask.assert_not_awaited()

    async def test_changing_it_afterwards_sends_it_back(self):
        self.draw("mine.png")
        await self.finish()
        self.ask.reset_mock()
        self.draw("mine.png", b"the builder again")
        await self.finish()
        self.ask.assert_awaited_once()

    async def test_if_the_plan_is_out_it_waits(self):
        self.draw("mine.png")
        self.ask.return_value = NO_ANSWER
        self.shop.governor.why_not_build.return_value = "paused until limits reset"
        self.assertFalse(await self.finish())

    async def test_any_other_failure_doesnt_hold_it_up_but_it_gets_asked_again(self):
        self.draw("mine.png")
        self.ask.return_value = NO_ANSWER
        self.assertTrue(await self.finish())
        await self.finish()
        self.assertEqual(self.ask.await_count, 2)

    async def test_what_opus_made_through_the_tool_isnt_redone(self):
        async def paints(*args, **kwargs):
            self.draw("opus.png")
            return ANSWER
        self.ask.side_effect = paints
        await self.shop._make_art("artist", "Draw it.", "demo", self.tree, "e_one", None)
        self.ask.reset_mock()
        self.ask.side_effect = None
        self.assertTrue(await self.finish())
        self.ask.assert_not_awaited()

    async def test_a_builders_own_art_doesnt_pass_because_opus_made_something_else(self):
        self.draw("mine.png")

        async def paints(*args, **kwargs):
            self.draw("opus.png")
            return ANSWER
        self.ask.side_effect = paints
        await self.shop._make_art("artist", "Draw it.", "demo", self.tree, "e_one", None)
        self.ask.reset_mock()
        self.ask.side_effect = None
        await self.finish()
        self.assertIn("mine.png", self.ask.await_args.args[2])
        self.assertNotIn("opus.png", self.ask.await_args.args[2])

    async def test_it_survives_a_restart(self):
        self.draw("mine.png")
        await self.finish()
        self.ask.reset_mock()
        again = workshop.Workshop(self.shop.governor, mock.AsyncMock(), mock.Mock())
        with mock.patch.object(self.shop, "art_made", again.art_made):
            await self.finish()
        self.ask.assert_not_awaited()

    async def test_a_builder_on_another_model_gets_the_tool_and_not_the_helpers(self):
        with mock.patch.object(self.shop, "world_server"):
            await self.attempt()
        options = self.ask.await_args.kwargs
        self.assertIs(options["lane"], LANE)
        self.assertEqual(sorted(options["agents"]), ["coder"])
        self.assertIn(workshop.ART_TOOL, options["tools"])
        self.assertIn(workshop.ART_TOOL, options["allowed_tools"])
        self.assertIn("art", options["mcp_servers"])
        self.assertIn("make_art", self.ask.await_args.args[2])

    async def test_a_small_builder_on_another_model_gets_it_too(self):
        with mock.patch.object(self.shop, "world_server"):
            await self.attempt(role_is_small=True)
        self.assertIn(workshop.ART_TOOL, self.ask.await_args.kwargs["tools"])

    async def test_a_builder_on_claude_is_as_it_was(self):
        with mock.patch.dict(llm.MOVED, clear=True), mock.patch.object(self.shop, "world_server"):
            await self.attempt()
        options = self.ask.await_args.kwargs
        self.assertIsNone(options["lane"])
        self.assertEqual(sorted(options["agents"]), ["artist", "coder", "modeller"])
        self.assertNotIn(workshop.ART_TOOL, options["tools"])
        self.assertNotIn("art", options["mcp_servers"])
        self.assertEqual(self.ask.await_args.args[2], "Build it.")


if __name__ == "__main__":
    unittest.main()
