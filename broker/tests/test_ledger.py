"""What's kept about each build for the website, and what's taken out of it first. Needs the agent's libraries, so it runs in the agent's image."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock, UserMessage

from orchestrator import bugs, ledger, main, scrub, workshop


class Scrubbing(unittest.TestCase):
    def test_what_looks_like_a_secret_goes(self):
        for text in ("sk-abcdefghijklmnopqrstuvwxyz", "ghp_abcdefghijklmnopqrstuvwxyz123456", "Authorization: Bearer abc.def-ghi_jkl", "api_key=hunter2hunter2", "PASSWORD: correct-horse",
                     "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.abcdefgh", "0123456789abcdef0123456789abcdef01234567", "aB3dEf9hIj2lMn5pQr8tUv1xYz4AbCdEfGh", "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"):
            self.assertNotIn(text.split()[-1], scrub.secrets(text), text)

    def test_ordinary_text_stays(self):
        for text in ("mods/genesis/features/brass_kiln/assets/textures/0003_scene_panel_brass_kiln_brass_kiln_block.png", "public static final int LONGEST = 40;", "A machine that melts metal into plates."):
            self.assertEqual(scrub.secrets(text), text)

    def test_addresses_go(self):
        self.assertNotIn("10.1.2.3", scrub.secrets("ssh someone@10.1.2.3:22 now"))

    def test_a_secret_thats_been_read_is_known_whatever_it_looks_like(self):
        scrub.keep_out("plainwordspass")
        self.addCleanup(scrub._KNOWN.discard, "plainwordspass")
        self.assertEqual(scrub.secrets("it was plainwordspass all along"), "it was (hidden) all along")

    def test_who_plays_and_what_they_said_in_private_goes(self):
        clean = scrub.Scrubber(["Dana", "x"], ["I really want a castle made of cheese please"])
        self.assertEqual(clean("Requested by Dana, and dana again."), "Requested by a player, and a player again.")
        self.assertEqual(clean("They said they really want a castle made of cheese today"), "They said they (private) today")
        self.assertEqual(clean("a castle made of stone"), "a castle made of stone")
        self.assertEqual(clean("x marks the spot"), "x marks the spot")

    def test_it_can_cut_something_long(self):
        text = scrub.Scrubber()("x" * 10 + "y" * 100 + "z" * 10, 40)
        self.assertLess(len(text), 100)
        self.assertTrue(text.startswith("xxx") and text.endswith("zzz"))


def assistant(*blocks, message_id="m1", usage=None, parent=None):
    return AssistantMessage(content=list(blocks), model="x", parent_tool_use_id=parent, usage=usage, message_id=message_id)


def result(usage=None, model_usage=None, is_error=False):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error, num_turns=1, session_id="s", stop_reason="end_turn", total_cost_usd=0.5, usage=usage, model_usage=model_usage, result="done")


class Records(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        for name, value in (("FOLDER", self.folder), ("_open", {}), ("_loaded", True), ("_scrubber", None)):
            patcher = mock.patch.object(ledger, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        ledger.configure(lambda: (["Dana"], ["I really want a castle made of cheese please"]))
        self.addCleanup(ledger.configure, lambda: ((), ()))

    def read(self, run):
        return json.loads(run.path.read_text(encoding="utf-8"))

    def entries(self, run):
        return [json.loads(line) for line in run.transcript.read_text(encoding="utf-8").splitlines()]

    def test_a_spec_is_scrubbed_before_its_kept(self):
        run = ledger.open_run("kiln", "kiln", spec="Dana said I really want a castle made of cheese please, sk-abcdefghijklmnopqrstuvwxyz", stage="early", kind="feature", safe_name="a thing")
        saved = run.path.read_text(encoding="utf-8")
        for word in ("Dana", "cheese", "sk-abc"):
            self.assertNotIn(word, saved)
        self.assertTrue(ledger.page_id("x") and run.data["page"] not in saved.replace(run.data["page"], "", 1))

    def test_a_page_id_doesnt_give_the_name_away_and_stays_the_same(self):
        first = ledger.page_id("kiln-1")
        self.assertEqual(first, ledger.page_id("kiln-1"))
        self.assertNotEqual(first, ledger.page_id("kiln-2"))
        self.assertRegex(first, r"^[0-9a-f]{20}$")
        self.assertNotIn("kiln", first)

    def test_a_conversation_is_kept_with_what_it_used(self):
        run = ledger.open_run("kiln", "kiln", spec="x", kind="feature")
        token = ledger.ACTIVE.set(run)
        self.addCleanup(ledger.ACTIVE.reset, token)
        call = ledger.call("builder", "Build the kiln.")
        call.heard(assistant(ThinkingBlock(thinking="hmm", signature="s"), TextBlock(text="Starting."), usage={"input_tokens": 100, "output_tokens": 1}))
        call.heard(assistant(ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}), usage={"input_tokens": 100, "output_tokens": 5}))
        call.heard(UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="file.txt", is_error=False)]))
        self.assertEqual(run.data["tokens"]["builder"], {"input": 100, "output": 5, "cache_read": 0, "cache_write": 0})
        call.answered(result(usage={"input_tokens": 300, "output_tokens": 50}), 0.5)
        run.save()
        saved = self.read(run)
        self.assertEqual(saved["tokens"]["builder"]["input"], 300)
        self.assertEqual(saved["tokens"]["builder"]["output"], 50)
        self.assertEqual(saved["prompts"][0]["text"], "Build the kiln.")
        self.assertEqual([entry["kind"] for entry in self.entries(run)], ["prompt", "think", "say", "use", "got", "end"])

    def test_what_a_model_used_counts_its_helpers_too(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        ledger.ACTIVE.set(run)
        call = ledger.call("builder", "go")
        call.answered(result(usage={"input_tokens": 10, "output_tokens": 1}, model_usage={"a": {"inputTokens": 100, "outputTokens": 10}, "b": {"inputTokens": 5, "outputTokens": 5}}))
        self.assertEqual(run.data["tokens"]["builder"]["input"], 105)
        ledger.ACTIVE.set(None)

    def test_a_call_outside_a_build_does_nothing(self):
        ledger.ACTIVE.set(None)
        call = ledger.call("builder", "private words")
        call.heard(assistant(TextBlock(text="hello")))
        call.answered(result())
        self.assertFalse(list(self.folder.rglob("*.jsonl")))

    def test_a_voice_speaking_during_a_build_isnt_recorded(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        token = ledger.ACTIVE.set(run)
        self.addCleanup(ledger.ACTIVE.reset, token)
        for role in ("news", "dm", "watcher", "triage", "mind", "interviewer", "teaser", "director", "bug_investigator"):
            call = ledger.call(role, "what a player wanted")
            call.heard(assistant(TextBlock(text="what it said to them")))
            call.answered(result())
        self.assertFalse(run.transcript.exists())
        self.assertNotIn("tokens", run.data)

    def test_what_came_back_from_somewhere_private_isnt_kept(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        token = ledger.ACTIVE.set(run)
        self.addCleanup(ledger.ACTIVE.reset, token)
        call = ledger.call("builder", "go")
        for number, command in enumerate(("cat /workspace/state/opening.json", "printenv", "env | grep X", "cat /proc/self/environ", "cat /run/secrets/bridge", "ls /home/agent/.claude/projects")):
            call.heard(assistant(ToolUseBlock(id=f"t{number}", name="Bash", input={"command": command}), message_id=f"m{number}"))
            call.heard(UserMessage(content=[ToolResultBlock(tool_use_id=f"t{number}", content=f"SECRETWORD{number}", is_error=False)]))
        # Wherever it came from, this is what the agent's saved state looks like.
        call.heard(assistant(ToolUseBlock(id="sneaky", name="Bash", input={"command": "sh ./x.sh"}), message_id="m9"))
        call.heard(UserMessage(content=[ToolResultBlock(tool_use_id="sneaky", content='{"private_chats": {"Dana": "SECRETWORD"}}', is_error=False)]))
        saved = run.transcript.read_text(encoding="utf-8")
        self.assertNotIn("SECRETWORD", saved)
        self.assertEqual(saved.count(ledger.NOT_SHOWN), 7)

    def test_an_ordinary_command_keeps_what_came_back(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        token = ledger.ACTIVE.set(run)
        self.addCleanup(ledger.ACTIVE.reset, token)
        call = ledger.call("builder", "go")
        for number, command in enumerate(("ls mods/genesis/features", "cat bible/theme.md", "python3 environment_map.py", 'make_art("a brief for the kiln")')):
            call.heard(assistant(ToolUseBlock(id=f"t{number}", name="Bash", input={"command": command}), message_id=f"m{number}"))
            call.heard(UserMessage(content=[ToolResultBlock(tool_use_id=f"t{number}", content=f"output{number}", is_error=False)]))
        self.assertEqual(run.transcript.read_text(encoding="utf-8").count(ledger.NOT_SHOWN), 0)

    def test_someone_elses_secret_in_what_a_builder_says_goes(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        token = ledger.ACTIVE.set(run)
        self.addCleanup(ledger.ACTIVE.reset, token)
        call = ledger.call("builder", "go")
        call.heard(assistant(TextBlock(text="Dana wants this. sk-abcdefghijklmnopqrstuvwxyz")))
        saved = run.transcript.read_text(encoding="utf-8")
        self.assertNotIn("Dana", saved)
        self.assertNotIn("sk-abc", saved)

    def test_a_status_keeps_a_phase_only_from_the_list(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        run.status("planning", "Reading\nthe theme")
        self.assertEqual(run.data["status"]["phase"], "planning")
        self.assertEqual(run.data["status"]["doing"], "Reading the theme")
        run.status("building the brass kiln", "x" * 500)
        self.assertIsNone(run.data["status"]["phase"])
        self.assertLess(len(run.data["status"]["doing"]), 300)

    def test_a_restart_carries_on_in_the_same_record_and_doesnt_count_the_wait(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        name = run.data["run"]
        run.data["resumed_at"] -= 100
        run.pause()
        self.assertAlmostEqual(run.data["seconds"], 100, delta=2)
        self.assertEqual(run.data["stage_now"], ledger.WAITING)
        again = ledger.open_run("kiln", "kiln", kind="feature")
        self.assertEqual(again.data["run"], name)
        self.assertTrue(again.active)
        with mock.patch.object(ledger, "_open", {}), mock.patch.object(ledger, "_loaded", False):
            loaded = ledger.find("kiln")
            self.assertEqual(loaded.data["run"], name)
            self.assertFalse(loaded.active)
            self.assertEqual(loaded.data["stage_now"], ledger.WAITING)

    def test_a_failure_is_recorded_with_its_spec_and_why(self):
        run = ledger.open_run("kiln", "kiln", spec="the spec", kind="feature")
        run.stage(ledger.TESTING, 1)
        run.problem("Gate static: it isn't valid")
        run.problem("Review: the art is muddy, Dana")
        run.finish("failed", timings={"total": 5})
        saved = self.read(run)
        self.assertEqual(saved["outcome"], "failed")
        self.assertEqual(saved["spec"], "the spec")
        self.assertEqual(saved["failure"]["kind"], "review")
        self.assertNotIn("Dana", saved["failure"]["reason"])
        self.assertEqual(len(saved["attempts"]), 2)
        self.assertIsNone(ledger.find("kiln"))

    def test_the_board_says_nothing_until_theres_a_theme(self):
        ledger.write_board(False, [{"id": "kiln", "spec": "SPECWORD"}], {"goal": "GOALWORD", "nodes": {}}, theme="THEMEWORD")
        saved = (self.folder / "board.json").read_text(encoding="utf-8")
        for word in ("SPECWORD", "GOALWORD", "THEMEWORD"):
            self.assertNotIn(word, saved)
        self.assertFalse(json.loads(saved)["chosen"])

    def test_the_board_only_carries_what_it_names(self):
        graph = {"goal": "the goal", "nodes": {"e": {"stage": "early", "name": "Dana's bit", "holds": "h", "opens_with": "o", "requires": []}}}
        run = ledger.open_run("kiln", "kiln", kind="feature")
        ledger.write_board(True, [{"id": "ore", "node": "e", "category": "mob", "spec": "for Dana", "answers": [3], "lane": "self_hosted", "queued_at": 5.0, "player": "Dana"}], graph, True, 7, "the theme")
        board = json.loads((self.folder / "board.json").read_text(encoding="utf-8"))
        self.assertNotIn("Dana", json.dumps(board))
        self.assertEqual(board["building"], [run.data["page"]])
        self.assertEqual(set(board["queue"][0]), {"key", "page", "run_page", "kind", "safe_name", "title", "category", "stage", "node", "spec", "queued_at"})
        self.assertEqual(board["queue"][0]["safe_name"], "early game mob")
        self.assertNotEqual(board["queue"][0]["page"], "ore")

    def test_nothing_about_the_record_can_stop_a_build(self):
        run = ledger.open_run("kiln", "kiln", kind="feature")
        with mock.patch.object(ledger, "_write_json", side_effect=OSError("disk full")):
            run.save()
            run.stage(ledger.BUILDING, 1)
            run.finish("failed")

    def test_what_came_before_is_brought_in_once(self):
        logs = self.folder / "logs"
        features = self.folder / "features" / "kiln"
        features.mkdir(parents=True)
        logs.mkdir()
        (features / "feature.json").write_text(json.dumps({"node": "e", "summary": "A kiln, for Dana.", "mobs": {"m": {"display": "Mob"}}}), encoding="utf-8")
        (logs / "features.jsonl").write_text(json.dumps({"at": 5.0, "feature": "kiln", "timings": {"build_1": 3.0, "total": 9.0}, "tier": "T2"}) + "\n", encoding="utf-8")
        (logs / "unfinished.jsonl").write_text(json.dumps({"at": 6.0, "feature": "gone", "problem": "Review: Dana's bit is wrong"}) + "\n", encoding="utf-8")
        graph = {"nodes": {"e": {"stage": "early"}}}
        ledger.bring_in_the_past(logs / "features.jsonl", logs / "unfinished.jsonl", self.folder / "features", self.folder / "trees", graph)
        rows = json.loads((self.folder / "old_builds.json").read_text(encoding="utf-8"))
        self.assertEqual([row["outcome"] for row in rows], ["released", "failed"])
        self.assertEqual(rows[0]["safe_name"], "early game mob")
        self.assertEqual(rows[0]["seconds"], 9.0)
        self.assertEqual(rows[1]["failure"]["kind"], "review")
        self.assertNotIn("Dana", json.dumps(rows))
        (logs / "features.jsonl").write_text("", encoding="utf-8")
        ledger.bring_in_the_past(logs / "features.jsonl", logs / "unfinished.jsonl", self.folder / "features", self.folder / "trees", graph)
        self.assertEqual(len(json.loads((self.folder / "old_builds.json").read_text(encoding="utf-8"))), 2)

    def test_a_builder_on_another_machine_hands_it_back(self):
        notes = ledger.Notebook()
        token = ledger.ACTIVE.set(notes)
        self.addCleanup(ledger.ACTIVE.reset, token)
        call = ledger.call("builder", "go")
        call.heard(assistant(TextBlock(text="said"), usage={"input_tokens": 10, "output_tokens": 2}))
        handed_back = notes.handed_back()
        self.assertEqual(handed_back["usage"]["input"], 10)
        run = ledger.open_run("kiln", "kiln", kind="feature")
        run.add_entries([*handed_back["transcript"], {"kind": "say", "text": "Dana's word"}, "junk"], handed_back["usage"], "builder")
        saved = run.transcript.read_text(encoding="utf-8")
        self.assertIn("said", saved)
        self.assertNotIn("Dana", saved)
        self.assertEqual(run.data["tokens"]["builder"]["input"], 10)


class TheAgent(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = pathlib.Path(folder.name)
        for name, value in (("FOLDER", self.folder), ("_open", {}), ("_loaded", True), ("_scrubber", None)):
            patcher = mock.patch.object(ledger, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.agent = main.Agent.__new__(main.Agent)
        self.agent.queue = []
        self.agent.building = {}
        self.agent.planning = False
        self.agent.interviews = {"Newcomer": mock.Mock(transcript=[{"from": "player", "text": "said in the interview so far"}])}
        self.agent.bugs = mock.Mock(reports={"1": {"player": "Reporter", "text": "reported in private"}, "2": {"player": bugs.CRASH_REPORTER, "text": "a crash"}})
        self.agent.state = {"briefs": {"Dana": {"wants": "wants a castle"}}, "private_chats": {"Dana": [{"from": "player", "text": "a private chat"}]}, "direction_chosen": True, "languages": {"Lang": "de_de"}, "notices": {"Away": []}}
        self.agent.roster = lambda: {"Rostered"}

    def test_a_queued_feature_keeps_the_first_time_it_joined(self):
        self.agent.add_to_queue([{"id": "one"}])
        first = self.agent.queue[0]["queued_at"]
        self.agent.add_to_queue([{"id": "two", "queued_at": 5.0}], first=True)
        self.agent.add_to_queue([{"id": "three"}])
        self.assertEqual([feature["id"] for feature in self.agent.queue], ["two", "one", "three"])
        self.assertEqual(self.agent.queue[0]["queued_at"], 5.0)
        self.assertEqual(self.agent.queue[1]["queued_at"], first)

    def test_it_knows_everyone_and_everything_said_in_private(self):
        names, said = self.agent.private_sources()
        self.assertEqual(names, {"Dana", "Newcomer", "Reporter", "Rostered", "Lang", "Away"})
        for words in ("wants a castle", "a private chat", "said in the interview so far", "reported in private"):
            self.assertTrue(any(words in text for text in said), words)

    def test_the_page_hears_what_its_given_and_nothing_else_of_the_state(self):
        ledger.configure(self.agent.private_sources)
        self.addCleanup(ledger.configure, lambda: ((), ()))
        self.agent.queue.append({"id": "ore", "node": "e", "spec": "for Dana", "category": "mob", "secret_field": "SECRETWORD"})
        self.agent.state["release_count"] = 3
        with mock.patch.object(main.progression, "read", return_value={"goal": "g", "nodes": {"e": {"stage": "early", "name": "n"}}}), mock.patch.object(main, "BIBLE", self.folder):
            self.agent.write_page_board()
        board = (self.folder / "board.json").read_text(encoding="utf-8")
        self.assertNotIn("SECRETWORD", board)
        self.assertNotIn("Dana", board)
        self.assertEqual(json.loads(board)["shipped"], 3)
        self.assertEqual(json.loads(board)["queue"][0]["safe_name"], "early game mob")

    def test_a_refused_feature_is_still_recorded(self):
        ledger.refused({"id": "ore", "spec": "the spec", "category": "mob", "queued_at": 3.0}, "Its node isn't in the progression.")
        saved = json.loads(next((self.folder / "runs").glob("ore-*.json")).read_text(encoding="utf-8"))
        self.assertEqual((saved["outcome"], saved["failure"]["kind"], saved["spec"]), ("failed", ledger.REFUSED, "the spec"))
        ledger.refused({"id": "../../etc/passwd"}, "Its id can't be used.")
        self.assertTrue(list((self.folder / "runs").glob("unnamed-*.json")))


class TheTool(unittest.IsolatedAsyncioTestCase):
    async def test_a_builder_can_report_and_its_record_hears(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(ledger, "FOLDER", pathlib.Path(folder)), mock.patch.object(ledger, "_open", {}), mock.patch.object(ledger, "_loaded", True):
            run = ledger.open_run("kiln", "kiln", kind="feature")
            token = ledger.ACTIVE.set(run)
            try:
                captured = {}
                with mock.patch.object(workshop, "create_sdk_mcp_server", side_effect=lambda name, tools: captured.update({tool.name: tool for tool in tools})):
                    workshop._tools_for("kiln", pathlib.Path(folder), "e")
            finally:
                ledger.ACTIVE.reset(token)
            await captured["report_status"].handler({"phase": "planning", "doing": "reading the theme"})
            self.assertEqual(run.data["status"]["doing"], "reading the theme")
            self.assertIn("mcp__broker__report_status", workshop.BUILDER_TOOLS)
            self.assertIn("mcp__broker__report_status", workshop.SMALL_TOOLS)

    async def test_on_another_machine_it_goes_through_the_hub(self):
        with tempfile.TemporaryDirectory() as folder:
            captured = {}
            ask = mock.AsyncMock(return_value={})
            with mock.patch.object(workshop, "create_sdk_mcp_server", side_effect=lambda name, tools: captured.update({tool.name: tool for tool in tools})):
                workshop._tools_for("kiln", pathlib.Path(folder), "e", ask=ask)
            await captured["report_status"].handler({"phase": "planning", "doing": "reading"})
            ask.assert_awaited_once_with("status", phase="planning", doing="reading")

    async def test_build_records_a_release_and_a_giving_up(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(ledger, "FOLDER", pathlib.Path(folder)), mock.patch.object(ledger, "_open", {}), mock.patch.object(ledger, "_loaded", True):
            shop = workshop.Workshop.__new__(workshop.Workshop)
            shop._build = mock.AsyncMock(return_value=None)
            self.assertIsNone(await shop.build("kiln", "spec", "e", "early", about="a thing", details={"category": "machine", "queued_at": 4.0}))
            self.assertEqual(ledger.find("kiln").data["stage_now"], ledger.WAITING)
            self.assertEqual(ledger.find("kiln").data["queued_at"], 4.0)
            shop._build = mock.AsyncMock(side_effect=RuntimeError("it broke"))
            with self.assertRaises(RuntimeError):
                await shop.build("kiln", "spec", "e", "early")
            self.assertIsNone(ledger.find("kiln"))
            saved = json.loads(next((pathlib.Path(folder) / "runs").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual((saved["outcome"], saved["failure"]["kind"]), ("failed", ledger.CRASHED))
            self.assertIsNone(ledger.ACTIVE.get())


if __name__ == "__main__":
    unittest.main()
