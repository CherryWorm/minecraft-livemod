"""The theme is only ever chosen on the owner's go-ahead. Needs the agent's libraries, so it runs in the agent's image."""
import pathlib
import tempfile
import unittest
from unittest import mock

from orchestrator import main


def agent(**state):
    """Just what the decision needs. A whole agent would want a game to connect to."""
    made = main.Agent.__new__(main.Agent)
    made.state = {"direction_chosen": False, "briefs": {}, **state}
    made.choosing_direction = False
    made.choose_direction = mock.AsyncMock()
    return made


class TheGoAhead(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.control = pathlib.Path(folder.name)
        patcher = mock.patch.object(main, "CONTROL", self.control)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_nothing_happens_without_it(self):
        (self.control / "roster.txt").write_text("Dana\n", encoding="utf-8")
        waiting = agent(briefs={"Dana": {}}, first_finished_at=1)
        await waiting.maybe_choose_direction()
        waiting.choose_direction.assert_not_awaited()

    async def test_it_chooses_when_given(self):
        (self.control / "decide_now").touch()
        ready = agent()
        await ready.maybe_choose_direction()
        ready.choose_direction.assert_awaited_once()

    async def test_it_only_chooses_once(self):
        (self.control / "decide_now").touch()
        done = agent(direction_chosen=True)
        await done.maybe_choose_direction()
        done.choose_direction.assert_not_awaited()

    async def test_a_failed_try_can_go_again(self):
        (self.control / "decide_now").touch()
        ready = agent()
        ready.choose_direction.side_effect = RuntimeError("no")
        with self.assertRaises(RuntimeError):
            await ready.maybe_choose_direction()
        self.assertFalse(ready.choosing_direction)


if __name__ == "__main__":
    unittest.main()
