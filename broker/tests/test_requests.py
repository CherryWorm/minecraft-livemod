"""What happens to what players ask for. Needs the agent's libraries, so it runs in the agent's image."""
import asyncio
import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

from orchestrator import lanes, feedback, llm, main, progression, voice, workshop


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
        agent.bugs = mock.Mock(**{"of_player.return_value": [], "open_count.return_value": 0})
        agent.governor = mock.Mock()
        agent.governor.why_not_build.return_value = None
        agent.governor.builders_allowed.return_value = 2
        agent.governor.small_builders_allowed.return_value = 1
        agent.self_hosted = mock.Mock(lane=None, slots=0, **{"takes.return_value": False, "is_up.return_value": False})
        agent.hub = mock.Mock()
        agent.hub.free_slots.return_value = 0
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
        self.answers("director_quick", {"decisions": [{"numbers": [1], "action": "changed"}]})
        await self.agent.sort_requests()
        self.assertIsNone(self.status(1))
        self.assertEqual(self.told(), [])

    async def test_a_real_change_is_done_and_they_hear_about_it(self):
        self.asked("skip the night with half the players")

        async def respond(governor, name, prompt, **options):
            if name == "director_quick":
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
        self.answers("director_quick", {"decisions": [{"numbers": [1, 2], "action": "small", "id": "sample_use", "node": "e_one", "spec": "Give them a use.", "title": "a use for core samples"}]})
        await self.agent.sort_requests()
        self.assertEqual(self.agent.queue[0], {"id": "sample_use", "node": "e_one", "spec": "Give them a use.", "title": "a use for core samples", "answers": [1, 2], "small": True})
        self.assertEqual((self.status(1), self.status(2)), (feedback.BUILDING, feedback.BUILDING))
        self.assertEqual(len(self.told()), 1, "one message for both")

    async def test_it_cant_turn_anything_down(self):
        actions = main.SORTER_SCHEMA["properties"]["decisions"]["items"]["properties"]["action"]["enum"]
        self.assertNotIn(feedback.DECLINED, actions)
        self.asked("faster boats")
        self.answers("director_quick", {"decisions": [{"numbers": [1], "action": "declined", "why": "Boats stay as they are."}]})
        await self.agent.sort_requests()
        self.assertIsNone(self.status(1))
        self.assertEqual(self.told(), [], "nobody hears a no from here")
        self.assertEqual([entry["number"] for entry in self.agent.requests.undecided()], [1], "the director decides it")

    async def test_a_small_job_with_a_bad_id_or_node_goes_to_the_director(self):
        self.asked("one", "two")
        self.answers("director_quick", {"decisions": [{"numbers": [1], "action": "small", "id": "../../etc", "node": "e_one", "spec": "x"},
                                              {"numbers": [2], "action": "small", "id": "fine", "node": "nowhere", "spec": "x"}]})
        await self.agent.sort_requests()
        self.assertEqual(self.agent.queue, [])
        self.assertEqual((self.status(1), self.status(2)), (None, None))

    async def test_a_number_it_was_not_given_is_ignored(self):
        self.asked("one")
        self.answers("director_quick", {"decisions": [{"numbers": [99], "action": "small", "id": "fine", "node": "e_one", "spec": "x"}]})
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
        self.answers("director_quick", {"decisions": []})
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

    async def test_a_big_feature_from_a_request_waits_its_turn(self):
        self.agent.queue.append({"id": "already_queued", "node": "e_one", "spec": "x"})
        self.asked("a map")
        self.plan_answer([{"id": "plain", "node": "e_one", "spec": "x"}, {"id": "map", "node": "e_one", "spec": "x", "answers": [1]}])
        await self.agent.plan()
        self.assertEqual([feature["id"] for feature in self.agent.queue], ["already_queued", "plain", "map"])
        self.assertEqual(self.status(1), feedback.BUILDING)
        self.assertFalse(self.agent.planning)
        self.assertTrue(self.agent.wake_director.is_set())

    async def test_it_never_asks_for_the_same_thing_twice(self):
        self.agent.queue.append({"id": "same", "node": "e_one", "spec": "x"})
        self.agent.building["also_same"] = {"id": "also_same"}
        self.plan_answer([{"id": "same", "node": "e_one", "spec": "y"}, {"id": "also_same", "node": "e_one", "spec": "y"}])
        self.assertEqual(await self.agent.next_features(), [])

    async def test_most_of_what_gets_built_comes_from_the_plan(self):
        self.asked("one", "two", "three")
        self.plan_answer([{"id": "one", "node": "e_one", "spec": "x", "answers": [1]}, {"id": "own_idea", "node": "e_one", "spec": "x"}, {"id": "two", "node": "e_one", "spec": "x", "answers": [2]},
                          {"id": "three", "node": "e_one", "spec": "x", "answers": [3]}, {"id": "another_own_idea", "node": "e_one", "spec": "x"}])
        chosen = [feature["id"] for feature in await self.agent.next_features()]
        self.assertEqual(chosen, ["one", "own_idea", "two", "another_own_idea"])
        self.assertEqual((self.status(1), self.status(2), self.status(3)), (feedback.BUILDING, feedback.BUILDING, None), "the third comes back next time")

    async def test_what_the_owner_asks_for_is_marked_and_not_held_back(self):
        self.asked("one", "two", "three")
        lines = self.agent.requests.path.read_text(encoding="utf-8").splitlines()
        marked = {**json.loads(lines[2]), "owner_asked": True}
        self.agent.requests.path.write_text("\n".join([lines[0], lines[1], json.dumps(marked)]) + "\n", encoding="utf-8")
        self.plan_answer([{"id": "one", "node": "e_one", "spec": "x", "answers": [1]}, {"id": "two", "node": "e_one", "spec": "x", "answers": [2]}, {"id": "three", "node": "e_one", "spec": "x", "answers": [3]}])
        chosen = [feature["id"] for feature in await self.agent.next_features()]
        self.assertEqual(chosen, ["one", "two", "three"])
        prompt = next(call.args[2] for call in self.ask.await_args_list if call.args[1] == "director")
        self.assertEqual(prompt.count('"owner_asked": true'), 1)

    async def test_every_decision_is_made_knowing_the_others(self):
        self.asked("faster boats", "a minimap")
        self.agent.requests.mark(1, feedback.DECLINED, why="Boats stay as they are.")
        self.plan_answer()
        await self.agent.next_features()
        director = next(call for call in self.ask.await_args_list if call.args[1] == "director")
        self.assertIn("Boats stay as they are.", director.args[2])

        self.agent.state["sorted_up_to"] = 1
        self.answers("director_quick", {"decisions": []})
        self.ask.reset_mock()
        await self.agent.sort_requests()
        quick = self.ask.await_args_list[0]
        self.assertIn("Boats stay as they are.", quick.args[2], "the fast look sees them too")
        self.assertIn("You direct what gets built", quick.kwargs["system"], "and it has the same rules")
        self.assertNotIn("Dana", quick.args[2], "who asked doesn't come into it")

    async def test_a_decision_is_kept_and_they_hear_why(self):
        self.asked("a nuke", "a boat", "a map")
        seen = []

        async def respond(governor, name, prompt, **options):
            if name == "director":
                return result({"features": [], "decisions": [{"number": 1, "outcome": "declined", "why": "Too much.", "harm": "It would flatten every base."}, {"number": 2, "outcome": "already_there", "why": "Vanilla."},
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

    async def test_a_no_that_names_no_harm_doesnt_count(self):
        self.asked("a crafting screen")
        self.plan_answer(decisions=[{"number": 1, "outcome": "declined", "why": "It never crafts."}])
        await self.agent.next_features()
        self.assertIsNone(self.status(1))
        self.assertEqual(self.told(), [], "nobody hears it")
        self.assertEqual([entry["number"] for entry in self.agent.requests.undecided()], [1], "it comes back")

    async def test_the_harm_stays_with_the_decision_and_players_never_see_it(self):
        self.asked("a nuke")
        seen = []

        async def respond(governor, name, prompt, **options):
            if name == "director":
                return result({"features": [], "decisions": [{"number": 1, "outcome": "declined", "why": "Too much.", "harm": "It would flatten every base."}]})
            seen.append(prompt)
            return result({"reply": "the news"})
        self.ask.side_effect = respond
        await self.agent.next_features()
        self.assertIn("It would flatten every base.", self.agent.decided_so_far())
        self.assertNotIn("flatten", seen[0])
        self.assertNotIn("flatten", json.dumps(self.agent.requests.of_player("Dana")))

    async def test_something_only_the_owner_can_fix_really_reaches_them(self):
        self.asked("the codex text is unreadable")
        self.plan_answer(decisions=[{"number": 1, "outcome": "needs_owner", "why": "It's in the engine."}])
        await self.agent.next_features()
        self.assertEqual(self.status(1), feedback.NEEDS_OWNER)
        self.assertEqual(self.agent.requests.undecided(), [])
        owner = [json.loads(line) for line in (self.folder / "host_requests.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(owner[0]["feature"], "request 1")
        self.assertIn("the codex text is unreadable", owner[0]["requests"][0])
        self.assertEqual(len(self.told()), 1)

    def engine_updated(self):
        patcher = mock.patch.object(main, "CONTROL", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.folder / main.ENGINE_UPDATED).write_text("", encoding="utf-8")

    async def test_nothing_comes_back_from_the_owner_until_they_say_so(self):
        self.asked("inventory tweaks")
        self.plan_answer(decisions=[{"number": 1, "outcome": "needs_owner", "why": "It's in the engine."}])
        await self.agent.next_features()
        self.plan_answer()
        await self.agent.next_features()
        prompt = [call.args[2] for call in self.ask.await_args_list if call.args[1] == "director"][-1]
        self.assertIn("(no requests waiting)", prompt)
        self.assertEqual(self.status(1), feedback.NEEDS_OWNER)

    async def test_once_the_engine_changes_the_director_looks_again(self):
        self.asked("inventory tweaks", "faster boats")
        self.plan_answer(decisions=[{"number": 1, "outcome": "needs_owner", "why": "It's in the engine."}, {"number": 2, "outcome": "declined", "why": "Boats stay as they are.", "harm": "Every boat in the world would change."}])
        await self.agent.next_features()
        self.engine_updated()
        self.agent.sort_wanted.clear()
        self.agent.queue.append({"id": "already_queued", "node": "e_one", "spec": "x"})
        self.assertTrue(self.agent.should_plan(), "it shouldn't wait for the current plan to run out")
        self.agent.queue.clear()
        self.plan_answer([{"id": "tweaks", "node": "e_one", "spec": "x", "answers": [1]}])
        chosen = await self.agent.next_features()
        self.assertEqual([feature["id"] for feature in chosen], ["tweaks"])
        prompt = [call.args[2] for call in self.ask.await_args_list if call.args[1] == "director"][-1]
        self.assertIn('"status": "ask_again"', prompt)
        self.assertEqual((self.status(1), self.status(2)), (feedback.BUILDING, feedback.DECLINED), "only what was waiting on the owner comes back")

    async def test_touching_it_once_only_counts_once(self):
        self.asked("inventory tweaks")
        self.engine_updated()
        self.plan_answer()
        await self.agent.next_features()
        self.assertFalse(self.agent.engine_updated())
        self.plan_answer(decisions=[{"number": 1, "outcome": "needs_owner", "why": "It's in the engine."}])
        await self.agent.next_features()
        self.plan_answer()
        await self.agent.next_features()
        self.assertEqual(self.status(1), feedback.NEEDS_OWNER, "it isn't asked about again until it's touched again")

    async def test_the_same_answer_again_isnt_news_to_anyone(self):
        self.asked("menus of their own")
        self.plan_answer(decisions=[{"number": 1, "outcome": "needs_owner", "why": "It's in the engine."}])
        await self.agent.next_features()
        told = len(self.told())
        owner = (self.folder / "host_requests.jsonl").read_text(encoding="utf-8")
        self.engine_updated()
        await self.agent.next_features()
        self.assertEqual(self.status(1), feedback.NEEDS_OWNER)
        self.assertEqual(len(self.told()), told)
        self.assertEqual((self.folder / "host_requests.jsonl").read_text(encoding="utf-8"), owner)

    async def test_a_player_hears_theirs_is_being_looked_at_again(self):
        self.asked("inventory tweaks")
        self.agent.requests.mark(1, feedback.ASK_AGAIN)
        self.assertEqual(self.agent.requests.of_player("Dana")[0]["status"], "being looked at")

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


class CatchingUp(unittest.IsolatedAsyncioTestCase):
    """Something shipping while another feature waits its turn is nobody's mistake."""

    async def test_it_catches_up_and_asks_again(self):
        answers = [{"result": "blocked", "reason": f"x/y {workshop.STALE} any more."}, {"result": "passed_gates"}]
        with mock.patch.object(workshop, "ready_commit", return_value="abc") as commit, mock.patch.object(workshop, "request", mock.AsyncMock(side_effect=answers)), \
                mock.patch.object(workshop.asyncio, "sleep", mock.AsyncMock()):
            answer = await workshop.checked_against_main("gates", "message", "tree", "feature", "node", hurry=True)
        self.assertEqual(answer["result"], "passed_gates")
        self.assertEqual(commit.call_count, 2)

    async def test_a_real_problem_goes_back_to_the_builder_straight_away(self):
        request = mock.AsyncMock(return_value={"result": "blocked", "reason": "The texture is missing."})
        with mock.patch.object(workshop, "ready_commit", return_value="abc"), mock.patch.object(workshop, "request", request):
            answer = await workshop.checked_against_main("gates", "message", "tree", "feature", "node")
        self.assertEqual(request.await_count, 1)
        self.assertIn("texture", answer["reason"])


class ThePlan(Base):
    async def test_it_spoils_nothing_about_the_world(self):
        self.agent.tell = mock.AsyncMock()
        self.agent.building["grimble"] = {"id": "grimble", "node": "e_one", "category": "mob", "spec": "A creature called Grimble."}
        self.agent.queue.extend([{"id": "secret_ship", "node": "e_one", "category": "boss fight", "spec": "A flying ship."}, {"id": "secret", "node": "e_one", "category": "a Flying Ship", "spec": "x"},
                                 {"id": "unlabelled", "node": "nowhere", "spec": "x"}, {"id": "minimap", "node": "e_one", "small": True, "title": "a minimap", "spec": "A HUD."}])
        await self.agent.show_plan("Dana")
        said = "\n".join(call.args[1] for call in self.agent.tell.await_args_list)
        self.assertIn("Being built right now: §fearly game mob", said)
        self.assertIn("early game boss fight, early game, something new, a minimap", said)
        for secret in ("Grimble", "grimble", "Flying", "flying", "secret"):
            self.assertNotIn(secret, said)

    async def test_a_long_queue_is_cut_short(self):
        self.agent.tell = mock.AsyncMock()
        self.agent.queue.extend({"id": f"thing{number}", "node": "e_one", "category": "item"} for number in range(main.PLAN_SHOWN + 3))
        await self.agent.show_plan("Dana")
        self.assertIn("and 3 more", self.agent.tell.await_args_list[1].args[1])

    async def test_an_empty_plan_says_so(self):
        self.agent.tell = mock.AsyncMock()
        await self.agent.show_plan("Dana")
        self.assertIn("Being built right now: §fnothing", self.agent.tell.await_args_list[0].args[1])

    def test_every_category_reads_properly(self):
        graph = progression.read(main.PROGRESSION)
        for category in feedback.CATEGORIES:
            self.assertEqual(feedback.describe({"node": "e_one", "category": category}, graph), f"early game {category}")


class WhenToPlan(Base):
    def setUp(self):
        super().setUp()
        self.agent.queue.extend({"id": f"big{number}", "node": "e_one", "spec": "x"} for number in range(self.agent.governor.builders_allowed()))

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

    def test_it_plans_ahead_without_waiting_for_everything_to_finish(self):
        self.agent.queue.pop()
        self.agent.building["big"] = {"id": "big", "node": "e_one", "spec": "x"}
        self.assertTrue(self.agent.should_plan())


class WhichLane(Base):
    def building(self, *on):
        for number, lane in enumerate(on):
            self.agent.building[f"b{number}"] = {"id": f"b{number}", "lane": lane}

    def test_claude_goes_first(self):
        self.assertIsNone(self.agent.lane_with_room())

    def test_nothing_else_turned_on_means_it_waits_for_claude(self):
        self.building(None, None)
        self.assertIs(self.agent.lane_with_room(), False)

    def other_model(self, slots, takes_builders=False, up=True):
        self.agent.self_hosted = mock.Mock(lane=object(), slots=slots, **{"takes.return_value": takes_builders and up, "is_up.return_value": up})

    def test_builders_moved_to_another_model_dont_touch_claude(self):
        self.other_model(1, takes_builders=True)
        self.assertEqual(self.agent.lane_with_room(), lanes.SELF_HOSTED)
        self.building(lanes.SELF_HOSTED)
        self.assertIs(self.agent.lane_with_room(), False)
        self.assertEqual(self.agent.big_slots(), 1)

    def test_while_that_model_is_down_they_go_back_to_claude(self):
        self.other_model(1, takes_builders=True, up=False)
        self.assertIsNone(self.agent.lane_with_room())
        self.building(None, None)
        self.assertIs(self.agent.lane_with_room(), False)

    def test_a_self_hosted_model_takes_what_claude_has_no_room_for(self):
        self.other_model(1)
        self.building(None, None)
        self.assertEqual(self.agent.lane_with_room(), lanes.SELF_HOSTED)
        self.building(None, None, lanes.SELF_HOSTED)
        self.assertIs(self.agent.lane_with_room(), False)

    def test_other_machines_take_what_is_left(self):
        self.agent.hub.free_slots.return_value = 1
        self.building(None, None)
        self.assertEqual(self.agent.lane_with_room(), lanes.REMOTE)

    def test_a_warning_from_the_plan_moves_work_over_by_itself(self):
        self.other_model(2)
        self.agent.governor.builders_allowed.return_value = 1
        self.building(None)
        self.assertEqual(self.agent.lane_with_room(), lanes.SELF_HOSTED)

    def test_small_jobs_never_count_against_big_slots(self):
        self.agent.building["small"] = {"id": "small", "small": True}
        self.assertIsNone(self.agent.lane_with_room())

    def test_planning_keeps_enough_waiting_for_every_slot(self):
        self.other_model(3)
        self.agent.hub.free_slots.return_value = 2
        self.assertEqual(self.agent.big_slots(), 2 + 3 + 2)


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
