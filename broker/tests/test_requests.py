"""What happens to what players ask for. Needs the agent's libraries, so it runs in the agent's image."""
import asyncio
import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from orchestrator import feedback, llm, main, progression, voice


def result(data=None, is_error=False):
    return llm.Result("", data, "", 0.0, is_error, "", 0.0)


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        (self.folder / "persona.md").write_text("A keeper.", encoding="utf-8")
        (self.folder / "persona_name.txt").write_text("Keeper", encoding="utf-8")
        (self.folder / "features").mkdir()
        graph = progression.from_direction("A goal.", [{"id": "e_one", "stage": "early", "name": "One", "requires": [], "opens_with": "x", "holds": "y"}])
        progression.save(self.folder / "progression.json", graph)
        for patcher in (mock.patch.object(main, "STATE", self.folder), mock.patch.object(main, "OPENING", self.folder / "opening.json"),
                        mock.patch.object(main, "PROGRESSION", self.folder / "progression.json"),
                        mock.patch.object(voice, "BIBLE", self.folder), mock.patch.object(voice, "FEATURES", self.folder / "features")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ask = mock.AsyncMock()
        patcher = mock.patch.object(llm, "ask", self.ask)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.agent = self.make_agent({})

    def make_agent(self, saved):
        """Everything but the connections to the game and the broker."""
        agent = main.Agent.__new__(main.Agent)
        agent.governor = mock.Mock()
        agent.governor.why_not_build.return_value = None
        agent.governor.builders_allowed.return_value = 2
        agent.governor.small_builders_allowed.return_value = 1
        agent.bridge = mock.Mock()
        agent.bridge.whisper = mock.AsyncMock()
        agent.bridge.call = mock.AsyncMock(return_value={})
        agent.workshop = mock.Mock()
        agent.workshop.changes = 0
        agent.workshop.build = mock.AsyncMock(return_value=True)
        agent.research = mock.Mock()
        agent.interviews = {}
        agent.sort_wanted = asyncio.Event()
        agent.wake_director = asyncio.Event()
        agent.planning = False
        agent.last_planned = 0
        agent.director_rest_until = 0
        agent.reached = []
        agent.state = {"direction_chosen": True, "briefs": {}, "released": [], "intents": {}, "intent_count": 0, "private_chats": {}, "requests": {}, "sorted_up_to": 0,
                       "director_saw": 0, "notices": {}, "queue": [], "in_flight": {}, "border_open": True, **saved}
        agent.requests = feedback.Requests(self.folder / "intents.jsonl", agent.state["requests"])
        agent.queue = agent.state["queue"]
        agent.building = agent.state["in_flight"]
        return agent

    def asked(self, *wants, player="Dana"):
        self.agent.record_intents([{"player": player, "wants": want, "personal_advantage": False} for want in wants])

    def status(self, number):
        return self.agent.requests.status(number)

    def told(self, player="Dana"):
        return [call.args[1] for call in self.agent.bridge.whisper.await_args_list if call.args[0] == player]

    def answers(self, role, data):
        """The chosen role answers with this, and the one that writes news gives a plain line."""
        async def respond(governor, name, prompt, **options):
            return result(data) if name == role else result({"reply": "the news"})
        self.ask.side_effect = respond


class Sorting(Base):
    async def test_a_change_only_counts_if_something_really_changed(self):
        self.asked("copper is too rare")
        self.answers("sorter", {"decisions": [{"numbers": [1], "action": "changed"}]})
        await self.agent.sort_requests()
        self.assertIsNone(self.status(1))
        self.assertEqual(self.told(), [])

    async def test_a_real_change_is_done_and_they_hear_about_it(self):
        self.asked("skip the night with half the players")

        async def respond(governor, name, prompt, **options):
            if name == "sorter":
                self.agent.workshop.changes += 1
                return result({"decisions": [{"numbers": [1], "action": "changed"}]})
            self.assertIn('"outcome": "done"', prompt)
            return result({"reply": "the news"})
        self.ask.side_effect = respond
        await self.agent.sort_requests()
        self.assertEqual(self.status(1), feedback.DONE)
        self.assertEqual(self.told(), ["§dKeeper§r: the news"])

    async def test_a_small_ask_goes_to_the_front_for_a_small_builder(self):
        self.agent.queue.append({"id": "big_thing", "node": "e_one", "spec": "big"})
        self.asked("use for core samples", "core samples are useless")
        self.answers("sorter", {"decisions": [{"numbers": [1, 2], "action": "small", "id": "sample_use", "node": "e_one", "spec": "Give them a use."}]})
        await self.agent.sort_requests()
        self.assertEqual(self.agent.queue[0], {"id": "sample_use", "node": "e_one", "spec": "Give them a use.", "answers": [1, 2], "small": True})
        self.assertEqual((self.status(1), self.status(2)), (feedback.BUILDING, feedback.BUILDING))
        self.assertEqual(len(self.told()), 1, "one message for both")

    async def test_a_small_job_with_a_bad_id_or_node_goes_to_the_director(self):
        self.asked("one", "two")
        self.answers("sorter", {"decisions": [{"numbers": [1], "action": "small", "id": "../../etc", "node": "e_one", "spec": "x"},
                                              {"numbers": [2], "action": "small", "id": "fine", "node": "nowhere", "spec": "x"}]})
        await self.agent.sort_requests()
        self.assertEqual(self.agent.queue, [])
        self.assertEqual((self.status(1), self.status(2)), (None, None))

    async def test_a_number_it_was_not_given_is_ignored(self):
        self.asked("one")
        self.answers("sorter", {"decisions": [{"numbers": [99], "action": "small", "id": "fine", "node": "e_one", "spec": "x"}]})
        await self.agent.sort_requests()
        self.assertEqual(self.agent.queue, [])

    async def test_if_sorting_fails_the_director_still_gets_them(self):
        self.asked("one")
        self.ask.return_value = result(is_error=True)
        await self.agent.sort_requests()
        self.assertEqual(self.agent.state["sorted_up_to"], 1)
        self.assertEqual([entry["number"] for entry in self.agent.requests.undecided()], [1])

    async def test_it_sees_each_request_once(self):
        self.asked("one")
        self.answers("sorter", {"decisions": []})
        await self.agent.sort_requests()
        await self.agent.sort_requests()
        self.assertEqual(self.ask.await_count, 1)

    async def test_nothing_happens_before_there_is_a_direction(self):
        self.agent.state["direction_chosen"] = False
        self.asked("one")
        await self.agent.sort_requests()
        self.ask.assert_not_awaited()
        self.assertEqual(self.agent.state["sorted_up_to"], 0)


class Directing(Base):
    def plan_answer(self, features=(), decisions=()):
        self.answers("director", {"features": list(features), "decisions": list(decisions)})

    async def test_nothing_drops_off_however_many_there_are(self):
        self.asked(*[f"request {number}" for number in range(1, 61)])
        self.plan_answer()
        await self.agent.next_features()
        prompt = next(call.args[2] for call in self.ask.await_args_list if call.args[1] == "director")
        self.assertIn("request 1\"", prompt)
        self.assertIn("request 60\"", prompt)

    async def test_what_someone_asked_for_goes_first(self):
        self.agent.queue.append({"id": "already_queued", "node": "e_one", "spec": "x"})
        self.asked("a map")
        self.plan_answer([{"id": "plain", "node": "e_one", "spec": "x"}, {"id": "map", "node": "e_one", "spec": "x", "answers": [1]}])
        await self.agent.plan()
        self.assertEqual([feature["id"] for feature in self.agent.queue], ["map", "already_queued", "plain"])
        self.assertEqual(self.status(1), feedback.BUILDING)
        self.assertFalse(self.agent.planning)
        self.assertTrue(self.agent.wake_director.is_set())

    async def test_it_never_asks_for_the_same_thing_twice(self):
        self.agent.queue.append({"id": "same", "node": "e_one", "spec": "x"})
        self.agent.building["also_same"] = {"id": "also_same"}
        self.plan_answer([{"id": "same", "node": "e_one", "spec": "y"}, {"id": "also_same", "node": "e_one", "spec": "y"}])
        self.assertEqual(await self.agent.next_features(), [])

    async def test_a_decision_is_kept_and_they_hear_why(self):
        self.asked("a nuke", "a boat", "a map")
        seen = []

        async def respond(governor, name, prompt, **options):
            if name == "director":
                return result({"features": [], "decisions": [{"number": 1, "outcome": "declined", "why": "Too much."}, {"number": 2, "outcome": "already_there", "why": "Vanilla."},
                                                             {"number": 3, "outcome": "later", "why": "After the kiln."}]})
            seen.append(prompt)
            return result({"reply": "the news"})
        self.ask.side_effect = respond
        await self.agent.next_features()
        self.assertEqual((self.status(1), self.status(2), self.status(3)), (feedback.DECLINED, feedback.DONE, feedback.LATER))
        self.assertEqual(len(seen), 1)
        for word in ("Too much.", "Vanilla.", "After the kiln."):
            self.assertIn(word, seen[0])
        self.assertEqual([entry["number"] for entry in self.agent.requests.undecided()], [3], "later comes back, and the others don't")

    async def test_they_only_hear_later_once(self):
        self.asked("a map")
        self.plan_answer(decisions=[{"number": 1, "outcome": "later", "why": "After the kiln."}])
        await self.agent.next_features()
        self.assertEqual(len(self.told()), 1)
        await self.agent.next_features()
        self.assertEqual(len(self.told()), 1)

    async def test_a_failed_call_decides_nothing_and_it_asks_again(self):
        self.asked("a map")
        self.ask.return_value = result(is_error=True)
        await self.agent.plan()
        self.assertEqual(self.agent.state["director_saw"], 0)
        self.assertEqual(self.status(1), None)


class WhenToPlan(Base):
    def setUp(self):
        super().setUp()
        self.agent.queue.append({"id": "big", "node": "e_one", "spec": "x"})

    def asked(self, *wants, player="Dana"):
        super().asked(*wants, player=player)
        self.agent.sort_wanted.clear()  # As it would be once they've been sorted.

    def test_new_requests_wait_at_most_a_while(self):
        self.asked("a map")
        self.agent.last_planned = time.time() - 60
        self.assertFalse(self.agent.should_plan())
        self.agent.last_planned = time.time() - main.FEEDBACK_PLAN_SECONDS - 1
        self.assertTrue(self.agent.should_plan())

    def test_no_news_means_no_extra_calls(self):
        self.agent.last_planned = 0
        self.assertFalse(self.agent.should_plan())
        self.asked("a map")
        self.agent.state["director_saw"] = 1
        self.assertFalse(self.agent.should_plan())

    def test_one_call_at_a_time(self):
        self.asked("a map")
        self.agent.planning = True
        self.assertFalse(self.agent.should_plan())

    def test_it_waits_while_requests_are_being_sorted(self):
        self.asked("a map")
        self.agent.sort_wanted.set()
        self.assertFalse(self.agent.should_plan())

    def test_running_out_of_big_work_is_a_reason_even_with_small_jobs_going(self):
        self.agent.queue.clear()
        self.agent.building["small"] = {"id": "small", "small": True}
        self.assertTrue(self.agent.should_plan())
        self.agent.director_rest_until = time.time() + 100
        self.assertFalse(self.agent.should_plan())


class Building(Base):
    async def settle(self):
        await asyncio.gather(*[task for task in asyncio.all_tasks() if task is not asyncio.current_task()])

    async def test_small_jobs_have_their_own_slots(self):
        self.agent.queue.extend([{"id": "big_one", "node": "e_one", "spec": "x"}, {"id": "big_two", "node": "e_one", "spec": "x"}, {"id": "big_three", "node": "e_one", "spec": "x"},
                                 {"id": "small_one", "node": "e_one", "spec": "x", "small": True}, {"id": "small_two", "node": "e_one", "spec": "x", "small": True}])
        self.agent.start_work()
        self.assertEqual(sorted(self.agent.building), ["big_one", "big_two", "small_one"])
        self.assertEqual([feature["id"] for feature in self.agent.queue], ["big_three", "small_two"])
        await self.settle()
        self.assertEqual(self.agent.building, {})
        small = {call.args[0]: call.kwargs["small"] for call in self.agent.workshop.build.await_args_list}
        self.assertEqual(small, {"big_one": False, "big_two": False, "small_one": True})

    async def test_two_jobs_on_one_feature_never_overlap(self):
        self.agent.building["same"] = {"id": "same", "small": True}
        self.agent.queue.append({"id": "same", "node": "e_one", "spec": "x", "small": True})
        self.agent.governor.small_builders_allowed.return_value = 5
        self.agent.start_work()
        self.assertEqual(len(self.agent.queue), 1)

    async def test_it_ships_and_they_hear_about_it_even_offline(self):
        self.asked("a map")
        self.agent.requests.mark(1, feedback.BUILDING, feature="map")
        feature = self.folder / "tree" / "mods/genesis/features/map"
        feature.mkdir(parents=True)
        (feature / "feature.json").write_text("{}", encoding="utf-8")
        self.ask.return_value = result({"reply": "the news"})
        self.agent.open_world = mock.AsyncMock()
        self.agent.bridge.whisper.side_effect = RuntimeError("Dana isn't online")
        await self.agent.on_released("map", self.folder / "tree")
        self.assertEqual(self.status(1), feedback.DONE)
        self.assertEqual(self.agent.state["notices"], {"Dana": ["§dKeeper§r: the news"]})

        self.agent.bridge.whisper.side_effect = None
        self.agent.bridge.whisper.reset_mock()
        await self.agent.deliver_waiting("Dana")
        self.assertEqual(self.told(), ["§dKeeper§r: the news"])
        self.assertEqual(self.agent.state["notices"], {})

    async def test_a_plain_message_goes_out_if_the_news_cannot_be_written(self):
        self.asked("a map")
        self.ask.side_effect = RuntimeError("no")
        await self.agent.send_news([(self.agent.requests.all()[0], feedback.DONE, "")])
        self.assertIn("a map: done", self.told()[0])

    async def test_a_failed_job_goes_back_to_the_director_soon(self):
        self.asked("a map")
        self.agent.state["director_saw"] = 1
        self.agent.requests.mark(1, feedback.BUILDING, feature="map")
        self.agent.building["map"] = {"id": "map", "node": "e_one", "spec": "x"}
        self.agent.workshop.build.return_value = False
        with mock.patch.object(main.progression, "stage_of", return_value="early"):
            await self.agent.build_one(self.agent.building["map"])
        self.assertIsNone(self.status(1))
        self.assertEqual(self.agent.requests.unanswered_after(self.agent.state["director_saw"])[0]["number"], 1)

    async def test_a_job_that_has_to_pause_comes_back(self):
        feature = {"id": "map", "node": "e_one", "spec": "x"}
        self.agent.building["map"] = feature
        self.agent.workshop.build.return_value = None
        await self.agent.build_one(feature)
        self.assertEqual(self.agent.queue, [feature])

    async def test_work_is_saved_for_a_restart(self):
        feature = {"id": "map", "node": "e_one", "spec": "x"}
        self.agent.building["map"] = feature
        self.agent.queue.append({"id": "next", "node": "e_one", "spec": "x"})
        self.agent.save()
        saved = json.loads((self.folder / "opening.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["in_flight"], {"map": feature})
        self.assertEqual(saved["queue"], [{"id": "next", "node": "e_one", "spec": "x"}])


if __name__ == "__main__":
    unittest.main()
