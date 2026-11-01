"""A model turning work away says nothing about what it was asked to build, so the build waits rather than being thrown away. Needs the
agent's libraries, so it runs in the agent's image.

Usage: python3 -m unittest broker.tests.test_model_outage
"""
import pathlib
import tempfile
import unittest
from unittest import mock

from orchestrator import lanes, llm, workshop


class Builds(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.shop = workshop.Workshop(mock.Mock(**{"why_not_build.return_value": None}), mock.AsyncMock(), mock.Mock())
        # What Claude Code does when the model refuses it: it raises, and there's no result at all.
        self.attempt = mock.AsyncMock(side_effect=RuntimeError("Claude Code returned an error result: API Error: 400"))
        for name, value in (("_prepare_tree", mock.Mock(return_value=pathlib.Path(folder.name))), ("_attempt", self.attempt)):
            patcher = mock.patch.object(self.shop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def on_a_model(self, **health):
        self.shop.lanes = {lanes.SELF_HOSTED: lanes.Lane(lanes.SELF_HOSTED, {}, **health)}

    async def build(self, lane=lanes.SELF_HOSTED):
        return await self.shop.build("demo", "A spec.", "e_one", "early", lane=lane)

    async def test_it_goes_back_in_the_queue_on_the_first_refusal(self):
        self.on_a_model(is_failing=lambda: True)
        self.assertIsNone(await self.build())
        self.attempt.assert_awaited_once()

    async def test_and_once_the_model_counts_as_down(self):
        self.on_a_model(is_down=lambda: True)
        self.assertIsNone(await self.build())

    async def test_a_failed_result_goes_back_too(self):
        self.on_a_model(is_failing=lambda: True)
        self.attempt.side_effect = None
        self.attempt.return_value = llm.Result("", None, "", 0.0, True, "error", 0.0)
        self.assertIsNone(await self.build())
        self.attempt.assert_awaited_once()

    async def test_with_the_model_fine_the_builders_failure_is_still_its_own(self):
        self.on_a_model()
        with self.assertRaises(RuntimeError):
            await self.build()

    async def test_on_claude_nothing_changes(self):
        with self.assertRaises(RuntimeError):
            await self.build(lane=None)


if __name__ == "__main__":
    unittest.main()
