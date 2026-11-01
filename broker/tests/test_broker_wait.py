"""A request nobody's waiting for any more doesn't stay in the queue, and a broker that's down doesn't send builders off to fix anything."""
import asyncio
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from orchestrator import workshop


class Waiting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.requests = pathlib.Path(folder.name) / "requests"
        self.responses = pathlib.Path(folder.name) / "responses"
        self.responses.mkdir()
        for name, value in (("REQUESTS", self.requests), ("RESPONSES", self.responses), ("REQUEST_TIMEOUT", {"check": 0.1, "release": 1})):
            patcher = mock.patch.object(workshop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_a_quick_request_takes_itself_back_and_says_so(self):
        answer = await workshop.request("check", commit="abc")
        self.assertEqual(answer["result"], "blocked")
        self.assertIn("didn't answer", answer["reason"])
        self.assertEqual(list(self.requests.glob("*.json")), [])

    async def test_a_release_keeps_asking_with_only_one_request_waiting(self):
        task = asyncio.create_task(workshop.request("release", commit="abc"))
        seen = set()
        while len(seen) < 2:
            await asyncio.sleep(0.05)
            waiting = list(self.requests.glob("*.json"))
            self.assertLessEqual(len(waiting), 1)
            seen.update(path.stem for path in waiting)
        self.assertFalse(task.done())
        while not (waiting := list(self.requests.glob("*.json"))):
            await asyncio.sleep(0.01)
        request = json.loads(waiting[0].read_text(encoding="utf-8"))
        (self.responses / f"{request['id']}.json").write_text(json.dumps({"result": "released"}), encoding="utf-8")
        self.assertEqual((await asyncio.wait_for(task, 5))["result"], "released")


if __name__ == "__main__":
    unittest.main()
